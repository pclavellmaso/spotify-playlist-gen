"""Puntuacion y seleccion de canciones. Sin LLM: deterministico y testeable.

La peticion ya viene traducida al mismo espacio que las canciones (VibeQuery),
asi que emparejar es una distancia ponderada mas unos ajustes.
"""
from __future__ import annotations

from typing import Any

from app.vibes import VibeQuery

# Cuanto pesa cada senyal en la nota final.
W_AXES = 0.65
W_CONTEXT = 0.20
W_DESCRIPTORS = 0.15

# Una etiqueta insegura no se descarta, se acerca a la media: si el modelo no
# conocia la cancion, su perfil no deberia decidir nada por si solo.
CONFIDENCE_FLOOR = 0.35


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
    if not query.targets or not axes:
        return None
    total_w = 0.0
    total_err = 0.0
    for axis, target in query.targets.items():
        if axis not in axes:
            continue
        weight = float(query.weights.get(axis, 1.0))
        if weight <= 0:
            continue
        total_w += weight
        total_err += weight * abs(axes[axis] - target) / 100
    if total_w == 0:
        return None
    return (1 - total_err / total_w) * 100


def _context_score(contexts: list[str], query: VibeQuery) -> float | None:
    if not query.contexts:
        return None
    if not contexts:
        # Sin contextos declarados no hay evidencia ni a favor ni en contra.
        return 50.0
    hits = len(set(contexts) & set(query.contexts))
    return 100.0 if hits else 25.0


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


def select(
    tracks: list[dict[str, Any]],
    query: VibeQuery,
    limit: int = 30,
    min_score: float = 55.0,
    max_per_artist: int = 2,
    order: str = "flow",
) -> list[dict[str, Any]]:
    """Puntua, filtra, diversifica y ordena la seleccion final."""
    scored = []
    for track in tracks:
        score = score_track(track, query)
        if score >= min_score:
            scored.append({**track, "score": score})

    scored.sort(key=lambda t: t["score"], reverse=True)

    # Sin el tope por artista, una peticion muy concreta devuelve el mismo disco
    # doce veces. Se rellena con los descartados si no se llega al limite.
    picked: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    per_artist: dict[str, int] = {}
    for track in scored:
        artist = (track["artists"] or ["?"])[0].lower()
        if per_artist.get(artist, 0) < max_per_artist:
            per_artist[artist] = per_artist.get(artist, 0) + 1
            picked.append(track)
        else:
            overflow.append(track)
        if len(picked) == limit:
            break
    if len(picked) < limit:
        picked.extend(overflow[: limit - len(picked)])

    if order == "flow":
        # Una playlist de ambiente se escucha mejor como una curva de energia
        # continua que como un ranking de afinidad.
        picked.sort(key=lambda t: t.get("axes", {}).get("energy", 50))
    return picked
