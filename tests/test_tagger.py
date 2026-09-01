"""Politica de errores del etiquetado y traduccion de peticiones.

No se llama a ninguna API: el Tagger habla contra la interfaz `Modelo`, asi que
basta con uno falso.

El caso que motivo estos tests: con la cuenta sin saldo, los 45 lotes de una
biblioteca de 1.788 canciones fallaban uno a uno y el job terminaba sin
etiquetar nada y sin registrar ningun error, asi que la UI no tenia nada que
mostrar.
"""
import pytest

from app.llm import LLMError
from app.tagger import MAX_CONSECUTIVE_FAILURES, Tagger, TaggingAborted
from app.vibes import AxisTarget, QueryDraft, QueryTargets, TrackVibe, TrackVibeBatch

TRACKS = [
    {"id": f"t{i}", "name": f"Cancion {i}", "artists": ["Alguien"], "album": "Disco",
     "release_year": 2020}
    for i in range(5)
]

SIN_SALDO = LLMError("La cuenta no tiene saldo.", permanent=True)


def _transitorio() -> LLMError:
    return LLMError("El proveedor devolvio un error temporal (500).", permanent=False)


class FakeModel:
    """Devuelve o lanza lo que le digan, y guarda lo que se le envio."""

    nombre = "modelo-de-prueba"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.sent = []

    def parse(self, system, user, esquema, max_tokens):
        self.calls += 1
        self.sent.append({"system": system, "user": user, "esquema": esquema})
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _tagger(outcomes) -> Tagger:
    return Tagger(FakeModel(outcomes))


def _vibe(track_id: str) -> TrackVibe:
    return TrackVibe(
        track_id=track_id, energy=50, valence=50, danceability=50,
        acousticness=50, tempo_feel=50, vocal_focus=50, warmth=50, confidence=70,
    )


# -- errores permanentes ----------------------------------------------------
def test_un_error_permanente_aborta_en_el_primer_lote():
    tagger = _tagger([SIN_SALDO] * 5)
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert "no tiene saldo" in str(exc.value)
    # Lo importante: no recorre la biblioteca entera quemando llamadas.
    assert tagger.model.calls == 1


def test_el_mensaje_del_proveedor_llega_intacto_a_la_interfaz():
    tagger = _tagger([LLMError("Revisa AI_MODEL en .env.", permanent=True)])
    with pytest.raises(TaggingAborted, match="AI_MODEL"):
        list(tagger.tag_all(TRACKS, batch_size=1))


# -- errores transitorios ---------------------------------------------------
def test_un_fallo_suelto_no_tumba_el_resto():
    outcomes = [_transitorio()] + [
        TrackVibeBatch(tracks=[_vibe(f"t{i}")]) for i in range(1, 5)
    ]
    lotes = list(_tagger(outcomes).tag_all(TRACKS, batch_size=1))
    assert lotes[0] == []
    assert [v.track_id for lote in lotes[1:] for v in lote] == ["t1", "t2", "t3", "t4"]


def test_una_racha_de_fallos_aborta():
    tagger = _tagger([_transitorio() for _ in range(10)])
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert str(MAX_CONSECUTIVE_FAILURES) in str(exc.value)
    assert tagger.model.calls == MAX_CONSECUTIVE_FAILURES


def test_la_racha_se_reinicia_tras_un_lote_bueno():
    # Alterna fallo/exito: nunca hay racha, asi que debe recorrerlo entero.
    outcomes = [
        _transitorio(), TrackVibeBatch(tracks=[_vibe("t1")]),
        _transitorio(), TrackVibeBatch(tracks=[_vibe("t3")]),
        _transitorio(),
    ]
    lotes = list(_tagger(outcomes).tag_all(TRACKS, batch_size=1))
    assert [v.track_id for lote in lotes for v in lote] == ["t1", "t3"]


