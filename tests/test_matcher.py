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


# -- especificidad del contexto ---------------------------------------------
# Un acierto plano premiaba a las canciones que se apuntan a todo: sobre una
# biblioteca real el etiquetador repartia 3,4 contextos por tema y `fiesta`
# salia en el 57%, con lo que casi cualquier cancion acertaba.
CTX_QUERY = VibeQuery(label="x", targets={}, contexts=["piscina_verano"])


def test_una_cancion_especifica_puntua_mas_que_una_que_se_apunta_a_todo():
    especifica = track("e", contexts=["piscina_verano"])
    promiscua = track("p", contexts=["piscina_verano", "fiesta", "conducir", "tareas_casa"])
    assert score_track(especifica, CTX_QUERY) > score_track(promiscua, CTX_QUERY)


def test_el_acierto_unico_sigue_valiendo_lo_maximo():
    assert score_track(track("e", contexts=["piscina_verano"]), CTX_QUERY) == 100.0


def test_el_acierto_se_diluye_en_proporcion():
    dos = track("d", contexts=["piscina_verano", "fiesta"])
    cuatro = track("c", contexts=["piscina_verano", "fiesta", "conducir", "tareas_casa"])
    assert score_track(dos, CTX_QUERY) == 75.0
    assert score_track(cuatro, CTX_QUERY) == 62.5


def test_acertar_varios_contextos_pedidos_no_penaliza():
    query = VibeQuery(label="x", targets={}, contexts=["piscina_verano", "terraza_atardecer"])
    ambos = track("a", contexts=["piscina_verano", "terraza_atardecer"])
    assert score_track(ambos, query) == 100.0


def test_no_acertar_nada_sigue_puntuando_bajo():
    assert score_track(track("m", contexts=["entrenamiento"]), CTX_QUERY) == 25.0


def test_sin_contextos_declarados_no_hay_evidencia():
    # Una lista vacia es una respuesta valida del etiquetador, no un fallo.
    assert score_track(track("v", contexts=[]), CTX_QUERY) == 50.0


# -- los ejes son conjuntivos -----------------------------------------------
# Antes esto era la media de errores absolutos y compensaba: Papi Chulo sacaba
# 68,7 en una peticion de "calma" pese a fallar por 43 y 45 puntos en energy y
# tempo_feel, porque acertaba en valence y warmth.
CALMA = VibeQuery(
    label="x",
    targets={"energy": 35, "valence": 75, "tempo_feel": 35, "warmth": 80},
    weights={"energy": 1.0, "valence": 1.0, "tempo_feel": 0.8, "warmth": 0.7},
)


def _axes(**kwargs):
    base = {"energy": 50, "valence": 50, "danceability": 50, "acousticness": 50,
            "tempo_feel": 50, "vocal_focus": 50, "warmth": 50}
    return {**base, **kwargs}


def _score_axes(**kwargs):
    t = track("t", confidence=100)
    t["axes"] = _axes(**kwargs)
    return score_track(t, CALMA)


def test_un_encaje_perfecto_puntua_lo_maximo():
    assert _score_axes(energy=35, valence=75, tempo_feel=35, warmth=80) == 100.0


def test_fallar_de_lleno_en_un_eje_importante_no_se_compensa():
    # Acierta valence y warmth, falla energy y tempo_feel: no vale.
    fiesta = _score_axes(energy=78, valence=75, tempo_feel=80, warmth=80)
    assert fiesta < 40, fiesta


def test_acertar_de_cerca_en_todo_puntua_alto():
    cerca = _score_axes(energy=45, valence=72, tempo_feel=45, warmth=75)
    assert cerca > 70, cerca


def test_un_solo_eje_catastrofico_arrastra_el_conjunto():
    # Media geometrica: un termino cerca de cero manda sobre los demas.
    todo_bien = _score_axes(energy=35, valence=75, tempo_feel=35, warmth=80)
    una_mal = _score_axes(energy=100, valence=75, tempo_feel=35, warmth=80)
    assert todo_bien == 100.0
    assert una_mal < 30, una_mal


def test_el_peso_gradua_el_castigo():
    # Mismo desajuste de 45 puntos, en un eje de peso 1.0 y en uno de peso 0.7.
    pesado = _score_axes(energy=80, valence=75, tempo_feel=35, warmth=80)
    ligero = _score_axes(energy=35, valence=75, tempo_feel=35, warmth=35)
    assert pesado < ligero


def test_un_desajuste_pequenyo_apenas_penaliza():
    assert _score_axes(energy=40, valence=75, tempo_feel=35, warmth=80) > 90


# -- forma de la curva ------------------------------------------------------
def _energias(picked):
    return [t["axes"]["energy"] for t in picked]


def _pool(*energias):
    salida = []
    for i, e in enumerate(energias):
        t = track(f"t{i}", artist=f"A{i}", confidence=100)
        t["axes"]["energy"] = e
        t["duration_ms"] = 180000  # tres minutos
        salida.append(t)
    return salida


LIBRE = VibeQuery(label="x", targets={"valence": 50}, weights={"valence": 1.0})


