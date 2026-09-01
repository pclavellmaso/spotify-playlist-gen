"""API local. Sirve el front y expone conexion, sync, etiquetado y generacion."""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.config import SCOPES, settings
from app.db import Library
from app.lastfm import LastfmClient, album_key, artist_key, merge
from app.matcher import blend, profile_from_tracks, select
from app.spotify import SpotifyAuthError, SpotifyClient, SpotifyError, TokenStore
from app.tagger import BATCH_SIZE, Tagger, TaggingAborted
from app.vibes import TAGGER_VERSION, VibeQuery

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("playlist-gen")

STATIC = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

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


# Un exception_handler tiene que *devolver* una respuesta. Lanzar HTTPException
# desde dentro no la convierte en 401: se propaga y sale un 500 con el traceback
# crudo, que es justo lo que no queremos que vea nadie.
@app.exception_handler(SpotifyAuthError)
def _auth_error(_request, exc: SpotifyAuthError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=401)


@app.exception_handler(SpotifyError)
def _spotify_error(_request, exc: SpotifyError) -> JSONResponse:
    return JSONResponse({"detail": explain_spotify(exc)}, status_code=502)


def explain_spotify(exc: SpotifyError) -> str:
    """Traduce un error de la Web API a algo accionable."""
    if exc.status == 403:
        return (
            "Spotify ha denegado la operacion (403). Comprueba, en "
            "developer.spotify.com/dashboard, que tu cuenta este anadida en "
            "User Management de la app y que sea Premium, obligatorio para el "
            "desarrollador desde marzo de 2026."
        )
    if exc.status == 404:
        return "Spotify no encuentra el recurso (404). Puede que la playlist ya no exista."
    if exc.status == 429:
        return "Spotify esta limitando las peticiones. Prueba en unos minutos."
    return str(exc)


# -- front ------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


PAGINAS = {
    "/": ("index.html", "inicio"),
    "/metodo": ("metodo.html", "metodo"),
    "/guia": ("guia.html", "guia"),
    "/app": ("app.html", "app"),
}


def _pagina(request: Request, ruta: str):
    plantilla, nombre = PAGINAS[ruta]
    return templates.TemplateResponse(request, plantilla, {"page": nombre})


@app.get("/")
def inicio(request: Request):
    return _pagina(request, "/")


@app.get("/metodo")
def metodo(request: Request):
    return _pagina(request, "/metodo")


@app.get("/guia")
def guia(request: Request):
    return _pagina(request, "/guia")


@app.get("/app")
def estudio(request: Request):
    return _pagina(request, "/app")


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
    return RedirectResponse("/app")


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

        # Se pregunta por artista y album, no por cancion: a nivel de tema
        # Last.fm devuelve vacio siempre. Varias canciones comparten entidad,
        # asi que un lote de 40 suele resolverse con muchas menos peticiones.
        needed: dict[str, tuple[str, str]] = {}
        for track in chunk:
            artist = (track["artists"] or [""])[0]
            if not artist:
                continue
            needed[artist_key(artist)] = ("artist", artist)
            if track.get("album"):
                needed[album_key(artist, track["album"])] = ("album", artist)

        cached = library.lastfm_tags(list(needed))
        fetched: dict[str, list[str]] = {}
        for key, (kind, artist) in needed.items():
            if key in cached:
                continue
            # Se cachea tambien la lista vacia: "Last.fm no lo conoce" es una
            # respuesta, y no hay que volver a preguntarla en cada pasada.
            if kind == "artist":
                fetched[key] = lastfm.artist_tags(artist)
            else:
                fetched[key] = lastfm.album_tags(artist, key.split("|", 1)[1])
        if fetched:
            library.save_lastfm_tags(fetched)

        tags = {**cached, **fetched}
        out = []
        for track in chunk:
            artist = (track["artists"] or [""])[0]
            album = tags.get(album_key(artist, track["album"]), []) if track.get("album") else []
            out.append({**track, "lastfm_tags": merge(album, tags.get(artist_key(artist), []))})
        return out

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
    order: str = Field(default="rise", pattern="^(rise|fall|peak|score|flow)$")
    target_minutes: int | None = Field(default=None, ge=5, le=600)
    exclude: list[str] = Field(default_factory=list)


