"""API local. Sirve el front y expone conexion, sync, etiquetado y generacion."""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import SCOPES, settings
from app.db import Library
from app.lastfm import LastfmClient
from app.matcher import select
from app.spotify import SpotifyAuthError, SpotifyClient, SpotifyError, TokenStore
from app.tagger import BATCH_SIZE, Tagger, TaggingAborted
from app.vibes import TAGGER_VERSION

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("playlist-gen")

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Spotify vibe playlists")
library = Library(settings.db_path)
spotify = SpotifyClient(
    settings.spotify_client_id,
    settings.spotify_redirect_uri,
    TokenStore(settings.token_path),
)

lastfm = LastfmClient(settings.lastfm_api_key)

# El flujo OAuth es de un solo usuario en local, con lo que basta memoria.
_pending_auth: dict[str, str] = {}

# Estado del etiquetado en curso; el front lo consulta cada pocos segundos.
_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "source": None,
    "done": 0,
    "total": 0,
    # El modelo responde un lote entero de golpe, asi que no hay progreso
    # observable dentro de un lote: lo unico honesto que se puede mostrar es
    # por donde va el recorrido.
    "batch": 0,
    "batches": 0,
    "error": None,
    "finished": False,
}


def _tagger() -> Tagger:
    try:
        return Tagger(settings.anthropic_model)
    except Exception as exc:  # falta la API key, normalmente
        raise HTTPException(500, f"No se pudo iniciar Claude: {exc}") from exc


@app.exception_handler(SpotifyAuthError)
def _auth_error(_request, exc: SpotifyAuthError):
    raise HTTPException(401, str(exc))


# -- front ------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# -- auth -------------------------------------------------------------------
@app.get("/api/status")
def status() -> dict[str, Any]:
    if not settings.spotify_client_id:
        return {"connected": False, "configured": False}
    if not spotify.connected:
        return {"connected": False, "configured": True}
    try:
        me = spotify.me()
    except (SpotifyAuthError, SpotifyError):
        return {"connected": False, "configured": True}
    return {
        "connected": True,
        "configured": True,
        "user": me.get("display_name") or me.get("id"),
        "model": settings.anthropic_model,
        "lastfm": lastfm.enabled,
        "sources": library.sources(),
    }


@app.get("/api/auth/login")
def login() -> RedirectResponse:
    if not settings.spotify_client_id:
        raise HTTPException(500, "Falta SPOTIFY_CLIENT_ID en .env")
    url, state, verifier = spotify.authorize_url(SCOPES)
    _pending_auth[state] = verifier
    return RedirectResponse(url)


