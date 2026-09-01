"""Etiquetado de canciones y traduccion de la peticion del usuario.

Spotify retiro `audio-features` en noviembre de 2024, asi que el perfil sonoro
se infiere del conocimiento que el modelo tiene de cada cancion (titulo,
artista, album, anyo). Es una estimacion, no una medicion: por eso cada
etiqueta lleva `confidence` y el buscador penaliza las inseguras.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable, Iterator

from app.llm import LLMError, Modelo
from app.vibes import AXES, CONTEXTS, QueryDraft, TrackVibe, TrackVibeBatch, VibeQuery

log = logging.getLogger(__name__)

BATCH_SIZE = 40

# Un fallo transitorio suelto se salta; una racha significa que algo va mal de
# verdad y no tiene sentido seguir recorriendo la biblioteca.
MAX_CONSECUTIVE_FAILURES = 3

# Por debajo de esto la interpretacion no filtra: los ejes son el 65% de la
# nota y sin ellos manda el vocabulario de contextos, que es mucho mas grueso.
MIN_TARGET_AXES = 3


class TaggingAborted(RuntimeError):
    """El etiquetado no puede continuar. El mensaje se muestra tal cual en la UI."""


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
  **Maximo 2, y solo si son obvios.** La mayoria de canciones encajan en 0, 1 o 2
  momentos; si te salen 4 no estas eligiendo, estas repartiendo. Una lista vacia es
  una respuesta perfectamente valida y frecuente.
  El criterio es: ¿pondrias *esta* cancion si alguien te pide musica para ese momento?
  No vale que el genero encaje de lejos. Un tema de club no es "cena_amigos" porque se
  pueda oir de fondo, ni "piscina_verano" porque sea alegre: `fiesta` ya lo cubre.
  Estas etiquetas solo sirven si separan unas canciones de otras.
- descriptors: hasta 6 adjetivos cortos en castellano, en minusculas, sin tildes
  (ej: "hipnotica", "veraniega", "nostalgica", "densa").
- confidence: cuanto se sostiene el perfil que acabas de dar. Si no reconoces la
  cancion y estas deduciendo del nombre del artista o del genero, pon un valor bajo
  (0-40). Nunca inventes seguridad que no tienes: una etiqueta con confidence bajo es
  util, una etiqueta segura y equivocada envenena la playlist.

Algunas canciones traen `tags:` con etiquetas de la comunidad de Last.fm, ordenadas de
mas a menos usada. No son medidas acusticas: las escriben personas que han escuchado la
musica, y son la mejor pista disponible sobre genero, escena y epoca.

Importante: **esos tags son del album y del artista, no de la cancion**. A nivel de tema
Last.fm no tiene nada. Eso significa que situan el terreno -si un artista es neurofunk o
french house, si un disco es de 2019- pero no distinguen una balada de un corte bailable
del mismo album. Usalos para el genero y la produccion, y decide la energia, el
tempo_feel y la valence por lo que sepas de la cancion concreta.

Si no reconoces la cancion pero los tags situan bien al artista, el perfil deja de ser
una adivinanza a ciegas y puedes subir el confidence a la zona media (45-65). Reserva
lo bajo (0-40) para cuando ni la conoces ni hay tags utiles. Si los tags contradicen lo
que creias saber de la cancion, fiate de tu conocimiento y baja un poco el confidence.

Devuelve exactamente una entrada por cancion recibida, con el mismo track_id."""

QUERY_SYSTEM = f"""Traduces una peticion en lenguaje natural a un perfil de busqueda musical.

Ejes disponibles (0-100): {", ".join(AXES)}.
Contextos disponibles: {", ".join(CONTEXTS)}.

Reglas:
- `targets` es lo que de verdad filtra. Tiene un campo por eje, cada uno con `value`
  (0-100) y `weight` (0-1). Pon `value` en **al menos tres** ejes: casi cualquier
  momento describible determina energy y tempo_feel, y casi siempre valence.
  Deja `value` a null solo en los ejes que de verdad den igual: si a alguien no le
  importa que la musica sea acustica o electronica, acousticness va a null.
  No dejes los siete a null: sin ejes la seleccion la acaban decidiendo las etiquetas
  de contexto, que son mucho mas gruesas.
- `weight`: 1.0 en lo que la peticion pide explicitamente, 0.3-0.6 en lo que solo esta
  implicito.
- `contexts` solo si la peticion apunta claramente a uno.
- `descriptors`: adjetivos en minusculas y sin tildes que deberia evocar la seleccion.
- `avoid_descriptors`: lo que arruinaria el momento descrito.
- `label`: nombre corto y evocador para la playlist, en el idioma de la peticion.
- `notes`: una frase explicando como has interpretado la peticion.

Ejemplo: "momento calma en la piscina con una cervecita" ->
energy {{value 35, weight 1.0}}, valence {{value 75, weight 1.0}}, warmth {{value 80,
weight 0.7}}, tempo_feel {{value 35, weight 0.8}}, danceability {{value 55, weight 0.4}},
y acousticness/vocal_focus con value null porque la peticion no los determina;
contexts ["piscina_verano", "terraza_atardecer"]; descriptors ["veraniega",
"relajada", "luminosa"]; avoid ["agresiva", "oscura"]."""


