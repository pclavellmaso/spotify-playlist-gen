"""Cliente de Last.fm y cache de tags. No se llama a la API real."""
import json

import httpx2
import pytest

from app import lastfm as lastfm_mod
from app.db import Library
from app.lastfm import MIN_COUNT, LastfmClient


def _payload(*tags) -> dict:
    return {"toptags": {"tag": [{"name": n, "count": c} for n, c in tags]}}


def _fake_get(monkeypatch, payload, status=200):
    def fake(url, **kwargs):
        request = httpx2.Request("GET", url)
        return httpx2.Response(status, json=payload, request=request)

    monkeypatch.setattr(lastfm_mod.httpx, "get", fake)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    # El cliente respeta 5 req/s; en los tests no hace falta esperar.
    monkeypatch.setattr(lastfm_mod, "MIN_INTERVAL", 0.0)


def test_sin_key_no_hace_ninguna_peticion(monkeypatch):
    def explota(*a, **k):
        raise AssertionError("no deberia llamar a Last.fm sin key")

    monkeypatch.setattr(lastfm_mod.httpx, "get", explota)
    client = LastfmClient("")
    assert client.enabled is False
    assert client.top_tags("Morcheeba", "World Looking In") == []


def test_devuelve_los_tags_ordenados(monkeypatch):
    _fake_get(monkeypatch, _payload(("trip-hop", 100), ("chillout", 80), ("downtempo", 45)))
    tags = LastfmClient("k").top_tags("Morcheeba", "World Looking In")
    assert tags == ["trip-hop", "chillout", "downtempo"]


def test_descarta_los_tags_de_una_sola_persona(monkeypatch):
    _fake_get(monkeypatch, _payload(("house", 90), ("ruido de mi primo", MIN_COUNT - 1)))
    assert LastfmClient("k").top_tags("A", "B") == ["house"]


def test_descarta_el_nombre_del_artista_y_del_tema(monkeypatch):
    # El tag mas usado de un tema suele ser el propio artista: no aporta nada.
    _fake_get(monkeypatch, _payload(("morcheeba", 100), ("trip-hop", 90),
                                    ("world looking in", 70)))
    assert LastfmClient("k").top_tags("Morcheeba", "World Looking In") == ["trip-hop"]


def test_descarta_los_tags_que_no_hablan_de_musica(monkeypatch):
    _fake_get(monkeypatch, _payload(("seen live", 100), ("favorites", 95), ("balearic", 60)))
    assert LastfmClient("k").top_tags("A", "B") == ["balearic"]


def test_un_solo_tag_llega_como_objeto_y_no_como_lista(monkeypatch):
    # Rareza real de la API: con un unico tag no devuelve una lista de uno.
    _fake_get(monkeypatch, {"toptags": {"tag": {"name": "jungle", "count": 100}}})
    assert LastfmClient("k").top_tags("A", "B") == ["jungle"]


def test_un_tema_desconocido_devuelve_lista_vacia(monkeypatch):
    _fake_get(monkeypatch, {"error": 6, "message": "Track not found"})
    assert LastfmClient("k").top_tags("Nadie", "Nada") == []


def test_un_fallo_de_red_no_rompe_el_etiquetado(monkeypatch):
    def revienta(*a, **k):
        raise httpx2.ConnectError("sin red")

    monkeypatch.setattr(lastfm_mod.httpx, "get", revienta)
    assert LastfmClient("k").top_tags("A", "B") == []


def test_una_respuesta_no_json_no_rompe_el_etiquetado(monkeypatch):
    def fake(url, **kwargs):
        request = httpx2.Request("GET", url)
        return httpx2.Response(200, text="<html>vaya</html>", request=request)

    monkeypatch.setattr(lastfm_mod.httpx, "get", fake)
    assert LastfmClient("k").top_tags("A", "B") == []


# -- cache ------------------------------------------------------------------
def test_el_cache_guarda_y_devuelve(tmp_path):
    library = Library(tmp_path / "t.db")
    library.upsert_tracks([
        {"id": "a", "name": "A", "artists": ["X"], "source": "liked"},
        {"id": "b", "name": "B", "artists": ["Y"], "source": "liked"},
    ])
    library.save_lastfm_tags({"a": ["house", "funky"], "b": []})
    assert library.lastfm_tags(["a", "b", "c"]) == {"a": ["house", "funky"], "b": []}


def test_el_cache_distingue_vacio_de_no_preguntado(tmp_path):
    # "Last.fm no lo conoce" es una respuesta: no hay que volver a preguntarla.
    library = Library(tmp_path / "t.db")
    library.upsert_tracks([{"id": "a", "name": "A", "artists": ["X"], "source": "liked"}])
    library.save_lastfm_tags({"a": []})
    cached = library.lastfm_tags(["a"])
    assert "a" in cached and cached["a"] == []


def test_el_cache_se_sobrescribe(tmp_path):
    library = Library(tmp_path / "t.db")
    library.upsert_tracks([{"id": "a", "name": "A", "artists": ["X"], "source": "liked"}])
    library.save_lastfm_tags({"a": ["viejo"]})
    library.save_lastfm_tags({"a": ["nuevo"]})
    assert library.lastfm_tags(["a"]) == {"a": ["nuevo"]}
