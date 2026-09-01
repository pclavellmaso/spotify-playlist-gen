"""Puntuacion y seleccion de canciones. Sin LLM: deterministico y testeable.

La peticion ya viene traducida al mismo espacio que las canciones (VibeQuery),
asi que emparejar es una distancia ponderada mas unos ajustes.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from app.vibes import AXES, VibeQuery

# Cuanto pesa cada senyal en la nota final.
W_AXES = 0.65
W_CONTEXT = 0.20
W_DESCRIPTORS = 0.15

# Una etiqueta insegura no se descarta, se acerca a la media: si el modelo no
# conocia la cancion, su perfil no deberia decidir nada por si solo.
CONFIDENCE_FLOOR = 0.35

# Cuanto puede desviarse un eje antes de que deje de ser un matiz. Con 0.30, un
# desajuste de 15 puntos conserva el 78% del parecido, uno de 30 baja al 37% y
# uno de 45 cae al 11%.
AXIS_TOLERANCE = 0.30


def score_track(track: dict[str, Any], query: VibeQuery) -> float:
    """Nota de 0 a 100 de lo bien que la cancion encaja con la peticion."""
    axes_score = _axes_score(track.get("axes", {}), query)
    context_score = _context_score(track.get("contexts", []), query)
    desc_score, vetoed = _descriptor_score(track.get("descriptors", []), query)

    if vetoed:
        return 0.0

    # Los bloques sin senyal en la peticion se reparten entre los que si la tienen.
    parts = [(W_AXES, axes_score), (W_CONTEXT, context_score), (W_DESCRIPTORS, desc_score)]
    active = [(w, s) for w, s in parts if s is not None]
    if not active:
        return 0.0
    total_weight = sum(w for w, _ in active)
    raw = sum(w * s for w, s in active) / total_weight

    confidence = track.get("confidence", 50) / 100
    trust = CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR) * confidence
    # Se arrastra hacia 50 (neutro) en lugar de hacia 0: baja confianza no es
    # lo mismo que mal encaje.
    adjusted = 50 + (raw - 50) * trust
    return round(max(0.0, min(100.0, adjusted)), 2)


def _axes_score(axes: dict[str, int], query: VibeQuery) -> float | None:
    """Parecido con el perfil objetivo. Conjuntivo: fallar de lleno en un eje
    importante descarta, no se compensa acertando en otros.

    Antes esto era la media de los errores absolutos, y era demasiado
    indulgente: una peticion de "calma en la piscina" (energy 35, tempo_feel 35)
    puntuaba a Papi Chulo con un 68,7 pese a fallar por 43 y 45 puntos en esos
    dos ejes, porque acertaba en valence y warmth y la media repartia. Todo el
    ranking se comprimia en una franja estrecha y nada puntuaba mal de verdad.

    Ahora cada eje aporta un parecido con caida gaussiana -a partir de cierto
    desajuste deja de importar "un poco" y pasa a descalificar- y se combinan en
    media geometrica, que es la que expresa "todo esto tiene que cumplirse":
    un solo termino cerca de cero arrastra el resultado entero. Con eso, la
    misma cancion pasa de 68,7 a 27,6 y una que si encaja se queda en 75,3.
    """
    if not query.targets or not axes:
        return None
    total_w = 0.0
    log_sum = 0.0
    for axis, target in query.targets.items():
        if axis not in axes:
            continue
        weight = float(query.weights.get(axis, 1.0))
        if weight <= 0:
            continue
        error = abs(axes[axis] - target) / 100
        # log(exp(-x)) = -x, asi que el logaritmo se calcula directo y no hay
        # riesgo de log(0) por muy grande que sea el desajuste.
        log_sim = -((error / AXIS_TOLERANCE) ** 2)
        total_w += weight
        log_sum += weight * log_sim
    if total_w == 0:
        return None
    return math.exp(log_sum / total_w) * 100


def _context_score(contexts: list[str], query: VibeQuery) -> float | None:
    """Acierto de contexto, ponderado por lo especifica que sea la cancion.

    Un acierto plano de 100 premiaba a las canciones que se apuntan a todo: en
    una biblioteca real el etiquetador reparte 3,4 contextos por tema y `fiesta`
    aparece en el 57%, asi que casi cualquier cancion acertaba y el bloque
    dejaba de discriminar. Decir "encajo en 5 momentos" es afirmar menos sobre
    cada uno que decir "encajo en este": el acierto vale en proporcion.

    1 de 1 -> 100 · 1 de 2 -> 75 · 1 de 4 -> 62.5 · sin acierto -> 25
    """
    if not query.contexts:
        return None
    if not contexts:
        # Sin contextos declarados no hay evidencia ni a favor ni en contra.
        return 50.0
    hits = len(set(contexts) & set(query.contexts))
    if not hits:
        return 25.0
    return 50.0 + 50.0 * (hits / len(contexts))


def _descriptor_score(
    descriptors: list[str], query: VibeQuery
) -> tuple[float | None, bool]:
    """Devuelve (nota, vetada). El veto lo dispara un `avoid_descriptors`."""
    have = {d.lower() for d in descriptors}
    if have & {d.lower() for d in query.avoid_descriptors}:
        return None, True
    if not query.descriptors:
        return None, False
    if not have:
        return 50.0, False
    wanted = {d.lower() for d in query.descriptors}
    hits = len(have & wanted)
    if hits == 0:
        return 35.0, False
    return min(100.0, 55.0 + 22.5 * hits), False


ORDERS = ("score", "rise", "fall", "peak")

# `flow` era el unico modo de curva y equivalia a energia ascendente.
ORDER_ALIASES = {"flow": "rise"}


def select(
    tracks: list[dict[str, Any]],
    query: VibeQuery,
    limit: int = 30,
    min_score: float = 55.0,
    max_per_artist: int = 2,
    order: str = "rise",
    target_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """Puntua, filtra, diversifica y ordena la seleccion final.

    `target_minutes` manda sobre `limit` cuando se da: para un viaje o una
    fiesta, la unidad util es el tiempo, no el numero de canciones. `limit`
    sigue actuando como tope duro para que una duracion imposible no devuelva
    la biblioteca entera.
    """
    scored = []
    for track in tracks:
        score = score_track(track, query)
        if score >= min_score:
            scored.append({**track, "score": score})

    scored.sort(key=lambda t: t["score"], reverse=True)

    target_ms = target_minutes * 60_000 if target_minutes else None

    def lleno(elegidas: list[dict[str, Any]], ms: int) -> bool:
        if len(elegidas) >= limit:
            return True
        return target_ms is not None and ms >= target_ms

    # Sin el tope por artista, una peticion muy concreta devuelve el mismo disco
    # doce veces. Se rellena con los descartados si no se llega al limite.
    picked: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    per_artist: dict[str, int] = {}
    total_ms = 0
    for track in scored:
        if lleno(picked, total_ms):
            break
        artist = (track["artists"] or ["?"])[0].lower()
        if per_artist.get(artist, 0) < max_per_artist:
            per_artist[artist] = per_artist.get(artist, 0) + 1
            picked.append(track)
            total_ms += track.get("duration_ms") or 0
        else:
            overflow.append(track)

    for track in overflow:
        if lleno(picked, total_ms):
            break
        picked.append(track)
        total_ms += track.get("duration_ms") or 0

    return _ordenar(picked, ORDER_ALIASES.get(order, order))


def _ordenar(picked: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """Una playlist de ambiente se escucha mejor como una curva continua de
    energia que como un ranking de afinidad."""
    if order == "score":
        return sorted(picked, key=lambda t: t["score"], reverse=True)

    energia = sorted(picked, key=lambda t: t.get("axes", {}).get("energy", 50))
    if order == "fall":
        return list(reversed(energia))
    if order == "peak":
        # Sube hasta el pico y baja: las de menos energia se reparten a los dos
        # extremos y las mas intensas quedan en el centro.
        subida, bajada = [], []
        for i, track in enumerate(energia):
            (subida if i % 2 == 0 else bajada).append(track)
        return subida + list(reversed(bajada))
    return energia


def profile_from_tracks(
    tracks: list[dict[str, Any]], label: str = "Mas como esto"
) -> VibeQuery:
    """Perfil medio de un conjunto de canciones ya etiquetadas.

    Sirve para "mas como esto": en vez de adivinar el ambiente por el nombre de
    una playlist -"Piknik" o "b2b" no dicen gran cosa- se lee lo que ya hay
    dentro.

    Dos decisiones:

    - La media se pondera por `confidence`. Una cancion que el modelo no
      reconocio tiene un perfil que es casi el prior del genero; dejarla
      arrastrar el centroide seria mover el objetivo hacia la nada.
    - El peso de cada eje sale de su dispersion. Si todas las canciones rondan
      energia 80, la energia *define* la lista y debe pesar; si van de 20 a 95,
      no dice nada de ella y debe pesar poco. Eso distingue un perfil real de
      una media aritmetica sin sentido.
    """
    utiles = [t for t in tracks if t.get("axes")]
    if not utiles:
        raise ValueError("Ninguna de esas canciones esta analizada todavia")

    pesos = [max(t.get("confidence", 50), 10) / 100 for t in utiles]
    total = sum(pesos)

    targets: dict[str, int] = {}
    weights: dict[str, float] = {}
    for axis in AXES:
        valores = [t["axes"].get(axis, 50) for t in utiles]
        media = sum(v * w for v, w in zip(valores, pesos)) / total
        targets[axis] = round(media)
        dispersion = statistics.pstdev(valores) if len(valores) > 1 else 0.0
        # 35 puntos de desviacion es ya un eje que no caracteriza nada.
        weights[axis] = round(max(0.15, min(1.0, 1 - dispersion / 35)), 2)

    # Un contexto solo describe la lista si lo comparte buena parte de ella.
    conteo: dict[str, int] = {}
    for track in utiles:
        for ctx in track.get("contexts", []):
            conteo[ctx] = conteo.get(ctx, 0) + 1
    contexts = [c for c, n in conteo.items() if n / len(utiles) >= 0.3]

    desc: dict[str, int] = {}
    for track in utiles:
        for d in track.get("descriptors", []):
            desc[d] = desc.get(d, 0) + 1
    descriptors = [d for d, _ in sorted(desc.items(), key=lambda kv: -kv[1])[:5]]

    return VibeQuery(
        label=label,
        targets=targets,
        weights=weights,
        contexts=sorted(contexts, key=lambda c: -conteo[c])[:2],
        descriptors=descriptors,
        notes=f"Perfil medio de {len(utiles)} canciones ya analizadas de la lista.",
    )


def blend(base: VibeQuery, encima: VibeQuery) -> VibeQuery:
    """Deja que una peticion escrita mande sobre el perfil medio.

    Lo que el usuario pide explicitamente pesa 1.0 y pisa al centroide en ese
    eje; el resto de ejes los sigue aportando la lista, que es lo que da el
    caracter. Asi "Piknik, pero mas tranquilo" es la lista con la energia
    cambiada, no una peticion nueva desde cero.
    """
    targets = {**base.targets, **encima.targets}
    weights = dict(base.weights)
    for axis in encima.targets:
        weights[axis] = float(encima.weights.get(axis, 1.0))
    return VibeQuery(
        label=encima.label or base.label,
        targets=targets,
        weights=weights,
        contexts=encima.contexts or base.contexts,
        descriptors=sorted({*base.descriptors, *encima.descriptors}),
        avoid_descriptors=encima.avoid_descriptors,
        notes=encima.notes or base.notes,
    )
