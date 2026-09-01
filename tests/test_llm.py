"""Capa de proveedor: clasificacion de errores y dialecto OpenAI.

No se llama a ninguna API real. Lo que se comprueba aqui es que un fallo quede
bien clasificado en permanente o transitorio, porque de eso depende que el
etiquetado aborte en el primer lote o siga adelante.
"""
import json

import httpx2
import pytest
from pydantic import BaseModel

from app.llm import LLMError, OpenAIModel, build_model


class Respuesta(BaseModel):
    titulo: str
    energia: int


def _http(monkeypatch, status=200, cuerpo=None, texto=None, captura=None):
    def fake(url, **kwargs):
        if captura is not None:
            captura.update(url=url, **kwargs)
        request = httpx2.Request("POST", url)
        if texto is not None:
            return httpx2.Response(status, text=texto, request=request)
        return httpx2.Response(status, json=cuerpo, request=request)

    monkeypatch.setattr("app.llm.httpx.post", fake)


def _ok(contenido: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(contenido)}}]}


def _modelo() -> OpenAIModel:
    return OpenAIModel("un-modelo", "http://127.0.0.1:11434/v1", "clave")


# -- dialecto OpenAI --------------------------------------------------------
def test_devuelve_el_esquema_validado(monkeypatch):
    _http(monkeypatch, cuerpo=_ok({"titulo": "Piscina", "energia": 35}))
    salida = _modelo().parse("sistema", "usuario", Respuesta, 1000)
    assert salida.titulo == "Piscina" and salida.energia == 35


def test_pide_el_esquema_en_response_format(monkeypatch):
    visto = {}
    _http(monkeypatch, cuerpo=_ok({"titulo": "x", "energia": 1}), captura=visto)
    _modelo().parse("sistema", "usuario", Respuesta, 1000)
    formato = visto["json"]["response_format"]
    assert formato["type"] == "json_schema"
    assert formato["json_schema"]["name"] == "Respuesta"
    assert "energia" in formato["json_schema"]["schema"]["properties"]


def test_un_servidor_que_no_entiende_json_schema_no_rompe(monkeypatch):
    # Ollama y compania: se reintenta pidiendo JSON a secas, con el esquema
    # descrito en el prompt.
    llamadas = []

    def fake(url, **kwargs):
        llamadas.append(kwargs["json"])
        request = httpx2.Request("POST", url)
        if len(llamadas) == 1:
            return httpx2.Response(
                400, text='{"error":"response_format not supported"}', request=request)
        return httpx2.Response(200, json=_ok({"titulo": "ok", "energia": 2}), request=request)

    monkeypatch.setattr("app.llm.httpx.post", fake)
    modelo = _modelo()
    assert modelo.parse("sistema", "usuario", Respuesta, 1000).titulo == "ok"
    assert llamadas[1]["response_format"] == {"type": "json_object"}
    assert "esquema" in llamadas[1]["messages"][0]["content"]


def test_el_modo_compatible_se_recuerda(monkeypatch):
    # Descubrirlo una vez por lote seria un 400 gratis en cada uno.
    modelo = _modelo()
    modelo._json_schema = False
    visto = {}
    _http(monkeypatch, cuerpo=_ok({"titulo": "x", "energia": 1}), captura=visto)
    modelo.parse("sistema", "usuario", Respuesta, 1000)
    assert visto["json"]["response_format"] == {"type": "json_object"}


def test_un_json_que_no_encaja_con_el_esquema_se_descarta(monkeypatch):
    _http(monkeypatch, cuerpo=_ok({"titulo": "falta la energia"}))
    assert _modelo().parse("sistema", "usuario", Respuesta, 1000) is None


def test_una_respuesta_sin_choices_no_rompe(monkeypatch):
    _http(monkeypatch, cuerpo={"vaya": "algo raro"})
    with pytest.raises(LLMError) as exc:
        _modelo().parse("sistema", "usuario", Respuesta, 1000)
    assert exc.value.permanent is False


# -- clasificacion de errores -----------------------------------------------
@pytest.mark.parametrize("status,permanente", [
    (401, True), (403, True), (404, True), (402, True),
    (429, False), (500, False), (503, False),
])
def test_cada_codigo_se_clasifica(monkeypatch, status, permanente):
    _http(monkeypatch, status=status, texto="{}")
    with pytest.raises(LLMError) as exc:
        _modelo().parse("sistema", "usuario", Respuesta, 1000)
    assert exc.value.permanent is permanente


def test_la_falta_de_saldo_se_detecta_por_el_texto(monkeypatch):
    _http(monkeypatch, status=400, texto='{"error":"insufficient_quota"}')
    with pytest.raises(LLMError) as exc:
        _modelo().parse("sistema", "usuario", Respuesta, 1000)
    assert exc.value.permanent and "saldo" in exc.value.human


def test_un_servidor_local_apagado_es_transitorio_y_lo_dice(monkeypatch):
    def revienta(*a, **k):
        raise httpx2.ConnectError("conexion rechazada")

    monkeypatch.setattr("app.llm.httpx.post", revienta)
    with pytest.raises(LLMError) as exc:
        _modelo().parse("sistema", "usuario", Respuesta, 1000)
    assert exc.value.permanent is False
    assert "arrancado" in exc.value.human


# -- fabrica ----------------------------------------------------------------
def test_ollama_no_necesita_url(monkeypatch):
    modelo = build_model("ollama", "llama3.1")
    assert isinstance(modelo, OpenAIModel)
    assert modelo.base_url == "http://127.0.0.1:11434/v1"


def test_una_url_propia_basta_sin_preset():
    modelo = build_model("lo-que-sea", "m", base_url="https://mi-servidor/v1")
    assert isinstance(modelo, OpenAIModel) and modelo.base_url == "https://mi-servidor/v1"


def test_un_proveedor_desconocido_sin_url_se_rechaza():
    with pytest.raises(LLMError) as exc:
        build_model("inventado", "m")
    assert exc.value.permanent and "AI_BASE_URL" in exc.value.human