def test_la_curva_ascendente_empieza_floja():
    picked = select(_pool(90, 20, 60, 40), LIBRE, min_score=0, order="rise", max_per_artist=1)
    assert _energias(picked) == [20, 40, 60, 90]


def test_la_curva_descendente_es_para_irse_a_la_cama():
    picked = select(_pool(90, 20, 60, 40), LIBRE, min_score=0, order="fall", max_per_artist=1)
    assert _energias(picked) == [90, 60, 40, 20]


def test_la_curva_en_pico_sube_y_baja():
    # Las mas intensas al centro, las flojas repartidas a los extremos.
    picked = select(_pool(10, 30, 50, 70, 90), LIBRE, min_score=0, order="peak", max_per_artist=1)
    energias = _energias(picked)
    assert energias[0] < energias[len(energias) // 2] > energias[-1]
    assert energias == [10, 50, 90, 70, 30]


def test_flow_sigue_valiendo_como_ascendente():
    a = select(_pool(90, 20, 60), LIBRE, min_score=0, order="flow", max_per_artist=1)
    b = select(_pool(90, 20, 60), LIBRE, min_score=0, order="rise", max_per_artist=1)
    assert _energias(a) == _energias(b)


def test_ordenar_por_afinidad_ignora_la_energia():
    picked = select(_pool(90, 20, 60), LIBRE, min_score=0, order="score", max_per_artist=1)
    notas = [t["score"] for t in picked]
    assert notas == sorted(notas, reverse=True)


# -- duración objetivo ------------------------------------------------------
def test_se_puede_pedir_por_minutos_en_vez_de_por_canciones():
    # Canciones de 3 minutos: 20 minutos son 7 (la septima cruza el objetivo).
    picked = select(_pool(*([50] * 20)), LIBRE, limit=100, min_score=0,
                    max_per_artist=1, target_minutes=20)
    assert len(picked) == 7


def test_el_limite_sigue_siendo_un_tope_duro():
    # Una duracion imposible no debe devolver la biblioteca entera.
    picked = select(_pool(*([50] * 20)), LIBRE, limit=5, min_score=0,
                    max_per_artist=1, target_minutes=600)
    assert len(picked) == 5


def test_sin_minutos_manda_el_numero_de_canciones():
    picked = select(_pool(*([50] * 20)), LIBRE, limit=4, min_score=0, max_per_artist=1)
    assert len(picked) == 4


# -- perfil medio de una lista ("más como esto") ----------------------------
from app.matcher import blend, profile_from_tracks  # noqa: E402


def _perfilada(tid, energy, valence=50, conf=90, contexts=None, descriptors=None):
    t = track(tid, artist=tid, confidence=conf, contexts=contexts, descriptors=descriptors)
    t["axes"]["energy"] = energy
    t["axes"]["valence"] = valence
    return t


def test_el_centroide_recoge_el_caracter_de_la_lista():
    perfil = profile_from_tracks([_perfilada("a", 80), _perfilada("b", 84), _perfilada("c", 82)])
    assert 80 <= perfil.targets["energy"] <= 84


def test_un_eje_consistente_pesa_mas_que_uno_disperso():
    # Si todas rondan energia 80, la energia define la lista. Si la valencia va
    # de 10 a 90, no dice nada de ella.
    perfil = profile_from_tracks([
        _perfilada("a", 80, valence=10),
        _perfilada("b", 82, valence=90),
        _perfilada("c", 81, valence=50),
    ])
    assert perfil.weights["energy"] > perfil.weights["valence"]


def test_las_canciones_que_el_modelo_no_conocia_arrastran_menos():
    # La de confianza 10 tiene un perfil que es casi el prior del genero.
    perfil = profile_from_tracks([_perfilada("a", 90, conf=100), _perfilada("b", 20, conf=10)])
    assert perfil.targets["energy"] > 70


def test_solo_entran_los_contextos_que_comparte_buena_parte_de_la_lista():
    lista = [_perfilada(f"t{i}", 70, contexts=["fiesta"]) for i in range(4)]
    lista.append(_perfilada("raro", 70, contexts=["dormir"]))
    perfil = profile_from_tracks(lista)
    assert "fiesta" in perfil.contexts and "dormir" not in perfil.contexts


def test_una_lista_sin_analizar_no_da_perfil():
    import pytest
    with pytest.raises(ValueError, match="analizada"):
        profile_from_tracks([{"id": "x", "artists": ["A"]}])


# -- mezclar el perfil con una petición escrita -----------------------------
def test_lo_que_pides_por_escrito_manda_sobre_el_centroide():
    base = profile_from_tracks([_perfilada("a", 85), _perfilada("b", 85)])
    encima = VibeQuery(label="mas tranquilo", targets={"energy": 30}, weights={"energy": 1.0})
    mezcla = blend(base, encima)
    assert mezcla.targets["energy"] == 30
    assert mezcla.weights["energy"] == 1.0


def test_los_ejes_que_no_mencionas_los_sigue_poniendo_la_lista():
    base = profile_from_tracks([_perfilada("a", 85, valence=70), _perfilada("b", 85, valence=72)])
    mezcla = blend(base, VibeQuery(label="x", targets={"energy": 30}))
    assert 70 <= mezcla.targets["valence"] <= 72
    assert mezcla.label == "x"
