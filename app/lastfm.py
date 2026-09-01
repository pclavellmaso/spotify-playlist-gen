"""Tags de comunidad de Last.fm, como refuerzo del etiquetado.

El perfil de cada cancion lo infiere Claude de los metadatos, asi que en
catalogo nicho o muy reciente el modelo no reconoce el tema y baja el
`confidence` -que es lo correcto- pero el perfil que devuelve acaba siendo el
prior del genero: sobre una muestra de 90 canciones, dos tercios salieron por
debajo de 40 de confianza y sus ejes convergian todos al mismo sitio.

Last.fm no sabe nada de acustica, pero sus tags los escriben personas que si
han escuchado la musica: `trip-hop`, `neurofunk`, `french house`, `2019`.

**Se consultan album y artista, no la cancion.** `track.getTopTags` y el
`toptags` de `track.getInfo` vuelven vacios de forma sistematica -comprobado
incluso con Santana "Smooth" y Lizzo "Juice", con cientos de miles de oyentes-
asi que a nivel de tema no hay nada que usar. Album y artista si estan llenos.
El album es mas especifico y suele traer la epoca; el artista es la base.

La contrapartida es que dos canciones del mismo disco reciben los mismos tags,
asi que esto situa el genero y la epoca, no distingue una balada de un corte
bailable del mismo album. Al etiquetador se le dice explicitamente.

La API es gratuita para uso no comercial y pide no pasar de 5 peticiones por
segundo.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx2 as httpx

log = logging.getLogger(__name__)

API = "https://ws.audioscrobbler.com/2.0/"

# El ToS pide no pasar de 5 req/s por IP promediado a 5 minutos. Vamos holgados:
# el etiquetado es asincrono y no hay ninguna prisa.
MIN_INTERVAL = 0.25

# Los `count` de Last.fm son relativos (0-100). Por debajo de esto son tags de
# una persona suelta y suelen ser ruido.
MIN_COUNT = 5
MAX_TAGS = 8

# Tags que no dicen nada del sonido. La lista corta a proposito: es mejor dejar
# pasar algo de ruido que filtrar un genero util por exceso de celo.
JUNK = {
    "seen live", "favorites", "favourites", "favorite songs", "favourite songs",
    "spotify", "awesome", "love", "loved", "best", "beautiful", "good",
    "my music", "tracks", "songs", "music", "favorite", "favourite",
    "check out", "under 2000 listeners", "albums i own", "albums i own on vinyl",
}


def artist_key(artist: str) -> str:
    return f"artist:{artist.lower().strip()}"


def album_key(artist: str, album: str) -> str:
    return f"album:{artist.lower().strip()}|{album.lower().strip()}"


class LastfmClient:
    """Cliente minimo de Last.fm. Sin key, se desactiva en silencio."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._last_call = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def artist_tags(self, artist: str) -> list[str]:
        if not artist:
            return []
        return self._tags("artist.gettoptags", {"artist": artist}, drop={artist})

    def album_tags(self, artist: str, album: str) -> list[str]:
        if not artist or not album:
            return []
        return self._tags(
            "album.gettoptags", {"artist": artist, "album": album}, drop={artist, album}
        )

    def _tags(self, method: str, params: dict[str, str], drop: set[str]) -> list[str]:
        """Devuelve lista vacia ante cualquier problema: esto no puede tumbar
        un etiquetado de 1.800 canciones."""
        payload = self.consultar(method, params)
        return _clean(payload, drop) if payload else []

    def consultar(self, method: str, params: dict[str, str]) -> dict[str, Any]:
        """Llamada cruda, con el limite de peticiones y los errores ya tratados.

        Devuelve {} ante cualquier problema: ni el etiquetado ni el
        descubrimiento pueden caerse porque Last.fm tenga un mal dia.
        """
        if not self.enabled:
            return {}

        self._throttle()
        try:
            resp = httpx.get(
                API,
                params={
                    "method": method,
                    "api_key": self.api_key,
                    "autocorrect": 1,
                    "format": "json",
                    **params,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log.debug("Last.fm no respondio a %s %s: %s", method, params, exc)
            return {}

        if resp.status_code != 200:
            log.debug("Last.fm %s en %s %s", resp.status_code, method, params)
            return {}
        try:
            payload = resp.json()
        except ValueError:
            return {}

        if "error" in payload:
            # 6 = no esta en su catalogo, que es de lo mas normal.
            if payload.get("error") != 6:
                log.warning("Last.fm error %s: %s", payload.get("error"),
                            payload.get("message"))
            return {}

        return payload

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _clean(payload: dict[str, Any], drop: set[str]) -> list[str]:
    raw = (payload.get("toptags") or {}).get("tag") or []
    # Con un solo tag, Last.fm devuelve el objeto en vez de una lista de uno.
    if isinstance(raw, dict):
        raw = [raw]

    descartar = {d.lower().strip() for d in drop} | JUNK
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).lower().strip()
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if not name or len(name) > 30 or count < MIN_COUNT:
            continue
        if name in descartar or name in tags:
            continue
        tags.append(name)
        if len(tags) == MAX_TAGS:
            break
    return tags


def merge(album: list[str], artist: list[str], limit: int = MAX_TAGS) -> list[str]:
    """Album primero por ser mas especifico, artista para completar."""
    out: list[str] = []
    for tag in [*album, *artist]:
        if tag not in out:
            out.append(tag)
        if len(out) == limit:
            break
    return out


# --------------------------------------------------------------------------
# Descubrimiento
# --------------------------------------------------------------------------
# Spotify retiro `/recommendations`, `related-artists` y `top-tracks` de artista:
# los tres responden 404 o 403. El unico grafo de similitud que queda accesible
# es el de Last.fm, y es bueno: para Folamour devuelve Bellaire, Tour-Maubourg,
# Chaos in the CBD. Lo que NO sirve es `tag.getTopTracks`: esta dominado por
# popularidad y para "deep house" devuelve Madonna.
class Descubridor:
    """Artistas parecidos y sus temas principales, via Last.fm."""

    def __init__(self, cliente: LastfmClient):
        self.fm = cliente

    @property
    def enabled(self) -> bool:
        return self.fm.enabled

    def similares(self, artista: str, limite: int = 8) -> list[str]:
        datos = self.fm.consultar("artist.getsimilar", {"artist": artista, "limit": limite})
        crudo = (datos.get("similarartists") or {}).get("artist") or []
        if isinstance(crudo, dict):
            crudo = [crudo]
        return [a["name"] for a in crudo if isinstance(a, dict) and a.get("name")]

    def top_temas(self, artista: str, limite: int = 5) -> list[str]:
        datos = self.fm.consultar("artist.gettoptracks", {"artist": artista, "limit": limite})
        crudo = (datos.get("toptracks") or {}).get("track") or []
        if isinstance(crudo, dict):
            crudo = [crudo]
        return [t["name"] for t in crudo if isinstance(t, dict) and t.get("name")]
