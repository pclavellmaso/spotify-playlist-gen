"""Tags de comunidad de Last.fm, como refuerzo del etiquetado.

El perfil de cada cancion lo infiere Claude de los metadatos, asi que en
catalogo nicho o muy reciente el modelo no reconoce el tema y baja el
`confidence` -que es lo correcto- pero el perfil que devuelve acaba siendo el
prior del genero: sobre una muestra de 50 canciones, dos tercios salieron por
debajo de 40 de confianza y sus ejes convergian todos al mismo sitio.

Last.fm no sabe nada de acustica, pero sus tags los escriben personas que si
han escuchado el tema: `deep house`, `liquid dnb`, `balearic`, `summer`,
`chillout`. Pasarselos al tagger le da algo real sobre lo que trabajar en vez
de adivinar por el nombre del artista.

La API es gratuita para uso no comercial y pide no pasar de 5 peticiones por
segundo. Cada consulta se cachea en SQLite, incluidas las que no devuelven
nada, para no volver a preguntar por lo mismo.
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

# Los `count` de Last.fm son relativos al tema (0-100). Por debajo de esto son
# tags de una persona suelta y suelen ser ruido.
MIN_COUNT = 10
MAX_TAGS = 8

# Tags que no dicen nada del sonido. La lista corta a proposito: es mejor dejar
# pasar algo de ruido que filtrar un genero util por exceso de celo.
JUNK = {
    "seen live", "favorites", "favourites", "favorite songs", "favourite songs",
    "spotify", "awesome", "love", "loved", "best", "beautiful", "good",
    "my music", "tracks", "songs", "music", "favorite", "favourite",
    "check out", "under 2000 listeners", "albums i own",
}


class LastfmClient:
    """Cliente minimo de track.getTopTags. Sin key, se desactiva en silencio."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._last_call = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def top_tags(self, artist: str, track: str) -> list[str]:
        """Tags de comunidad de un tema, filtrados y ordenados por relevancia.

        Devuelve lista vacia si no hay key, si Last.fm no conoce el tema o si
        la peticion falla: el etiquetado debe seguir funcionando sin esto.
        """
        if not self.enabled or not artist or not track:
            return []

        self._throttle()
        try:
            resp = httpx.get(
                API,
                params={
                    "method": "track.gettoptags",
                    "artist": artist,
                    "track": track,
                    "api_key": self.api_key,
                    "autocorrect": 1,
                    "format": "json",
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log.debug("Last.fm no respondio para %s - %s: %s", artist, track, exc)
            return []

        if resp.status_code != 200:
            log.debug("Last.fm %s para %s - %s", resp.status_code, artist, track)
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []

        if "error" in payload:
            # 6 = el tema no existe en su catalogo, que es de lo mas normal.
            if payload.get("error") != 6:
                log.warning("Last.fm error %s: %s", payload.get("error"),
                            payload.get("message"))
            return []

        return _clean(payload, artist, track)

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _clean(payload: dict[str, Any], artist: str, track: str) -> list[str]:
    raw = (payload.get("toptags") or {}).get("tag") or []
    # Con un solo tag, Last.fm devuelve el objeto en vez de una lista de uno.
    if isinstance(raw, dict):
        raw = [raw]

    descartar = {artist.lower().strip(), track.lower().strip()} | JUNK
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
