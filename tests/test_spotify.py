"""Normalizacion de los items que devuelve Spotify. No se llama a la API."""
from app.spotify import _normalize


def _item(**track):
    base = {"id": "abc", "name": "Cancion", "type": "track",
            "artists": [{"name": "Alguien"}],
            "album": {"name": "Disco", "release_date": "2020-05-01"}}
    return {"track": {**base, **track}, "added_at": "2024-01-01T00:00:00Z"}


def test_un_track_normal_pasa():
    t = _normalize(_item(), "liked")
    assert t["id"] == "abc" and t["artists"] == ["Alguien"] and t["release_year"] == 2020


def test_se_descartan_los_podcasts():
    assert _normalize(_item(type="episode"), "liked") is None


def test_se_descartan_los_locales():
    assert _normalize(_item(is_local=True), "liked") is None


def test_se_descartan_los_que_no_tienen_id():
    assert _normalize(_item(id=None), "liked") is None


def test_se_descarta_un_tema_retirado_del_catalogo():
    # Conserva id y type pero vuelve con todo en blanco: no hay nada que
    # perfilar y en una playlist saldria como pista no disponible.
    retirado = _item(name="", artists=[{"name": ""}],
                     album={"name": "", "release_date": ""},
                     duration_ms=0)
    assert _normalize(retirado, "liked") is None


def test_se_descarta_un_track_sin_nombre():
    assert _normalize(_item(name="   "), "liked") is None


def test_se_descarta_un_track_sin_artistas():
    assert _normalize(_item(artists=[]), "liked") is None


def test_un_anyo_invalido_queda_en_none():
    t = _normalize(_item(album={"name": "Disco", "release_date": ""}), "liked")
    assert t["release_year"] is None


def test_un_album_vacio_queda_en_none():
    t = _normalize(_item(album={"name": "", "release_date": "1999"}), "liked")
    assert t["album"] is None and t["release_year"] == 1999


# -- creacion de playlists --------------------------------------------------
class FakeClient:
    """Registra las llamadas para poder comprobar la ruta que se usa."""

    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/me/playlists":
            return {"id": "pl1", "name": kwargs["json"]["name"],
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"}}
        return None


def _client(monkeypatch):
    from pathlib import Path

    from app.spotify import SpotifyClient, TokenStore

    client = SpotifyClient("id", "uri", TokenStore(Path("/tmp/no-existe.json")))
    fake = FakeClient()
    monkeypatch.setattr(client, "_request", fake.request)
    return client, fake


def test_la_playlist_se_crea_contra_me_playlists(monkeypatch):
    # `/users/{id}/playlists` es la forma antigua y devuelve 403 aunque los
    # scopes esten concedidos.
    client, fake = _client(monkeypatch)
    client.create_playlist("Piscina", "notas", ["a", "b"], public=False)
    assert fake.calls[0][:2] == ("POST", "/me/playlists")
    assert not any("/users/" in path for _, path, _ in fake.calls)


def test_no_se_gasta_una_llamada_a_me(monkeypatch):
    client, fake = _client(monkeypatch)
    client.create_playlist("x", "", ["a"])
    assert not any(path == "/me" for _, path, _ in fake.calls)


def test_las_canciones_van_en_tandas_de_100(monkeypatch):
    client, fake = _client(monkeypatch)
    res = client.create_playlist("x", "", [f"t{i}" for i in range(250)])
    tandas = [c for c in fake.calls if c[1] == "/playlists/pl1/items"]
    assert [len(c[2]["json"]["uris"]) for c in tandas] == [100, 100, 50]
    assert res["added"] == 250


def test_el_nombre_y_la_descripcion_se_recortan(monkeypatch):
    client, fake = _client(monkeypatch)
    client.create_playlist("N" * 200, "D" * 400, ["a"])
    enviado = fake.calls[0][2]["json"]
    assert len(enviado["name"]) == 100 and len(enviado["description"]) == 300


def test_las_canciones_van_a_items_y_no_a_tracks(monkeypatch):
    # `/playlists/{id}/tracks` quedo obsoleto en febrero de 2026 y responde 403.
    client, fake = _client(monkeypatch)
    client.create_playlist("x", "", ["a"])
    rutas = [path for _, path, _ in fake.calls]
    assert "/playlists/pl1/items" in rutas
    assert not any(r.endswith("/tracks") for r in rutas)


def test_las_uris_llevan_el_prefijo_de_spotify(monkeypatch):
    client, fake = _client(monkeypatch)
    client.create_playlist("x", "", ["abc123"])
    envio = [c for c in fake.calls if c[1] == "/playlists/pl1/items"][0]
    assert envio[2]["json"]["uris"] == ["spotify:track:abc123"]
