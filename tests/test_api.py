"""Recorrido completo de /api/generate con la biblioteca ya etiquetada.

Solo se sustituye la llamada a Claude: el resto (SQLite, scoring, seleccion,
serializacion HTTP) se ejerce de verdad.
"""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Library
from app.vibes import TAGGER_VERSION, TrackVibe, VibeQuery

TRACKS = [
    {"id": "chill", "name": "Slow Sun", "artists": ["Calma"], "album": "Verano",
     "release_year": 2019, "duration_ms": 200000, "popularity": 40,
     "source": "liked", "added_at": "2024-01-01T00:00:00Z"},
    {"id": "hard", "name": "Rage Machine", "artists": ["Ruido"], "album": "Metal",
     "release_year": 2005, "duration_ms": 180000, "popularity": 60,
     "source": "liked", "added_at": "2024-01-02T00:00:00Z"},
]

VIBES = [
    TrackVibe(track_id="chill", energy=30, valence=78, danceability=45,
              acousticness=70, tempo_feel=32, vocal_focus=40, warmth=85,
              contexts=["piscina_verano"], descriptors=["veraniega", "relajada"],
              confidence=90),
    TrackVibe(track_id="hard", energy=97, valence=20, danceability=60,
              acousticness=5, tempo_feel=95, vocal_focus=80, warmth=10,
              contexts=["entrenamiento"], descriptors=["agresiva"], confidence=90),
]


class FakeTagger:
    def parse_query(self, prompt):
        assert "piscina" in prompt
        return VibeQuery(
            label="Piscina y cerveza",
            targets={"energy": 33, "valence": 76, "warmth": 82},
            weights={"energy": 1.0, "valence": 1.0, "warmth": 0.7},
            contexts=["piscina_verano"],
            descriptors=["veraniega", "relajada"],
            avoid_descriptors=["agresiva"],
            notes="Ambiente calmado y luminoso de verano.",
        )


@pytest.fixture
def client(tmp_path, monkeypatch):
    library = Library(tmp_path / "api.db")
    library.upsert_tracks(TRACKS)
    library.save_vibes(VIBES, TAGGER_VERSION)
    monkeypatch.setattr(main, "library", library)
    monkeypatch.setattr(main, "_tagger", lambda: FakeTagger())
    return TestClient(main.app)


def test_generate_keeps_the_matching_track_and_drops_the_other(client):
    res = client.post("/api/generate", json={"prompt": "calma en la piscina con cervecita"})
    assert res.status_code == 200
    body = res.json()
    assert body["pool"] == 2
    assert [t["id"] for t in body["tracks"]] == ["chill"]
    assert body["tracks"][0]["score"] > 80
    assert body["query"]["label"] == "Piscina y cerveza"


def test_generate_rejects_an_empty_prompt(client):
    assert client.post("/api/generate", json={"prompt": "x"}).status_code == 422


def test_stats_reports_the_tagged_library(client):
    body = client.get("/api/stats?source=liked").json()
    assert body["total"] == 2 and body["tagged"] == 2 and body["pending"] == 0


def test_sync_rejects_an_unknown_source(client):
    res = client.post("/api/sync", json={"source": "album:123"})
    assert res.status_code == 400


# -- ampliar la seleccion ---------------------------------------------------
class TaggerQueNoDebeUsarse:
    def parse_query(self, prompt):
        raise AssertionError("/api/more no debe volver a interpretar la frase")


QUERY = {
    "label": "Piscina y cerveza",
    "targets": {"energy": 33, "valence": 76, "warmth": 82},
    "weights": {"energy": 1.0, "valence": 1.0, "warmth": 0.7},
    "contexts": ["piscina_verano"],
    "descriptors": ["veraniega", "relajada"],
    "avoid_descriptors": [],
    "notes": "",
}


def test_more_amplia_sin_volver_a_llamar_al_modelo(client, monkeypatch):
    monkeypatch.setattr(main, "_tagger", lambda: TaggerQueNoDebeUsarse())
    estricto = client.post("/api/more", json={"query": QUERY, "min_score": 90}).json()
    amplio = client.post("/api/more", json={"query": QUERY, "min_score": 0}).json()
    assert len(amplio["tracks"]) > len(estricto["tracks"])


def test_more_devuelve_la_seleccion_entera_no_solo_lo_nuevo(client):
    # El tope por artista y el orden por energia son globales: la lista se
    # rehace completa para que el resultado sea el mismo que pidiendola de una.
    body = client.post("/api/more", json={"query": QUERY, "min_score": 0}).json()
    assert [t["id"] for t in body["tracks"]] == ["chill", "hard"]
    assert body["min_score"] == 0


