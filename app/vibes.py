"""Vocabulario de 'vibe' compartido por el etiquetador y el buscador.

Todo el sistema se apoya en un espacio fijo de ejes numericos (0-100) mas un
vocabulario cerrado de contextos. Fijarlo tiene dos ventajas: el emparejamiento
es una distancia ponderada (barata, deterministica, testeable) y el modelo no
puede inventarse dimensiones nuevas entre lote y lote.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Ejes en los que se proyecta cada cancion. Cambiarlos invalida el cache de
# etiquetas: sube TAGGER_VERSION al tocar esta lista.
AXES: tuple[str, ...] = (
    "energy",        # 0 = casi parada, 100 = maxima intensidad
    "valence",       # 0 = oscura/triste, 100 = luminosa/alegre
    "danceability",  # 0 = no invita a moverse, 100 = irresistible
    "acousticness",  # 0 = totalmente electronica, 100 = acustica/organica
    "tempo_feel",    # 0 = se percibe lenta, 100 = se percibe rapida
    "vocal_focus",   # 0 = instrumental, 100 = la voz manda
    "warmth",        # 0 = fria/metalica, 100 = calida/analogica
)

CONTEXTS: tuple[str, ...] = (
    "piscina_verano",
    "terraza_atardecer",
    "fiesta",
    "after_hours",
    "cena_amigos",
    "romantico",
    "concentracion_trabajo",
    "entrenamiento",
    "conducir",
    "viaje_carretera",
    "desayuno_domingo",
    "tareas_casa",
    "melancolia_lluvia",
    "meditacion",
    "dormir",
)

# 2: el etiquetador recibe los tags de comunidad de Last.fm como contexto.
TAGGER_VERSION = 2

ContextName = Literal[
    "piscina_verano",
    "terraza_atardecer",
    "fiesta",
    "after_hours",
    "cena_amigos",
    "romantico",
    "concentracion_trabajo",
    "entrenamiento",
    "conducir",
    "viaje_carretera",
    "desayuno_domingo",
    "tareas_casa",
    "melancolia_lluvia",
    "meditacion",
    "dormir",
]


class TrackVibe(BaseModel):
    """Perfil de una cancion. Es lo que el modelo devuelve por cada track."""

    track_id: str = Field(description="El id de Spotify tal cual se recibio")
    energy: int = Field(ge=0, le=100)
    valence: int = Field(ge=0, le=100)
    danceability: int = Field(ge=0, le=100)
    acousticness: int = Field(ge=0, le=100)
    tempo_feel: int = Field(ge=0, le=100)
    vocal_focus: int = Field(ge=0, le=100)
    warmth: int = Field(ge=0, le=100)
    contexts: list[ContextName] = Field(
        default_factory=list,
        description="Momentos en los que la cancion encaja de forma natural",
    )
    descriptors: list[str] = Field(
        default_factory=list,
        description="Hasta 6 adjetivos cortos en castellano, en minusculas",
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="Cuanto conoces esta cancion en concreto. Bajo si dudas.",
    )


class TrackVibeBatch(BaseModel):
    tracks: list[TrackVibe]


AxisName = Literal[
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "tempo_feel",
    "vocal_focus",
    "warmth",
]


class AxisTarget(BaseModel):
    """Lo que la peticion pide en un eje concreto."""

    value: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Valor deseado 0-100, o null si este eje da igual para la peticion",
    )
    weight: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="1.0 si la peticion lo pide explicitamente, 0.3-0.6 si solo esta implicito",
    )


class QueryTargets(BaseModel):
    """El perfil objetivo, con un campo por eje.

    Los siete ejes son campos con nombre a proposito. Cuando esto era un
    `dict[str, int]` abierto, el esquema no contenia ni un solo nombre de eje
    -solo `additionalProperties`- y el modelo devolvia `{}` de forma sistematica:
    razonaba los ejes en prosa dentro de `notes` porque era el unico sitio donde
    tenia un campo en el que escribirlos. Sin ejes desaparece el 65% de la nota.
    """

    energy: AxisTarget = Field(default_factory=AxisTarget, description="0 = casi parada, 100 = maxima intensidad")
    valence: AxisTarget = Field(default_factory=AxisTarget, description="0 = oscura o triste, 100 = luminosa y alegre")
    danceability: AxisTarget = Field(default_factory=AxisTarget, description="0 = no invita a moverse, 100 = irresistible")
    acousticness: AxisTarget = Field(default_factory=AxisTarget, description="0 = electronica, 100 = acustica y organica")
    tempo_feel: AxisTarget = Field(default_factory=AxisTarget, description="Velocidad percibida, no el BPM real")
    vocal_focus: AxisTarget = Field(default_factory=AxisTarget, description="0 = instrumental, 100 = la voz manda")
    warmth: AxisTarget = Field(default_factory=AxisTarget, description="0 = fria y metalica, 100 = calida y analogica")


class QueryDraft(BaseModel):
    """Lo que se le pide al modelo. Se convierte en VibeQuery para puntuar."""

    label: str = Field(description="Nombre corto y evocador para la playlist")
    targets: QueryTargets = Field(
        default_factory=QueryTargets,
        description="Rellena el value de los ejes que la peticion determine; deja null los que den igual",
    )
    contexts: list[ContextName] = Field(default_factory=list)
    descriptors: list[str] = Field(
        default_factory=list, description="Adjetivos que deberia evocar la seleccion"
    )
    avoid_descriptors: list[str] = Field(
        default_factory=list, description="Adjetivos que descartan una cancion"
    )
    notes: str = Field(default="", description="Una frase explicando la interpretacion")

    def to_query(self) -> "VibeQuery":
        targets: dict[str, int] = {}
        weights: dict[str, float] = {}
        for axis in AXES:
            target: AxisTarget = getattr(self.targets, axis)
            if target.value is not None:
                targets[axis] = target.value
                weights[axis] = target.weight
        return VibeQuery(
            label=self.label,
            targets=targets,
            weights=weights,
            contexts=self.contexts,
            descriptors=self.descriptors,
            avoid_descriptors=self.avoid_descriptors,
            notes=self.notes,
        )


class VibeQuery(BaseModel):
    """Traduccion de la frase del usuario al mismo espacio que las canciones.

    Es la forma que consume el scorer: diccionarios eje -> valor. El modelo no
    la produce directamente, ver QueryDraft.
    """

    label: str = Field(description="Nombre corto y evocador para la playlist")
    targets: dict[str, int] = Field(
        description="Valor deseado 0-100 para cada eje relevante. Omite los que den igual."
    )
    weights: dict[str, float] = Field(
        default_factory=dict,
        description="Importancia 0-1 de cada eje presente en targets. Por defecto 1.",
    )
    contexts: list[ContextName] = Field(default_factory=list)
    descriptors: list[str] = Field(
        default_factory=list, description="Adjetivos que deberia evocar la seleccion"
    )
    avoid_descriptors: list[str] = Field(
        default_factory=list, description="Adjetivos que descartan una cancion"
    )
    notes: str = Field(default="", description="Una frase explicando la interpretacion")
