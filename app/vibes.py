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

TAGGER_VERSION = 1

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


class VibeQuery(BaseModel):
    """Traduccion de la frase del usuario al mismo espacio que las canciones."""

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