def test_more_rechaza_una_query_invalida(client):
    assert client.post("/api/more", json={"query": {"label": "x", "targets": "no"}}).status_code == 422


# -- errores de spotify -----------------------------------------------------
def test_un_error_de_spotify_no_sale_como_500(client, monkeypatch):
    # Lanzar HTTPException desde un exception_handler no produce el 4xx: se
    # propaga y el front solo veia "Error 500".
    from app.spotify import SpotifyError

    def denegado(*a, **k):
        raise SpotifyError(403, '{"error": {"status": 403, "message": "Forbidden"}}')

    monkeypatch.setattr(main.spotify, "create_playlist", denegado)
    res = client.post("/api/save", json={"name": "x", "track_ids": ["chill"]})
    assert res.status_code == 502
    assert "Premium" in res.json()["detail"]


def test_una_sesion_caducada_devuelve_401(client, monkeypatch):
    from app.spotify import SpotifyAuthError

    def caducado(*a, **k):
        raise SpotifyAuthError("La sesion de Spotify caduco, vuelve a conectar")

    monkeypatch.setattr(main.spotify, "create_playlist", caducado)
    res = client.post("/api/save", json={"name": "x", "track_ids": ["chill"]})
    assert res.status_code == 401
    assert "caduco" in res.json()["detail"]


# -- ampliar una playlist existente -----------------------------------------
def _dentro(*ids):
    return [{"id": i, "name": i, "artists": ["X"], "source": "liked"} for i in ids]


def test_extend_toma_como_objetivo_lo_que_ya_hay_dentro(client, monkeypatch):
    # El nombre de una lista es una pista pobre: el objetivo sale del perfil
    # medio de sus canciones.
    monkeypatch.setattr(main.spotify, "playlist_tracks", lambda pid: _dentro("chill"))
    monkeypatch.setattr(main.spotify, "playlist_name", lambda pid: "Piknik")
    body = client.post("/api/extend", json={"playlist_id": "p1", "min_score": 0}).json()

    assert body["playlist"]["name"] == "Piknik"
    assert body["reference"] == 1
    # El objetivo se parece a «chill», no a la media de la biblioteca.
    assert body["query"]["targets"]["energy"] == 30
    assert body["query"]["targets"]["warmth"] == 85


def test_extend_no_propone_lo_que_la_lista_ya_tiene(client, monkeypatch):
    monkeypatch.setattr(main.spotify, "playlist_tracks", lambda pid: _dentro("chill"))
    monkeypatch.setattr(main.spotify, "playlist_name", lambda pid: "Piknik")
    body = client.post("/api/extend", json={"playlist_id": "p1", "min_score": 0}).json()
    assert "chill" not in [t["id"] for t in body["tracks"]]
    assert "chill" in body["exclude"]


def test_extend_avisa_si_la_lista_no_esta_analizada(client, monkeypatch):
    monkeypatch.setattr(main.spotify, "playlist_tracks", lambda pid: _dentro("desconocida"))
    monkeypatch.setattr(main.spotify, "playlist_name", lambda pid: "Rarezas")
    res = client.post("/api/extend", json={"playlist_id": "p1"})
    assert res.status_code == 400
    assert "Rarezas" in res.json()["detail"]


def test_extend_rechaza_una_lista_vacia(client, monkeypatch):
    monkeypatch.setattr(main.spotify, "playlist_tracks", lambda pid: [])
    assert client.post("/api/extend", json={"playlist_id": "p1"}).status_code == 400


def test_append_escribe_en_la_lista_indicada(client, monkeypatch):
    visto = {}
    monkeypatch.setattr(main.spotify, "add_to_playlist",
                        lambda pid, ids: visto.update(pid=pid, ids=ids) or len(ids))
    body = client.post("/api/append",
                       json={"playlist_id": "p9", "track_ids": ["chill", "hard"]}).json()
    assert visto == {"pid": "p9", "ids": ["chill", "hard"]}
    assert body["added"] == 2 and "p9" in body["url"]


# -- duración y curva a través de la API ------------------------------------
def test_se_puede_pedir_por_minutos(client):
    body = client.post("/api/generate",
                       json={"prompt": "calma en la piscina", "target_minutes": 5,
                             "min_score": 0}).json()
    assert body["minutes"] >= 3


def test_la_curva_descendente_se_acepta(client):
    res = client.post("/api/generate",
                      json={"prompt": "calma en la piscina", "order": "fall", "min_score": 0})
    assert res.status_code == 200 and res.json()["order"] == "fall"


def test_una_curva_inventada_se_rechaza(client):
    res = client.post("/api/generate",
                      json={"prompt": "calma en la piscina", "order": "espiral"})
    assert res.status_code == 422
