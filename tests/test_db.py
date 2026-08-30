import json

from app.db import Library
from app.vibes import TrackVibe


def make_library(tmp_path):
    return Library(tmp_path / "test.db")


TRACK = {
    "id": "t1", "name": "Song", "artists": ["A"], "album": "Album",
    "release_year": 2020, "duration_ms": 1000, "popularity": 50,
    "source": "liked", "added_at": "2024-01-01T00:00:00Z",
}


def vibe(track_id="t1", confidence=80):
    return TrackVibe(
        track_id=track_id, energy=40, valence=70, danceability=50,
        acousticness=60, tempo_feel=40, vocal_focus=50, warmth=80,
        contexts=["piscina_verano"], descriptors=["veraniega"], confidence=confidence,
    )


def test_upsert_is_idempotent(tmp_path):
    lib = make_library(tmp_path)
    lib.upsert_tracks([TRACK])
    lib.upsert_tracks([{**TRACK, "name": "Renamed"}])
    tracks = lib.tracks_for_source("liked")
    assert len(tracks) == 1
    assert tracks[0]["name"] == "Renamed"
    assert tracks[0]["artists"] == ["A"]


def test_untagged_shrinks_after_tagging(tmp_path):
    lib = make_library(tmp_path)
    lib.upsert_tracks([TRACK])
    assert len(lib.untagged("liked", 1)) == 1
    lib.save_vibes([vibe()], tagger_version=1)
    assert lib.untagged("liked", 1) == []
    # Una version nueva del etiquetador invalida el cache.
    assert len(lib.untagged("liked", 2)) == 1


def test_tagged_tracks_returns_axes_and_descriptors(tmp_path):
    lib = make_library(tmp_path)
    lib.upsert_tracks([TRACK])
    lib.save_vibes([vibe()], tagger_version=1)
    (row,) = lib.tagged_tracks("liked", 1)
    assert row["axes"]["warmth"] == 80
    assert row["contexts"] == ["piscina_verano"]
    assert row["descriptors"] == ["veraniega"]
    assert row["confidence"] == 80


def test_descriptors_are_normalised_to_lowercase(tmp_path):
    lib = make_library(tmp_path)
    lib.upsert_tracks([TRACK])
    v = vibe()
    v.descriptors = ["  Veraniega ", "RELAJADA"]
    lib.save_vibes([v], tagger_version=1)
    (row,) = lib.tagged_tracks("liked", 1)
    assert row["descriptors"] == ["veraniega", "relajada"]


def test_stats_counts_pending(tmp_path):
    lib = make_library(tmp_path)
    lib.upsert_tracks([TRACK, {**TRACK, "id": "t2"}])
    lib.save_vibes([vibe("t1")], tagger_version=1)
    assert lib.stats("liked", 1) == {"total": 2, "tagged": 1, "pending": 1}
