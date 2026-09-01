"""Compara un modelo contra las etiquetas que ya hay en la base.

Responde a la pregunta que decide si merece la pena un modelo local: ¿sus
perfiles se parecen a los buenos, o son ruido con otra cara?

Lo que importa no es que acierte el valor exacto, sino la **correlacion**: si
sus notas suben y bajan con las de referencia, el scorer sigue discriminando
aunque esten desplazadas. Una correlacion cerca de cero significa que ese eje
no aporta nada.

    python scripts/comparar_modelos.py                    # 40 canciones, lotes de 10
    python scripts/comparar_modelos.py 24 4 ollama qwen2.5:14b

No se toca la base: esto solo lee.
"""
import logging, math, random, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("httpx2").setLevel(logging.WARNING)

from app.config import settings
from app.db import Library
from app.lastfm import album_key, artist_key, merge
from app.llm import build_model
from app.tagger import Tagger
from app.vibes import AXES, TAGGER_VERSION

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
LOTE = int(sys.argv[2]) if len(sys.argv) > 2 else 10
PROVEEDOR = sys.argv[3] if len(sys.argv) > 3 else "ollama"
MODELO = sys.argv[4] if len(sys.argv) > 4 else "qwen2.5:14b"

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
tagger = Tagger(build_model(PROVEEDOR, MODELO))

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
if not comunes:
    print("\nEl modelo no devolvio ni un perfil valido.")
    raise SystemExit(1)
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
