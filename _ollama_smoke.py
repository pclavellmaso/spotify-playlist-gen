import json, logging, sqlite3, time
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.config import settings
from app.db import Library
from app.lastfm import album_key, artist_key, merge
from app.llm import build_model
from app.tagger import Tagger
from app.vibes import TAGGER_VERSION

library = Library(settings.db_path)
tracks = library.tagged_tracks("liked", TAGGER_VERSION)[:5]

# Se adjuntan los tags de Last.fm del cache, igual que en el barrido real.
claves = []
for t in tracks:
    a = (t["artists"] or [""])[0]
    claves += [artist_key(a)] + ([album_key(a, t["album"])] if t.get("album") else [])
cache = library.lastfm_tags(claves)
for t in tracks:
    a = (t["artists"] or [""])[0]
    t["lastfm_tags"] = merge(cache.get(album_key(a, t["album"]), []) if t.get("album") else [],
                             cache.get(artist_key(a), []))

modelo = build_model("ollama", "qwen2.5:7b")
print(f"modelo: {modelo.nombre} en {modelo.base_url}\n")
for t in tracks:
    print(f"  {', '.join(t['artists'])[:30]:<32} {t['name'][:30]:<32} tags: {', '.join(t['lastfm_tags'][:4])}")

t0 = time.monotonic()
vibes = Tagger(modelo).tag_batch(tracks)
print(f"\ntardo {time.monotonic()-t0:.1f}s · devolvio {len(vibes)} de {len(tracks)}")
for v in vibes:
    print(f"  {v.track_id}  E{v.energy} V{v.valence} D{v.danceability} A{v.acousticness} "
          f"T{v.tempo_feel} Voz{v.vocal_focus} W{v.warmth} conf{v.confidence}")
    print(f"     ctx={v.contexts} desc={v.descriptors}")