def _selection(query: VibeQuery, req: Any) -> dict[str, Any]:
    tracks = library.tagged_tracks(req.source, TAGGER_VERSION)
    if not tracks:
        raise HTTPException(400, "No hay canciones etiquetadas. Sincroniza y etiqueta primero.")

    excluir = set(req.exclude or [])
    pool = [t for t in tracks if t["id"] not in excluir]

    picked = select(
        pool,
        query,
        limit=req.limit,
        min_score=req.min_score,
        max_per_artist=req.max_per_artist,
        order=req.order,
        target_minutes=req.target_minutes,
    )
    return {
        "query": query.model_dump(),
        "pool": len(pool),
        "min_score": req.min_score,
        "order": req.order,
        "minutes": round(sum(t.get("duration_ms") or 0 for t in picked) / 60000),
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


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    try:
        query = _tagger().parse_query(req.prompt)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _selection(query, req)


class MoreRequest(BaseModel):
    """Ampliar una seleccion ya hecha, sin volver a interpretar la frase."""

    query: VibeQuery
    source: str = "liked"
    limit: int = Field(default=40, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=0, le=100)
    max_per_artist: int = Field(default=2, ge=1, le=10)
    order: str = Field(default="rise", pattern="^(rise|fall|peak|score|flow)$")
    target_minutes: int | None = Field(default=None, ge=5, le=600)
    exclude: list[str] = Field(default_factory=list)


@app.post("/api/more")
def more(req: MoreRequest) -> dict[str, Any]:
    """Devuelve la seleccion entera con el liston mas bajo, no solo lo nuevo.

    Reutiliza la interpretacion que ya devolvio /api/generate, asi que no gasta
    una llamada al modelo y, sobre todo, no cambia de idea a mitad: "mas
    canciones" significa las siguientes mejores para *esta misma* peticion.

    Se rehace la seleccion completa en vez de anadir por debajo porque el tope
    por artista y el orden por curva de energia son globales: encajar las nuevas
    en la lista existente daria un resultado distinto al de pedirlas de una vez.
    """
    return _selection(req.query, req)


class ExtendRequest(BaseModel):
    """Proponer canciones para una playlist que ya existe."""

    playlist_id: str = Field(min_length=1)
    prompt: str = Field(default="", description="Contexto extra, opcional")
    source: str = "liked"
    limit: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=55.0, ge=0, le=100)
    max_per_artist: int = Field(default=2, ge=1, le=10)
    order: str = Field(default="rise", pattern="^(rise|fall|peak|score|flow)$")
    target_minutes: int | None = Field(default=None, ge=5, le=600)
    exclude: list[str] = Field(default_factory=list)


@app.post("/api/extend")
def extend(req: ExtendRequest) -> dict[str, Any]:
    """Busca canciones que peguen con una playlist que ya existe.

    El nombre de una playlist es una pista pobre -"Piknik" o "b2b" no dicen
    gran cosa-, asi que el objetivo sale del perfil medio de lo que ya tiene
    dentro. Si ademas escribes algo, eso manda sobre el centroide en los ejes
    que menciones: "como esta pero mas tranquilo" es la lista con la energia
    cambiada, no una peticion desde cero.

    No toca la playlist: devuelve la propuesta para que la revises.
    """
    dentro = spotify.playlist_tracks(req.playlist_id)
    if not dentro:
        raise HTTPException(400, "Esa playlist esta vacia o no se pudo leer")

    ids_dentro = {t["id"] for t in dentro}
    perfilados = [
        t for t in library.tagged_tracks(req.source, TAGGER_VERSION) if t["id"] in ids_dentro
    ]
    nombre = spotify.playlist_name(req.playlist_id) or "esta lista"
    if not perfilados:
        raise HTTPException(
            400,
            f"Ninguna cancion de «{nombre}» esta analizada todavia. Analizala como "
            "origen para poder usarla de referencia.",
        )

    query = profile_from_tracks(perfilados, label=nombre)
    if req.prompt.strip():
        try:
            query = blend(query, _tagger().parse_query(req.prompt))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # Lo que ya esta dentro no se vuelve a proponer.
    req.exclude = list(ids_dentro | set(req.exclude))
    body = _selection(query, req)
    body["playlist"] = {"id": req.playlist_id, "name": nombre, "total": len(dentro)}
    body["reference"] = len(perfilados)
    # Se devuelve para que ampliar la busqueda pueda seguir excluyendo lo que
    # ya esta dentro sin volver a leer la playlist de Spotify.
    body["exclude"] = req.exclude
    return body


class AppendRequest(BaseModel):
    playlist_id: str = Field(min_length=1)
    track_ids: list[str] = Field(min_length=1)


@app.post("/api/append")
def append(req: AppendRequest) -> dict[str, Any]:
    """Anade a una playlist existente, sin tocar lo que ya tiene."""
    added = spotify.add_to_playlist(req.playlist_id, req.track_ids)
    return {
        "id": req.playlist_id,
        "added": added,
        "url": f"https://open.spotify.com/playlist/{req.playlist_id}",
    }


class SaveRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    track_ids: list[str] = Field(min_length=1)
    public: bool = False


@app.post("/api/save")
def save(req: SaveRequest) -> dict[str, Any]:
    return spotify.create_playlist(req.name, req.description, req.track_ids, req.public)
