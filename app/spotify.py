"""Cliente minimo de la Web API de Spotify (OAuth Authorization Code + PKCE).

PKCE evita tener que guardar el client secret en local. Solo se usan endpoints
que siguen disponibles en Developer Mode: perfil, likes, playlists propias y
creacion de playlists. Nada de audio-features ni recommendations.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterator

import httpx2 as httpx

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"


class SpotifyAuthError(RuntimeError):
    pass


class SpotifyError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Spotify {status}: {message}")
        self.status = status


def make_pkce_pair() -> tuple[str, str]:
    """Devuelve (code_verifier, code_challenge)."""
    verifier = base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


class TokenStore:
    """Guarda el token en disco con permisos 0600."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return None

    def save(self, token: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(token))
        self.path.chmod(0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class SpotifyClient:
    def __init__(self, client_id: str, redirect_uri: str, store: TokenStore):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.store = store

    # -- OAuth -------------------------------------------------------------
    def authorize_url(self, scopes: str) -> tuple[str, str, str]:
        """Devuelve (url, state, code_verifier)."""
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{AUTH_URL}?{httpx.QueryParams(params)}", state, verifier

    def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            },
            timeout=20.0,
        )
        if resp.status_code != 200:
            raise SpotifyAuthError(f"No se pudo canjear el codigo: {resp.text}")
        return self._store_token(resp.json())

    def _store_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
        existing = self.store.load() or {}
        # Spotify no siempre reenvia el refresh_token al refrescar.
        if "refresh_token" not in payload and "refresh_token" in existing:
            payload["refresh_token"] = existing["refresh_token"]
        self.store.save(payload)
        return payload

    def _refresh(self, refresh_token: str) -> dict[str, Any]:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            },
            timeout=20.0,
        )
        if resp.status_code != 200:
            self.store.clear()
            raise SpotifyAuthError("La sesion de Spotify caduco, vuelve a conectar")
        return self._store_token(resp.json())

    def access_token(self) -> str:
        token = self.store.load()
        if not token:
            raise SpotifyAuthError("No hay sesion de Spotify")
        if token.get("expires_at", 0) <= time.time():
            token = self._refresh(token["refresh_token"])
        return token["access_token"]

    @property
    def connected(self) -> bool:
        return self.store.load() is not None

    # -- HTTP --------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("http") else f"{API}{path}"
        for attempt in range(5):
            resp = httpx.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.access_token()}"},
                timeout=30.0,
                **kwargs,
            )
            if resp.status_code == 429:
                # Spotify indica la espera exacta; respetarla es obligatorio.
                wait = int(resp.headers.get("Retry-After", "2"))
                time.sleep(min(wait, 30) + attempt)
                continue
            if resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            if resp.status_code == 401:
                raise SpotifyAuthError("Token rechazado, vuelve a conectar")
            if resp.status_code >= 400:
                raise SpotifyError(resp.status_code, resp.text)
            return resp.json() if resp.content else None
        raise SpotifyError(429, "Spotify sigue limitando las peticiones")

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        page = self._request("GET", path, params=params or {})
        while page:
            yield from page.get("items", [])
            nxt = page.get("next")
            page = self._request("GET", nxt) if nxt else None

    # -- endpoints ---------------------------------------------------------
    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def playlists(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "total": p.get("tracks", {}).get("total", 0),
                "owner": p.get("owner", {}).get("display_name"),
            }
            for p in self._paginate("/me/playlists", {"limit": 50})
            if p
        ]

    def liked_tracks(self) -> list[dict[str, Any]]:
        items = self._paginate("/me/tracks", {"limit": 50})
        return [t for t in (_normalize(i, "liked") for i in items) if t]

    def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        items = self._paginate(
            f"/playlists/{playlist_id}/tracks",
            {"limit": 100, "additional_types": "track"},
        )
        source = f"playlist:{playlist_id}"
        return [t for t in (_normalize(i, source) for i in items) if t]

    def create_playlist(
        self, name: str, description: str, track_ids: list[str], public: bool = False
    ) -> dict[str, Any]:
        user_id = self.me()["id"]
        playlist = self._request(
            "POST",
            f"/users/{user_id}/playlists",
            json={
                "name": name[:100],
                "description": description[:300],
                "public": public,
            },
        )
        # La API acepta 100 uris por llamada.
        for i in range(0, len(track_ids), 100):
            chunk = track_ids[i : i + 100]
            self._request(
                "POST",
                f"/playlists/{playlist['id']}/tracks",
                json={"uris": [f"spotify:track:{tid}" for tid in chunk]},
            )
        return {
            "id": playlist["id"],
            "name": playlist["name"],
            "url": playlist.get("external_urls", {}).get("spotify"),
            "added": len(track_ids),
        }


def _normalize(item: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Aplana un item de /me/tracks o /playlists/{id}/tracks.

    Devuelve None para episodios de podcast, locales y tracks retirados: no
    tienen id utilizable y romperian la creacion de playlists.
    """
    track = item.get("track") or {}
    if not track.get("id") or track.get("is_local") or track.get("type") != "track":
        return None
    release = (track.get("album") or {}).get("release_date") or ""
    return {
        "id": track["id"],
        "name": track["name"],
        "artists": [a["name"] for a in track.get("artists", [])],
        "album": (track.get("album") or {}).get("name"),
        "release_year": int(release[:4]) if release[:4].isdigit() else None,
        "duration_ms": track.get("duration_ms"),
        "popularity": track.get("popularity"),
        "source": source,
        "added_at": item.get("added_at"),
    }
