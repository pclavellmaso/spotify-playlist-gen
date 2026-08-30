"""Etiquetado de canciones y traduccion de la peticion del usuario, via Claude.

Spotify retiro `audio-features` en noviembre de 2024, asi que el perfil sonoro
se infiere del conocimiento que el modelo tiene de cada cancion (titulo,
artista, album, anyo). Es una estimacion, no una medicion: por eso cada
etiqueta lleva `confidence` y el buscador penaliza las inseguras.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Iterator

import anthropic

from app.vibes import AXES, CONTEXTS, TrackVibe, TrackVibeBatch, VibeQuery

log = logging.getLogger(__name__)

BATCH_SIZE = 40

# Prefijo estable: se cachea entre lotes y solo cambia si tocas el vocabulario.
TAGGER_SYSTEM = f"""Eres un critico musical que perfila canciones para un motor de playlists.

Para cada cancion de la lista devuelve un perfil con estos ejes, todos enteros de 0 a 100:
- energy: 0 = practicamente parada, 100 = maxima intensidad
- valence: 0 = oscura, triste o tensa, 100 = luminosa, alegre
- danceability: 0 = no invita a moverse, 100 = irresistible
- acousticness: 0 = produccion totalmente electronica, 100 = acustica y organica
- tempo_feel: la velocidad *percibida*, no el BPM real (una balada a 140 BPM se percibe lenta)
- vocal_focus: 0 = instrumental, 100 = la voz es el centro absoluto
- warmth: 0 = fria, metalica, afilada, 100 = calida, analogica, envolvente

Ademas:
- contexts: en que momentos encaja de forma natural. Solo de esta lista: {", ".join(CONTEXTS)}.
  Lista solo los que encajen de verdad; una lista vacia es una respuesta valida.
- descriptors: hasta 6 adjetivos cortos en castellano, en minusculas, sin tildes
  (ej: "hipnotica", "veraniega", "nostalgica", "densa").
- confidence: cuanto conoces esta cancion en concreto. Si no la reconoces y estas
  deduciendo el perfil del nombre del artista o del genero, pon un valor bajo (0-40).
  Nunca inventes seguridad que no tienes: una etiqueta con confidence bajo es util,
  una etiqueta segura y equivocada envenena la playlist.

Devuelve exactamente una entrada por cancion recibida, con el mismo track_id."""

QUERY_SYSTEM = f"""Traduces una peticion en lenguaje natural a un perfil de busqueda musical.

Ejes disponibles (0-100): {", ".join(AXES)}.
Contextos disponibles: {", ".join(CONTEXTS)}.

Reglas:
- En `targets` incluye SOLO los ejes que la peticion determina de verdad. Si a alguien
  le da igual si la musica es acustica o electronica, no pongas acousticness.
  Menos ejes bien elegidos filtran mejor que siete a ojo.
- En `weights` da 1.0 a lo que la peticion pide explicitamente y 0.3-0.6 a lo que solo
  esta implicito.
- `contexts` solo si la peticion apunta claramente a uno.
- `descriptors`: adjetivos en minusculas y sin tildes que deberia evocar la seleccion.
- `avoid_descriptors`: lo que arruinaria el momento descrito.
- `label`: nombre corto y evocador para la playlist, en el idioma de la peticion.
- `notes`: una frase explicando como has interpretado la peticion.

Ejemplo: "momento calma en la piscina con una cervecita" ->
targets con energy bajo-medio (~35), valence alto (~75), warmth alto (~80),
tempo_feel bajo (~35); contexts ["piscina_verano", "terraza_atardecer"];
descriptors ["veraniega", "relajada", "luminosa"]; avoid ["agresiva", "oscura"]."""


class Tagger:
    def __init__(self, model: str, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def tag_batch(self, tracks: list[dict[str, Any]]) -> list[TrackVibe]:
        """Perfila un lote de canciones. Devuelve solo las que el modelo reconocio."""
        listing = "\n".join(
            f"{t['id']} | {', '.join(t['artists'])} - {t['name']}"
            f" | album: {t.get('album') or '?'}"
            f" | anyo: {t.get('release_year') or '?'}"
            for t in tracks
        )
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=[
                {
                    "type": "text",
                    "text": TAGGER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Perfila estas {len(tracks)} canciones:\n\n{listing}",
                }
            ],
            output_format=TrackVibeBatch,
        )
        parsed = response.parsed_output
        if parsed is None:
            log.warning("El modelo no devolvio un lote valido; se omite")
            return []

        known = {t["id"] for t in tracks}
        # El modelo puede alucinar un id o repetir uno: quedarse solo con los pedidos.
        seen: set[str] = set()
        out: list[TrackVibe] = []
        for vibe in parsed.tracks:
            if vibe.track_id in known and vibe.track_id not in seen:
                seen.add(vibe.track_id)
                out.append(vibe)
        missing = len(tracks) - len(out)
        if missing:
            log.info("%d canciones sin perfil en este lote", missing)
        return out

    def tag_all(
        self, tracks: list[dict[str, Any]], batch_size: int = BATCH_SIZE
    ) -> Iterator[list[TrackVibe]]:
        """Genera los perfiles lote a lote para poder ir guardando el progreso."""
        for chunk in _chunks(tracks, batch_size):
            try:
                yield self.tag_batch(chunk)
            except anthropic.APIError as exc:
                # Un lote fallido no debe tumbar un sync de 2.000 canciones:
                # las que queden sin etiqueta se reintentan en la proxima pasada.
                log.error("Fallo al etiquetar un lote de %d: %s", len(chunk), exc)
                yield []

    def parse_query(self, prompt: str) -> VibeQuery:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=[
                {
                    "type": "text",
                    "text": QUERY_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
            output_format=VibeQuery,
        )
        query = response.parsed_output
        if query is None:
            raise ValueError("No se pudo interpretar la peticion")
        # Descartar ejes inventados antes de que lleguen al scorer.
        query.targets = {k: v for k, v in query.targets.items() if k in AXES}
        query.weights = {k: v for k, v in query.weights.items() if k in query.targets}
        if not query.targets and not query.contexts and not query.descriptors:
            raise ValueError(
                "La peticion es demasiado vaga: describe un momento, un ambiente o una actividad"
            )
        return query


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
