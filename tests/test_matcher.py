from app.matcher import score_track, select
from app.vibes import VibeQuery


def track(tid="a", artist="X", energy=50, valence=50, warmth=50, tempo=50,
          contexts=None, descriptors=None, confidence=100):
    return {
        "id": tid,
        "name": f"song {tid}",
        "artists": [artist],
        "album": None,
        "release_year": 2020,
        "axes": {
            "energy": energy, "valence": valence, "danceability": 50,
            "acousticness": 50, "tempo_feel": tempo, "vocal_focus": 50, "warmth": warmth,
        },
        "contexts": contexts or [],
        "descriptors": descriptors or [],
        "confidence": confidence,
    }


POOL_QUERY = VibeQuery(
    label="Piscina",
    targets={"energy": 35, "valence": 75, "warmth": 80},
    weights={"energy": 1.0, "valence": 1.0, "warmth": 0.6},
    contexts=["piscina_verano"],
    descriptors=["veraniega", "relajada"],
    avoid_descriptors=["agresiva"],
)


def test_perfect_match_scores_higher_than_opposite():
    good = track("g", energy=35, valence=75, warmth=80,
                 contexts=["piscina_verano"], descriptors=["veraniega", "relajada"])
    bad = track("b", energy=95, valence=15, warmth=10,
                contexts=["entrenamiento"], descriptors=["densa"])
    assert score_track(good, POOL_QUERY) > 90
    assert score_track(bad, POOL_QUERY) < 40


def test_avoid_descriptor_vetoes_the_track():
    vetoed = track("v", energy=35, valence=75, warmth=80,
                   contexts=["piscina_verano"], descriptors=["veraniega", "agresiva"])
    assert score_track(vetoed, POOL_QUERY) == 0.0


def test_low_confidence_pulls_score_toward_neutral():
    sure = track("s", energy=35, valence=75, warmth=80, confidence=100)
    unsure = track("u", energy=35, valence=75, warmth=80, confidence=0)
    assert score_track(sure, POOL_QUERY) > score_track(unsure, POOL_QUERY) > 50


def test_query_without_targets_still_scores_on_context():
    query = VibeQuery(label="x", targets={}, contexts=["piscina_verano"])
    hit = track("h", contexts=["piscina_verano"])
    miss = track("m", contexts=["entrenamiento"])
    assert score_track(hit, query) > score_track(miss, query)


def test_axes_ignore_zero_weight_axis():
    query = VibeQuery(label="x", targets={"energy": 10, "valence": 90},
                      weights={"energy": 1.0, "valence": 0.0})
    # valence esta lejisimos del target pero pesa 0, asi que no debe restar.
    assert score_track(track(energy=10, valence=10), query) > 90


def test_select_caps_tracks_per_artist():
    pool = [track(f"t{i}", artist="Same", energy=35, valence=75, warmth=80,
                  contexts=["piscina_verano"], descriptors=["veraniega"])
            for i in range(6)]
    pool += [track(f"o{i}", artist=f"Other{i}", energy=35, valence=75, warmth=80,
                   contexts=["piscina_verano"], descriptors=["veraniega"])
             for i in range(4)]
    picked = select(pool, POOL_QUERY, limit=6, max_per_artist=2)
    from collections import Counter
    counts = Counter(t["artists"][0] for t in picked)
    assert counts["Same"] == 2
    assert len(picked) == 6


def test_select_backfills_when_diversity_starves_the_list():
    pool = [track(f"t{i}", artist="Same", energy=35, valence=75, warmth=80,
                  contexts=["piscina_verano"], descriptors=["veraniega"])
            for i in range(5)]
    # Solo hay un artista: el tope no debe impedir llenar el limite.
    picked = select(pool, POOL_QUERY, limit=4, max_per_artist=2)
    assert len(picked) == 4


def test_flow_order_ramps_energy_up():
    pool = [track("hi", artist="A", energy=60, valence=75, warmth=80,
                  contexts=["piscina_verano"], descriptors=["veraniega"]),
            track("lo", artist="B", energy=20, valence=75, warmth=80,
                  contexts=["piscina_verano"], descriptors=["veraniega"])]
    picked = select(pool, POOL_QUERY, limit=2, min_score=0, order="flow")
    assert [t["id"] for t in picked] == ["lo", "hi"]


def test_min_score_filters_the_pool():
    pool = [track("bad", energy=100, valence=0, warmth=0, descriptors=["densa"])]
    assert select(pool, POOL_QUERY, min_score=55) == []