# -- tag_batch --------------------------------------------------------------
def test_descarta_ids_alucinados_y_repetidos():
    batch = TrackVibeBatch(tracks=[_vibe("t0"), _vibe("t0"), _vibe("inventado"), _vibe("t1")])
    vibes = _tagger([batch]).tag_batch(TRACKS[:2])
    assert [v.track_id for v in vibes] == ["t0", "t1"]


def test_un_lote_ilegible_se_omite_sin_romper():
    assert _tagger([None]).tag_batch(TRACKS[:2]) == []


# -- contexto de last.fm ----------------------------------------------------
def test_los_tags_de_lastfm_llegan_al_prompt():
    tagger = _tagger([TrackVibeBatch(tracks=[_vibe("t0")])])
    tagger.tag_batch([{**TRACKS[0], "lastfm_tags": ["deep house", "balearic"]}])
    assert "tags: deep house, balearic" in tagger.model.sent[0]["user"]


def test_una_cancion_sin_tags_no_ensucia_el_prompt():
    tagger = _tagger([TrackVibeBatch(tracks=[_vibe("t0")])])
    tagger.tag_batch([{**TRACKS[0], "lastfm_tags": []}])
    assert "tags:" not in tagger.model.sent[0]["user"]


def test_prepare_se_aplica_a_cada_lote():
    vistos = []

    def prepare(chunk):
        vistos.append([t["id"] for t in chunk])
        return [{**t, "lastfm_tags": ["marcado"]} for t in chunk]

    tagger = _tagger([TrackVibeBatch(tracks=[_vibe(f"t{i}")]) for i in range(3)])
    list(tagger.tag_all(TRACKS[:3], batch_size=1, prepare=prepare))
    assert vistos == [["t0"], ["t1"], ["t2"]]
    for enviado in tagger.model.sent:
        assert "tags: marcado" in enviado["user"]


# -- parse_query ------------------------------------------------------------
def _draft(notes="nota", **ejes) -> QueryDraft:
    targets = QueryTargets(**{
        eje: AxisTarget(value=valor, weight=1.0) for eje, valor in ejes.items()
    })
    return QueryDraft(label="X", targets=targets, notes=notes)


def test_una_interpretacion_sin_ejes_se_reintenta():
    # El caso real: "calma en la piscina" devolvia los siete ejes a null, el
    # bloque de ejes (65% de la nota) desaparecia y mandaban los contextos.
    tagger = _tagger([_draft(), _draft(energy=35, valence=75, warmth=80)])
    query = tagger.parse_query("calma en la piscina con cervecita")
    assert query.targets == {"energy": 35, "valence": 75, "warmth": 80}
    assert tagger.model.calls == 2


def test_el_reintento_dice_lo_que_falta():
    tagger = _tagger([_draft(), _draft(energy=35, valence=75, warmth=80)])
    tagger.parse_query("algo")
    assert "sin ejes numericos" in tagger.model.sent[1]["user"]


def test_una_interpretacion_con_ejes_no_gasta_una_segunda_llamada():
    tagger = _tagger([_draft(energy=80, tempo_feel=85, valence=70)])
    tagger.parse_query("fiesta")
    assert tagger.model.calls == 1


def test_los_ejes_a_null_no_llegan_al_scorer():
    # Un eje sin value significa "me da igual": no debe puntuar ni pesar.
    query = _tagger([_draft(energy=40, valence=60, warmth=70)]).parse_query("x")
    assert set(query.targets) == {"energy", "valence", "warmth"}
    assert set(query.weights) == set(query.targets)


def test_si_el_reintento_tampoco_trae_ejes_avisa_en_las_notas():
    pobre = QueryDraft(label="X", descriptors=["veraniega"], notes="nota")
    assert "poco concreta" in _tagger([pobre, pobre]).parse_query("algo bonito").notes


def test_una_peticion_sin_nada_aprovechable_se_rechaza():
    with pytest.raises(ValueError, match="demasiado vaga"):
        _tagger([_draft(), _draft()]).parse_query("mmm")


def test_una_respuesta_ilegible_se_rechaza():
    with pytest.raises(ValueError, match="No se pudo interpretar"):
        _tagger([None]).parse_query("lo que sea")
