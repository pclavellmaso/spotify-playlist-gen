"""Informe de calidad del etiquetado, y comparacion contra un snapshot.

La pregunta que este proyecto tiene que responderse cada vez que se toca el
etiquetador es siempre la misma: ¿los perfiles tienen sentido *para esta
biblioteca*? El `confidence` es la senal principal, porque un perfil con
confianza baja no se descarta, se arrastra hacia neutro, y si eso le pasa a
media biblioteca el scorer se queda sin nada con lo que discriminar.

    python scripts/vibes_report.py
    python scripts/vibes_report.py data/snapshots/vibes-v1-2026-09-01.json

Con un snapshot delante compara cancion a cancion. Para que la comparacion sea
limpia hay que guardar el snapshot ANTES de re-etiquetar: `save_vibes`
sobrescribe por `track_id`.

    python scripts/vibes_report.py --snapshot   # guarda el estado actual
"""
from __future__ import annotations

import json
import statistics
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def load_current() -> list[dict]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.artists, t.release_year,
               v.tagger_version, v.axes, v.contexts, v.descriptors, v.confidence
        FROM tracks t JOIN vibes v ON v.track_id = t.id
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def snapshot() -> Path:
    rows = load_current()
    path = ROOT / "data" / "snapshots" / f"vibes-{date.today().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"{len(rows)} etiquetas guardadas en {path.relative_to(ROOT)}")
    return path


def _histogram(values: list[int], width: int = 40) -> None:
    buckets = Counter(f"{v // 20 * 20:>3}-{v // 20 * 20 + 19}" for v in values)
    peak = max(buckets.values()) if buckets else 1
    for label in sorted(buckets):
        n = buckets[label]
        print(f"  {label}: {'#' * max(1, round(n / peak * width))} ({n})")


def report(rows: list[dict]) -> None:
    if not rows:
        print("No hay ninguna cancion etiquetada todavia.")
        return

    print(f"=== {len(rows)} canciones etiquetadas "
          f"(tagger_version {rows[0]['tagger_version']}) ===\n")

    confs = [r["confidence"] for r in rows]
    print("CONFIDENCE")
    print(f"  media {statistics.mean(confs):.1f} · mediana {statistics.median(confs)} · "
          f"min {min(confs)} · max {max(confs)}")
    bajas = sum(1 for c in confs if c < 40)
    print(f"  por debajo de 40: {bajas} ({bajas / len(confs):.0%})")
    _histogram(confs)

    print("\nCONTEXTOS")
    ctx = Counter(c for r in rows for c in json.loads(r["contexts"]))
    for name, n in ctx.most_common(10):
        print(f"  {n:>4}  {name}  ({n / len(rows):.0%} de la biblioteca)")
    vacios = sum(1 for r in rows if not json.loads(r["contexts"]))
    por_cancion = sum(len(json.loads(r["contexts"])) for r in rows) / len(rows)
    print(f"  media de {por_cancion:.1f} contextos por cancion · {vacios} sin ninguno")

    print("\nEJES")
    axes_all = [json.loads(r["axes"]) for r in rows]
    for axis in axes_all[0]:
        vals = [a[axis] for a in axes_all]
        print(f"  {axis:<14} media {statistics.mean(vals):>5.1f} · "
              f"desv {statistics.pstdev(vals):>4.1f} · rango {min(vals):>3}-{max(vals)}")

    print("\nDESCRIPTORES mas usados")
    for d, n in Counter(d for r in rows for d in json.loads(r["descriptors"])).most_common(12):
        print(f"  {n:>4}  {d}")


def compare(before: list[dict], after: list[dict]) -> None:
    prev = {r["id"]: r for r in before}
    common = [r for r in after if r["id"] in prev]
    if not common:
        print("\nNinguna cancion en comun con el snapshot.")
        return

    print(f"\n\n=== COMPARACION sobre {len(common)} canciones en comun ===\n")
    antes = [prev[r["id"]]["confidence"] for r in common]
    ahora = [r["confidence"] for r in common]

    print("CONFIDENCE          antes    ahora")
    print(f"  media           {statistics.mean(antes):>7.1f}  {statistics.mean(ahora):>7.1f}"
          f"   ({statistics.mean(ahora) - statistics.mean(antes):+.1f})")
    print(f"  mediana         {statistics.median(antes):>7.1f}  {statistics.median(ahora):>7.1f}")
    b_a = sum(1 for c in antes if c < 40) / len(antes)
    b_d = sum(1 for c in ahora if c < 40) / len(ahora)
    print(f"  por debajo 40   {b_a:>6.0%}   {b_d:>6.0%}")

    subidas = [r for r in common if r["confidence"] > prev[r["id"]]["confidence"]]
    bajadas = [r for r in common if r["confidence"] < prev[r["id"]]["confidence"]]
    print(f"\n  sube en {len(subidas)}, baja en {len(bajadas)}, "
          f"igual en {len(common) - len(subidas) - len(bajadas)}")

    print("\nMAYORES SUBIDAS")
    for r in sorted(subidas, key=lambda r: prev[r["id"]]["confidence"] - r["confidence"])[:10]:
        artists = ", ".join(json.loads(r["artists"]))
        print(f"  {prev[r['id']]['confidence']:>3} -> {r['confidence']:>3}   {artists} — {r['name']}")

    if bajadas:
        print("\nMAYORES BAJADAS")
        for r in sorted(bajadas, key=lambda r: r["confidence"] - prev[r["id"]]["confidence"])[:5]:
            artists = ", ".join(json.loads(r["artists"]))
            print(f"  {prev[r['id']]['confidence']:>3} -> {r['confidence']:>3}   {artists} — {r['name']}")

    ctx_antes = sum(len(json.loads(prev[r["id"]]["contexts"])) for r in common) / len(common)
    ctx_ahora = sum(len(json.loads(r["contexts"])) for r in common) / len(common)
    print(f"\nCONTEXTOS por cancion: {ctx_antes:.1f} -> {ctx_ahora:.1f}")

    axes_antes = [json.loads(prev[r["id"]]["axes"]) for r in common]
    axes_ahora = [json.loads(r["axes"]) for r in common]
    print("\nDISPERSION de los ejes (mas alta = discrimina mas)")
    for axis in axes_ahora[0]:
        a = statistics.pstdev([x[axis] for x in axes_antes])
        d = statistics.pstdev([x[axis] for x in axes_ahora])
        print(f"  {axis:<14} {a:>5.1f} -> {d:>5.1f}   ({d - a:+.1f})")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--snapshot":
        snapshot()
    else:
        current = load_current()
        report(current)
        if args:
            compare(json.loads(Path(args[0]).read_text()), current)