class Tagger:
    """Las dos llamadas al modelo. No sabe que proveedor hay detras."""

    def __init__(self, model: Modelo):
        self.model = model

    def tag_batch(self, tracks: list[dict[str, Any]]) -> list[TrackVibe]:
        """Perfila un lote de canciones. Devuelve solo las que el modelo reconocio."""
        listing = "\n".join(_describe(t) for t in tracks)
        parsed = self.model.parse(
            TAGGER_SYSTEM,
            f"Perfila estas {len(tracks)} canciones:\n\n{listing}",
            TrackVibeBatch,
            max_tokens=16000,
        )
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
        self,
        tracks: list[dict[str, Any]],
        batch_size: int = BATCH_SIZE,
        prepare: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> Iterator[list[TrackVibe]]:
        """Genera los perfiles lote a lote para poder ir guardando el progreso.

        Lanza TaggingAborted si el problema no es del lote sino de la cuenta o
        la configuracion: seguir intentandolo solo retrasa el diagnostico.
        """
        consecutive = 0
        for chunk in _chunks(tracks, batch_size):
            if prepare is not None:
                # Enriquecer lote a lote, no de una: en una biblioteca grande,
                # resolver todo por adelantado son minutos con la barra parada.
                chunk = prepare(chunk)
            try:
                yield self.tag_batch(chunk)
                consecutive = 0
            except LLMError as exc:
                if exc.permanent:
                    raise TaggingAborted(exc.human) from exc
                # Un lote fallido puntual no debe tumbar un sync de 2.000
                # canciones: las que queden sin etiqueta se reintentan en la
                # proxima pasada. Una racha si, porque ya no es puntual.
                consecutive += 1
                log.error("Fallo al etiquetar un lote de %d: %s", len(chunk), exc)
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    raise TaggingAborted(
                        f"{consecutive} lotes seguidos han fallado. {exc.human}"
                    ) from exc
                yield []

    def parse_query(self, prompt: str) -> VibeQuery:
        query = self._parse_query_once(prompt)
        if len(query.targets) < MIN_TARGET_AXES:
            # Sin ejes desaparece el 65% de la nota y la seleccion la deciden los
            # contextos, que el etiquetador reparte con mucha alegria: una lista de
            # "calma en la piscina" acaba llena de temas de fiesta que comparten la
            # etiqueta piscina_verano. Merece la pena una segunda llamada corta.
            log.info("Interpretacion con %d ejes; reintentando", len(query.targets))
            query = self._parse_query_once(prompt, insist=True)

        if not query.targets and not query.contexts and not query.descriptors:
            raise ValueError(
                "La peticion es demasiado vaga: describe un momento, un ambiente o una actividad"
            )
        if len(query.targets) < MIN_TARGET_AXES:
            # No se bloquea: con contextos y descriptores todavia se puede filtrar,
            # pero quien mira la pantalla debe saber que la nota es mas gruesa.
            query.notes += (
                " (Interpretacion poco concreta: casi sin ejes numericos, "
                "la seleccion se apoya en las etiquetas. Prueba a describir "
                "el ritmo y la intensidad que buscas.)"
            )
        return query

    def _parse_query_once(self, prompt: str, insist: bool = False) -> VibeQuery:
        messages = [prompt]
        if insist:
            messages.append(
                "Esa interpretacion se quedo sin ejes numericos en `targets`. "
                f"Vuelve a interpretarla poniendo al menos {MIN_TARGET_AXES} "
                "ejes con su valor 0-100, empezando por energy, tempo_feel y valence."
            )
        draft = self.model.parse(QUERY_SYSTEM, "\n\n".join(messages), QueryDraft,
                                 max_tokens=4000)
        if draft is None:
            raise ValueError("No se pudo interpretar la peticion")
        # QueryDraft tiene un campo por eje, asi que no hay ejes inventados que
        # descartar: el esquema ya no los admite.
        return draft.to_query()


def _describe(track: dict[str, Any]) -> str:
    line = (
        f"{track['id']} | {', '.join(track['artists'])} - {track['name']}"
        f" | album: {track.get('album') or '?'}"
        f" | anyo: {track.get('release_year') or '?'}"
    )
    tags = track.get("lastfm_tags")
    if tags:
        line += f" | tags: {', '.join(tags)}"
    return line


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
