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
