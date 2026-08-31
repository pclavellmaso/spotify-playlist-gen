"""Cache local en SQLite: biblioteca del usuario + etiquetas de vibe.

Etiquetar es la parte cara, asi que se guarda de forma permanente y se
reutiliza en cada consulta. Una cancion solo se vuelve a etiquetar si sube
TAGGER_VERSION.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    artists      TEXT NOT NULL,
    album        TEXT,
    release_year INTEGER,
    duration_ms  INTEGER,
    popularity   INTEGER,
    source       TEXT NOT NULL,
    added_at     TEXT,
    synced_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibes (
    track_id       TEXT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    tagger_version INTEGER NOT NULL,
    axes           TEXT NOT NULL,
    contexts       TEXT NOT NULL,
    descriptors    TEXT NOT NULL,
    confidence     INTEGER NOT NULL,
    tagged_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lastfm_tags (
    track_id   TEXT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    tags       TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source);
"""


class Library:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- tracks ------------------------------------------------------------
    def upsert_tracks(self, tracks: Iterable[dict[str, Any]]) -> int:
        rows = [
            (
                t["id"],
                t["name"],
                json.dumps(t["artists"], ensure_ascii=False),
                t.get("album"),
                t.get("release_year"),
                t.get("duration_ms"),
                t.get("popularity"),
                t["source"],
                t.get("added_at"),
            )
            for t in tracks
        ]
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO tracks
                    (id, name, artists, album, release_year, duration_ms,
                     popularity, source, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    artists=excluded.artists,
                    album=excluded.album,
                    release_year=excluded.release_year,
                    duration_ms=excluded.duration_ms,
                    popularity=excluded.popularity,
                    source=excluded.source,
                    added_at=excluded.added_at,
                    synced_at=datetime('now')
                """,
                rows,
            )
        return len(rows)

    def tracks_for_source(self, source: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks WHERE source = ? ORDER BY added_at DESC", (source,)
            ).fetchall()
        return [_track_row(r) for r in rows]

    def sources(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) AS total FROM tracks GROUP BY source"
            ).fetchall()
        return [dict(r) for r in rows]

    # -- vibes -------------------------------------------------------------
    def untagged(self, source: str, tagger_version: int) -> list[dict[str, Any]]:
        """Canciones de `source` sin etiqueta valida para esta version."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM tracks t
                LEFT JOIN vibes v ON v.track_id = t.id AND v.tagger_version = ?
                WHERE t.source = ? AND v.track_id IS NULL
                ORDER BY t.added_at DESC
                """,
                (tagger_version, source),
            ).fetchall()
        return [_track_row(r) for r in rows]

    def save_vibes(self, vibes: Iterable[Any], tagger_version: int) -> int:
        from app.vibes import AXES

        rows = [
            (
                v.track_id,
                tagger_version,
                json.dumps({axis: getattr(v, axis) for axis in AXES}),
                json.dumps(v.contexts),
                json.dumps([d.lower().strip() for d in v.descriptors], ensure_ascii=False),
                v.confidence,
            )
            for v in vibes
        ]
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO vibes
                    (track_id, tagger_version, axes, contexts, descriptors, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    tagger_version=excluded.tagger_version,
                    axes=excluded.axes,
                    contexts=excluded.contexts,
                    descriptors=excluded.descriptors,
                    confidence=excluded.confidence,
                    tagged_at=datetime('now')
                """,
                rows,
            )
        return len(rows)

    def tagged_tracks(self, source: str, tagger_version: int) -> list[dict[str, Any]]:
        """Canciones con su perfil, listas para puntuar."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, v.axes, v.contexts, v.descriptors, v.confidence
                FROM tracks t
                JOIN vibes v ON v.track_id = t.id
                WHERE t.source = ? AND v.tagger_version = ?
                """,
                (source, tagger_version),
            ).fetchall()

        out = []
        for row in rows:
            track = _track_row(row)
            track["axes"] = json.loads(row["axes"])
            track["contexts"] = json.loads(row["contexts"])
            track["descriptors"] = json.loads(row["descriptors"])
            track["confidence"] = row["confidence"]
            out.append(track)
        return out

    # -- tags de last.fm ---------------------------------------------------
    def lastfm_tags(self, track_ids: list[str]) -> dict[str, list[str]]:
        """Tags cacheados. Una entrada con lista vacia significa 'ya preguntado'."""
        if not track_ids:
            return {}
        out: dict[str, list[str]] = {}
        with self.connect() as conn:
            # SQLite tiene un tope de variables por consulta, de ahi los trozos.
            for i in range(0, len(track_ids), 500):
                chunk = track_ids[i : i + 500]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT track_id, tags FROM lastfm_tags WHERE track_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                out.update({r["track_id"]: json.loads(r["tags"]) for r in rows})
        return out

    def save_lastfm_tags(self, tags_by_track: dict[str, list[str]]) -> int:
        if not tags_by_track:
            return 0
        rows = [
            (track_id, json.dumps(tags, ensure_ascii=False))
            for track_id, tags in tags_by_track.items()
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO lastfm_tags (track_id, tags)
                VALUES (?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    tags=excluded.tags,
                    fetched_at=datetime('now')
                """,
                rows,
            )
        return len(rows)

    def stats(self, source: str, tagger_version: int) -> dict[str, int]:
        with self.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE source = ?", (source,)
            ).fetchone()[0]
            tagged = conn.execute(
                """
                SELECT COUNT(*) FROM tracks t
                JOIN vibes v ON v.track_id = t.id AND v.tagger_version = ?
                WHERE t.source = ?
                """,
                (tagger_version, source),
            ).fetchone()[0]
        return {"total": total, "tagged": tagged, "pending": total - tagged}


def _track_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "artists": json.loads(row["artists"]),
        "album": row["album"],
        "release_year": row["release_year"],
        "duration_ms": row["duration_ms"],
        "popularity": row["popularity"],
        "source": row["source"],
        "added_at": row["added_at"],
    }