@app.get("/api/auth/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"Spotify denego el acceso: {error}")
    verifier = _pending_auth.pop(state or "", None)
    if not code or not verifier:
        # Sin state valido no se puede distinguir de un CSRF.
        raise HTTPException(400, "Respuesta de OAuth invalida, reinicia la conexion")
    spotify.exchange_code(code, verifier)
    return RedirectResponse("/?connected=1")


@app.post("/api/auth/logout")
def logout() -> dict[str, bool]:
    spotify.store.clear()
    return {"ok": True}


# -- biblioteca -------------------------------------------------------------
@app.get("/api/playlists")
def playlists() -> list[dict[str, Any]]:
    return spotify.playlists()


class SyncRequest(BaseModel):
    source: str = Field(default="liked", description="'liked' o 'playlist:<id>'")


@app.post("/api/sync")
def sync(req: SyncRequest) -> dict[str, Any]:
    """Descarga la biblioteca a SQLite. No etiqueta nada todavia."""
    if req.source == "liked":
        tracks = spotify.liked_tracks()
    elif req.source.startswith("playlist:"):
        tracks = spotify.playlist_tracks(req.source.split(":", 1)[1])
    else:
        raise HTTPException(400, "source debe ser 'liked' o 'playlist:<id>'")

    library.upsert_tracks(tracks)
    return {"source": req.source, "synced": len(tracks), **library.stats(req.source, TAGGER_VERSION)}


@app.get("/api/stats")
def stats(source: str = "liked") -> dict[str, Any]:
    return {**library.stats(source, TAGGER_VERSION), "job": _job}


class TagRequest(BaseModel):
    source: str = "liked"
    limit: int | None = Field(default=None, description="Tope de canciones a etiquetar")


@app.post("/api/tag")
def tag(req: TagRequest) -> dict[str, Any]:
    """Lanza el etiquetado en segundo plano y devuelve al momento."""
    with _job_lock:
        if _job["running"]:
            raise HTTPException(409, "Ya hay un etiquetado en curso")
        pending = library.untagged(req.source, TAGGER_VERSION)
        if req.limit:
            pending = pending[: req.limit]
        if not pending:
            return {"started": False, "pending": 0}
        _job.update(
            running=True,
            source=req.source,
            done=0,
            total=len(pending),
            batch=0,
            batches=math.ceil(len(pending) / BATCH_SIZE),
            error=None,
            finished=False,
        )

    tagger = _tagger()

    def with_lastfm_tags(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Adjunta los tags de comunidad, del cache o preguntando lo que falte."""
        if not lastfm.enabled:
            return chunk
        cached = library.lastfm_tags([t["id"] for t in chunk])
        fetched: dict[str, list[str]] = {}
        for track in chunk:
            if track["id"] in cached:
                continue
            artist = (track["artists"] or [""])[0]
            # Se cachea tambien la lista vacia: "Last.fm no lo conoce" es una
            # respuesta, y no hay que volver a preguntarla en cada pasada.
            fetched[track["id"]] = lastfm.top_tags(artist, track["name"])
        if fetched:
            library.save_lastfm_tags(fetched)
        tags = {**cached, **fetched}
        return [{**t, "lastfm_tags": tags.get(t["id"], [])} for t in chunk]

    def worker() -> None:
        try:
            for vibes in tagger.tag_all(pending, prepare=with_lastfm_tags):
                if vibes:
                    library.save_vibes(vibes, TAGGER_VERSION)
                with _job_lock:
                    # Se avanza por lote completo aunque alguna cancion se caiga:
                    # asi la barra refleja el trabajo hecho, no el conseguido.
                    _job["done"] = min(_job["done"] + len(vibes), _job["total"])
                    _job["batch"] += 1
            with _job_lock:
                _job["finished"] = True
        except TaggingAborted as exc:
            # El mensaje ya viene redactado para la pantalla; el traceback no
            # aporta nada porque la causa es la cuenta o el .env, no el codigo.
            log.error("Etiquetado abortado: %s", exc)
            with _job_lock:
                _job["error"] = str(exc)
        except Exception as exc:
            log.exception("Etiquetado interrumpido")
            with _job_lock:
                _job["error"] = str(exc)
        finally:
            with _job_lock:
                _job["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, "pending": len(pending)}


# -- generacion -------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3)
    source: str = "liked"
    limit: int = Field(default=30, ge=1, le=100)
    min_score: float = Field(default=55.0, ge=0, le=100)
    max_per_artist: int = Field(default=2, ge=1, le=10)
    order: str = Field(default="flow", pattern="^(flow|score)$")


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    tracks = library.tagged_tracks(req.source, TAGGER_VERSION)
    if not tracks:
        raise HTTPException(400, "No hay canciones etiquetadas. Sincroniza y etiqueta primero.")

    try:
        query = _tagger().parse_query(req.prompt)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    picked = select(
        tracks,
        query,
        limit=req.limit,
        min_score=req.min_score,
        max_per_artist=req.max_per_artist,
        order=req.order,
    )
    return {
        "query": query.model_dump(),
        "pool": len(tracks),
        "tracks": [
            {
                "id": t["id"],
                "name": t["name"],
                "artists": t["artists"],
                "album": t["album"],
                "year": t["release_year"],
                "score": t["score"],
                "descriptors": t["descriptors"],
                "confidence": t["confidence"],
            }
            for t in picked
        ],
    }


class SaveRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    track_ids: list[str] = Field(min_length=1)
    public: bool = False


@app.post("/api/save")
def save(req: SaveRequest) -> dict[str, Any]:
    return spotify.create_playlist(req.name, req.description, req.track_ids, req.public)
