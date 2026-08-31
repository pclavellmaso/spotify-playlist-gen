"""Politica de errores del etiquetado. No se llama a la API real.

El caso que motivo estos tests: con la cuenta sin saldo, los 45 lotes de una
biblioteca de 1.788 canciones fallaban uno a uno y el job terminaba sin
etiquetar nada y sin registrar ningun error, asi que la UI no tenia nada que
mostrar.
"""
import anthropic
import httpx2
import pytest

from app.tagger import MAX_CONSECUTIVE_FAILURES, Tagger, TaggingAborted, explain_error
from app.vibes import AxisTarget, QueryDraft, QueryTargets, TrackVibe, TrackVibeBatch

TRACKS = [
    {"id": f"t{i}", "name": f"Cancion {i}", "artists": ["Alguien"], "album": "Disco",
     "release_year": 2020}
    for i in range(5)
]

NO_CREDIT = (
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)


def _response(status: int) -> httpx2.Response:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(status, request=request)


def _bad_request(message: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(message, response=_response(400), body=None)


def _server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError("boom", response=_response(500), body=None)


class FakeMessages:
    """Devuelve o lanza lo que le digan, y cuenta las llamadas."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.sent: list[dict] = []

    def parse(self, **kwargs):
        self.calls += 1
        self.sent.append(kwargs)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.messages = FakeMessages(outcomes)


class FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed


def _tagger(outcomes) -> Tagger:
    return Tagger("claude-opus-5", client=FakeClient(outcomes))


def _vibe(track_id: str) -> TrackVibe:
    return TrackVibe(
        track_id=track_id, energy=50, valence=50, danceability=50,
        acousticness=50, tempo_feel=50, vocal_focus=50, warmth=50,
        confidence=70,
    )


# -- errores permanentes ----------------------------------------------------
def test_sin_saldo_aborta_en_el_primer_lote():
    tagger = _tagger([_bad_request(NO_CREDIT)] * 5)
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert "no tiene saldo" in str(exc.value)
    # Lo importante: no recorre la biblioteca entera quemando llamadas.
    assert tagger.client.messages.calls == 1


def test_api_key_invalida_aborta():
    error = anthropic.AuthenticationError(
        "invalid x-api-key", response=_response(401), body=None
    )
    tagger = _tagger([error])
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_modelo_inexistente_menciona_el_modelo():
    error = anthropic.NotFoundError("not found", response=_response(404), body=None)
    tagger = _tagger([error])
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert "claude-opus-5" in str(exc.value)


# -- errores transitorios ---------------------------------------------------
def test_un_fallo_suelto_no_tumba_el_resto():
    outcomes = [
        _server_error(),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t1")])),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t2")])),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t3")])),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t4")])),
    ]
    lotes = list(_tagger(outcomes).tag_all(TRACKS, batch_size=1))
    assert lotes[0] == []
    assert [v.track_id for lote in lotes[1:] for v in lote] == ["t1", "t2", "t3", "t4"]


def test_una_racha_de_fallos_aborta():
    tagger = _tagger([_server_error()] * 10)
    with pytest.raises(TaggingAborted) as exc:
        list(tagger.tag_all(TRACKS, batch_size=1))
    assert str(MAX_CONSECUTIVE_FAILURES) in str(exc.value)
    assert tagger.client.messages.calls == MAX_CONSECUTIVE_FAILURES


def test_la_racha_se_reinicia_tras_un_lote_bueno():
    # Alterna fallo/exito: nunca hay racha, asi que debe recorrerlo entero.
    outcomes = [
        _server_error(),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t1")])),
        _server_error(),
        FakeResponse(TrackVibeBatch(tracks=[_vibe("t3")])),
        _server_error(),
    ]
    lotes = list(_tagger(outcomes).tag_all(TRACKS, batch_size=1))
    assert [v.track_id for lote in lotes for v in lote] == ["t1", "t3"]


# -- tag_batch --------------------------------------------------------------
def test_descarta_ids_alucinados_y_repetidos():
    batch = TrackVibeBatch(tracks=[_vibe("t0"), _vibe("t0"), _vibe("inventado"), _vibe("t1")])
    tagger = _tagger([FakeResponse(batch)])
    vibes = tagger.tag_batch(TRACKS[:2])
    assert [v.track_id for v in vibes] == ["t0", "t1"]


def test_un_lote_ilegible_se_omite_sin_romper():
    tagger = _tagger([FakeResponse(None)])
    assert tagger.tag_batch(TRACKS[:2]) == []


# -- mensajes ---------------------------------------------------------------
def test_explain_error_prioriza_el_saldo_sobre_el_tipo():
    # Sin saldo llega como un 400 generico: el texto es la unica pista util.
    assert "saldo" in explain_error(_bad_request(NO_CREDIT), "claude-opus-5")


def test_explain_error_tiene_salida_para_lo_desconocido():
    assert "raro" in explain_error(_bad_request("algo raro"), "claude-opus-5")


# -- parse_query ------------------------------------------------------------
def _draft(notes="nota", **axes) -> QueryDraft:
    """Un borrador con `value` puesto solo en los ejes que se le pasen."""
    targets = QueryTargets(**{
        axis: AxisTarget(value=value, weight=1.0) for axis, value in axes.items()
    })
    return QueryDraft(label="X", targets=targets, notes=notes)


def test_una_interpretacion_sin_ejes_se_reintenta():
    # El caso real: "calma en la piscina" devolvia los siete ejes a null, el
    # bloque de ejes (65% de la nota) desaparecia y mandaban los contextos.
    bueno = _draft(energy=35, valence=75, warmth=80)
    tagger = _tagger([FakeResponse(_draft()), FakeResponse(bueno)])
    query = tagger.parse_query("calma en la piscina con cervecita")
    assert query.targets == {"energy": 35, "valence": 75, "warmth": 80}
    assert tagger.client.messages.calls == 2


def test_una_interpretacion_con_ejes_no_gasta_una_segunda_llamada():
    tagger = _tagger([FakeResponse(_draft(energy=80, tempo_feel=85, valence=70))])
    tagger.parse_query("fiesta")
    assert tagger.client.messages.calls == 1


def test_los_ejes_a_null_no_llegan_al_scorer():
    # Un eje sin value significa "me da igual": no debe puntuar ni pesar.
    query = _tagger([FakeResponse(_draft(energy=40, valence=60, warmth=70))]).parse_query("x")
    assert set(query.targets) == {"energy", "valence", "warmth"}
    assert set(query.weights) == set(query.targets)


def test_si_el_reintento_tampoco_trae_ejes_avisa_en_las_notas():
    pobre = QueryDraft(label="X", descriptors=["veraniega"], notes="nota")
    tagger = _tagger([FakeResponse(pobre), FakeResponse(pobre)])
    assert "poco concreta" in tagger.parse_query("algo bonito").notes


def test_una_peticion_sin_nada_aprovechable_se_rechaza():
    tagger = _tagger([FakeResponse(_draft()), FakeResponse(_draft())])
    with pytest.raises(ValueError, match="demasiado vaga"):
        tagger.parse_query("mmm")


def test_una_respuesta_ilegible_se_rechaza():
    with pytest.raises(ValueError, match="No se pudo interpretar"):
        _tagger([FakeResponse(None)]).parse_query("lo que sea")


# -- contexto de last.fm ----------------------------------------------------
def test_los_tags_de_lastfm_llegan_al_prompt():
    tagger = _tagger([FakeResponse(TrackVibeBatch(tracks=[_vibe("t0")]))])
    tagger.tag_batch([{**TRACKS[0], "lastfm_tags": ["deep house", "balearic"]}])
    enviado = tagger.client.messages.sent[0]["messages"][0]["content"]
    assert "tags: deep house, balearic" in enviado


def test_una_cancion_sin_tags_no_ensucia_el_prompt():
    tagger = _tagger([FakeResponse(TrackVibeBatch(tracks=[_vibe("t0")]))])
    tagger.tag_batch([{**TRACKS[0], "lastfm_tags": []}])
    assert "tags:" not in tagger.client.messages.sent[0]["messages"][0]["content"]


def test_prepare_se_aplica_a_cada_lote():
    vistos = []

    def prepare(chunk):
        vistos.append([t["id"] for t in chunk])
        return [{**t, "lastfm_tags": ["marcado"]} for t in chunk]

    outcomes = [FakeResponse(TrackVibeBatch(tracks=[_vibe(f"t{i}")])) for i in range(3)]
    tagger = _tagger(outcomes)
    list(tagger.tag_all(TRACKS[:3], batch_size=1, prepare=prepare))

    assert vistos == [["t0"], ["t1"], ["t2"]]
    for enviado in tagger.client.messages.sent:
        assert "tags: marcado" in enviado["messages"][0]["content"]
