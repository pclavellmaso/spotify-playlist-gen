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
