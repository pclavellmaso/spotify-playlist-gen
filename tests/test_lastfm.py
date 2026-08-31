"""Cliente de Last.fm y cache de tags. No se llama a la API real."""
import httpx2
import pytest

from app import lastfm as lastfm_mod
from app.db import Library
from app.lastfm import MIN_COUNT, LastfmClient, album_key, artist_key, merge


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
    assert client.artist_tags("Morcheeba") == []
    assert client.album_tags("Morcheeba", "Big Calm") == []


def test_devuelve_los_tags_ordenados(monkeypatch):
    _fake_get(monkeypatch, _payload(("trip-hop", 100), ("chillout", 64), ("downtempo", 30)))
    assert LastfmClient("k").artist_tags("Morcheeba") == ["trip-hop", "chillout", "downtempo"]


def test_se_consulta_el_metodo_correcto(monkeypatch):
    visto = {}

    def fake(url, **kwargs):
        visto.update(kwargs["params"])
        request = httpx2.Request("GET", url)
        return httpx2.Response(200, json=_payload(("house", 100)), request=request)

    monkeypatch.setattr(lastfm_mod.httpx, "get", fake)
    LastfmClient("k").album_tags("Folamour", "Ordinary Drugs")
    assert visto["method"] == "album.gettoptags"
    assert visto["artist"] == "Folamour" and visto["album"] == "Ordinary Drugs"


def test_descarta_los_tags_de_una_sola_persona(monkeypatch):
    _fake_get(monkeypatch, _payload(("house", 90), ("ruido de mi primo", MIN_COUNT - 1)))
    assert LastfmClient("k").artist_tags("X") == ["house"]


def test_descarta_el_nombre_de_la_propia_entidad(monkeypatch):
    # El tag mas usado de un artista suele ser su propio nombre: no aporta nada.
    _fake_get(monkeypatch, _payload(("morcheeba", 100), ("trip-hop", 90)))
    assert LastfmClient("k").artist_tags("Morcheeba") == ["trip-hop"]


def test_descarta_los_tags_que_no_hablan_de_musica(monkeypatch):
    _fake_get(monkeypatch, _payload(("seen live", 100), ("favorites", 95), ("balearic", 60)))
    assert LastfmClient("k").artist_tags("X") == ["balearic"]


def test_un_solo_tag_llega_como_objeto_y_no_como_lista(monkeypatch):
    # Rareza real de la API: con un unico tag no devuelve una lista de uno.
    _fake_get(monkeypatch, {"toptags": {"tag": {"name": "jungle", "count": 100}}})
    assert LastfmClient("k").artist_tags("X") == ["jungle"]


def test_una_entidad_desconocida_devuelve_lista_vacia(monkeypatch):
    _fake_get(monkeypatch, {"error": 6, "message": "Artist not found"})
    assert LastfmClient("k").artist_tags("Nadie") == []


def test_un_fallo_de_red_no_rompe_el_etiquetado(monkeypatch):
    def revienta(*a, **k):
        raise httpx2.ConnectError("sin red")

    monkeypatch.setattr(lastfm_mod.httpx, "get", revienta)
    assert LastfmClient("k").artist_tags("X") == []


def test_una_respuesta_no_json_no_rompe_el_etiquetado(monkeypatch):
    def fake(url, **kwargs):
        request = httpx2.Request("GET", url)
        return httpx2.Response(200, text="<html>vaya</html>", request=request)

    monkeypatch.setattr(lastfm_mod.httpx, "get", fake)
    assert LastfmClient("k").artist_tags("X") == []


# -- merge ------------------------------------------------------------------
def test_el_album_manda_sobre_el_artista():
    # El album es mas especifico: trae la epoca y el caracter de ese disco.
    assert merge(["2019", "pop rap"], ["pop", "hip hop"]) == ["2019", "pop rap", "pop", "hip hop"]


def test_no_se_repiten_los_tags_que_coinciden():
    assert merge(["house", "2020"], ["house", "french house"]) == ["house", "2020", "french house"]


def test_sin_album_se_usa_solo_el_artista():
    assert merge([], ["drum and bass", "neurofunk"]) == ["drum and bass", "neurofunk"]


# -- claves de cache --------------------------------------------------------
def test_las_claves_no_distinguen_mayusculas():
    assert artist_key("Morcheeba") == artist_key(" morcheeba ")
    assert album_key("Lizzo", "Cuz I Love You") == album_key("lizzo", "cuz i love you")


def test_artista_y_album_no_colisionan():
    assert artist_key("X") != album_key("X", "X")


# -- cache ------------------------------------------------------------------
def test_el_cache_guarda_y_devuelve(tmp_path):
    library = Library(tmp_path / "t.db")
    library.save_lastfm_tags({artist_key("Folamour"): ["house", "french house"],
                              artist_key("Vesyr"): []})
    cached = library.lastfm_tags([artist_key("Folamour"), artist_key("Vesyr"), artist_key("Otro")])
    assert cached == {artist_key("Folamour"): ["house", "french house"], artist_key("Vesyr"): []}


def test_el_cache_distingue_vacio_de_no_preguntado(tmp_path):
    # "Last.fm no lo conoce" es una respuesta: no hay que volver a preguntarla.
    library = Library(tmp_path / "t.db")
    library.save_lastfm_tags({artist_key("Vesyr"): []})
    assert library.lastfm_tags([artist_key("Vesyr")]) == {artist_key("Vesyr"): []}


def test_el_cache_se_sobrescribe(tmp_path):
    library = Library(tmp_path / "t.db")
    library.save_lastfm_tags({artist_key("X"): ["viejo"]})
    library.save_lastfm_tags({artist_key("X"): ["nuevo"]})
    assert library.lastfm_tags([artist_key("X")]) == {artist_key("X"): ["nuevo"]}
