"""A/B entre el modelo local y Claude sobre las MISMAS canciones.

Claude ya perfilo las 1788, asi que sirven de referencia. No se toca la base:
esto solo lee.
"""
import json, logging, math, random, statistics, sys, time
logging.getLogger("httpx2").setLevel(logging.WARNING)

from app.config import settings
from app.db import Library
from app.lastfm import album_key, artist_key, merge
from app.llm import build_model
from app.tagger import Tagger
from app.vibes import AXES, TAGGER_VERSION

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
LOTE = int(sys.argv[2]) if len(sys.argv) > 2 else 10

library = Library(settings.db_path)
todas = library.tagged_tracks("liked", TAGGER_VERSION)
random.seed(7)
muestra = random.sample(todas, N)

claves = []
for t in muestra:
    a = (t["artists"] or [""])[0]
    claves += [artist_key(a)] + ([album_key(a, t["album"])] if t.get("album") else [])
cache = library.lastfm_tags(claves)
for t in muestra:
    a = (t["artists"] or [""])[0]
    t["lastfm_tags"] = merge(cache.get(album_key(a, t["album"]), []) if t.get("album") else [],
                             cache.get(artist_key(a), []))

referencia = {t["id"]: t for t in muestra}
tagger = Tagger(build_model("ollama", "qwen2.5:14b"))

t0 = time.monotonic()
local = {}
for lote in [muestra[i:i+LOTE] for i in range(0, len(muestra), LOTE)]:
    try:
        for v in tagger.tag_batch(lote):
            local[v.track_id] = v
    except Exception as exc:
        print(f"  lote fallido: {exc}")
    print(f"  {len(local)}/{N} en {time.monotonic()-t0:.0f}s", flush=True)
segundos = time.monotonic() - t0

comunes = [i for i in referencia if i in local]
print(f"\n=== {len(comunes)} de {N} perfiladas por el modelo local ===")
print(f"tiempo: {segundos:.0f}s · {segundos/max(len(comunes),1):.1f}s por cancion")
print(f"extrapolado a 1788: {segundos/max(len(comunes),1)*1788/3600:.1f} horas\n")

def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return num/den if den else 0.0

print(f"{'eje':<14} {'Claude':>12} {'local':>12} {'dif.media':>10} {'correl':>8}")
for eje in AXES:
    c = [referencia[i]["axes"][eje] for i in comunes]
    o = [getattr(local[i], eje) for i in comunes]
    dif = statistics.mean(abs(a-b) for a, b in zip(c, o))
    print(f"{eje:<14} {statistics.mean(c):>6.1f}±{statistics.pstdev(c):<5.1f} "
          f"{statistics.mean(o):>6.1f}±{statistics.pstdev(o):<5.1f} {dif:>10.1f} {pearson(c,o):>8.2f}")

cc = [referencia[i]["confidence"] for i in comunes]
co = [local[i].confidence for i in comunes]
print(f"\nconfidence     Claude {statistics.mean(cc):.1f}  ·  local {statistics.mean(co):.1f}")

ctx_c = sum(len(referencia[i]["contexts"]) for i in comunes)/len(comunes)
ctx_o = sum(len(local[i].contexts) for i in comunes)/len(comunes)
coincide = sum(1 for i in comunes if set(referencia[i]["contexts"]) & set(local[i].contexts))
print(f"contextos/cancion  Claude {ctx_c:.1f}  ·  local {ctx_o:.1f}")
print(f"canciones con algun contexto en comun: {coincide} de {len(comunes)}")

print("\n--- tres ejemplos ---")
for i in comunes[:3]:
    r, l = referencia[i], local[i]
    print(f"\n{', '.join(r['artists'])[:34]} — {r['name'][:34]}")
    print(f"  Claude E{r['axes']['energy']} T{r['axes']['tempo_feel']} W{r['axes']['warmth']} "
          f"conf{r['confidence']} · {', '.join(r['descriptors'][:4])}")
    print(f"  local  E{l.energy} T{l.tempo_feel} W{l.warmth} conf{l.confidence} · "
          f"{', '.join(l.descriptors[:4])}")
