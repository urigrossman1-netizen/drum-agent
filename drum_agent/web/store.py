"""Persistent state for the web app: SQLite plus a data directory.

Tables:
  songs    one row per recording the user picked (stable id from the provider's id,
           or from title and artist when the provider gives none)
  sources  audio a user supplied for a song, with the rights basis they stated; the file
           itself lives under data/sources/<sha256>.wav (normalized) and is never served
  jobs     one transcription run: status, current stage, stage log, error, attempts
  charts   a chart version: score.json and its exports under data/charts/<id>/, its
           validation, status and the job that made it

Chart versions are immutable: a correction makes a new version (version + 1), so a
printed chart can always be traced back to the exact score that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  artist TEXT NOT NULL,
  album TEXT,
  year INTEGER,
  duration_s REAL,
  isrc TEXT,
  version TEXT,
  provider TEXT,
  provider_ids TEXT NOT NULL DEFAULT '{}',
  urls TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  kind TEXT NOT NULL DEFAULT 'song',   -- song (a recording) | beat (an original beat)
  prompt TEXT,                          -- the description an original beat was generated from
  draft TEXT,                           -- unsaved working score {score, base_chart_id, saved_at}
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL REFERENCES songs(id),
  kind TEXT NOT NULL,              -- upload | library | verified_asset
  rights TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  original_name TEXT,
  path TEXT NOT NULL,
  info TEXT NOT NULL DEFAULT '{}', -- ffprobe properties, levels, duration
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sources_song ON sources(song_id);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL REFERENCES songs(id),
  source_id TEXT REFERENCES sources(id),  -- the recording (transcribe jobs only)
  kind TEXT NOT NULL DEFAULT 'transcribe', -- transcribe | generate
  params TEXT NOT NULL DEFAULT '{}',
  engine TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL,            -- queued | running | succeeded | failed | cancelled
  stage TEXT,
  stages TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  error_code TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  chart_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_key ON jobs(idempotency_key);
CREATE TABLE IF NOT EXISTS charts (
  id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL REFERENCES songs(id),
  version INTEGER NOT NULL,
  parent_id TEXT,
  job_id TEXT,
  source_id TEXT,
  status TEXT NOT NULL,            -- COMPLETE | NEEDS_CORRECTION
  origin TEXT NOT NULL,            -- transcription | verified_chart | correction
  bars INTEGER NOT NULL,
  validation TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '{}',
  dir TEXT NOT NULL,
  created_at REAL NOT NULL,
  note TEXT,                       -- what made this version ("Generated", "Grid edits", ...)
  UNIQUE(song_id, version)
);
"""

JOB_COLUMNS = ("id, song_id, source_id, kind, params, engine, idempotency_key, status, stage, stages, error, "
               "error_code, attempts, cancel_requested, chart_id, created_at, updated_at")

JSON_COLUMNS = {"provider_ids", "urls", "info", "stages", "validation", "summary", "params", "draft"}


def song_id_for(title: str, artist: str, provider: str | None = None, provider_id: str | None = None) -> str:
    """Stable song id: the provider's own id when there is one, else title and artist."""
    from ..song.lookup import artist_key, title_key
    basis = f"{provider}:{provider_id}" if provider and provider_id else f"{title_key(title)}|{artist_key(artist)}"
    return "s_" + hashlib.sha1(basis.encode()).hexdigest()[:16]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir).resolve()
        for sub in ("sources", "charts", "uploads", "previews", "samples"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.root / "drum_agent.sqlite3"), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Bring a database made by an earlier version up to the current tables."""
        cols = lambda t: {r[1]: r for r in self._db.execute(f"PRAGMA table_info({t})")}
        songs = cols("songs")
        for name, decl in (("kind", "TEXT NOT NULL DEFAULT 'song'"), ("prompt", "TEXT"), ("draft", "TEXT"),
                           ("updated_at", "REAL")):
            if name not in songs:
                self._db.execute(f"ALTER TABLE songs ADD COLUMN {name} {decl}")
        if "note" not in cols("charts"):
            self._db.execute("ALTER TABLE charts ADD COLUMN note TEXT")
        jobs = cols("jobs")
        if "kind" not in jobs:  # source_id becomes optional: rebuild the table (rows are copied as they are)
            self._db.commit()
            self._db.execute("PRAGMA foreign_keys=OFF")
            old = ", ".join(c for c in JOB_COLUMNS.split(", ") if c not in ("kind", "params"))
            self._db.executescript(
                "ALTER TABLE jobs RENAME TO jobs_v1;" + SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS jobs"):
                                                               SCHEMA.index("CREATE TABLE IF NOT EXISTS charts")]
                + f"INSERT INTO jobs ({old}, kind, params) SELECT {old}, 'transcribe', '{{}}' FROM jobs_v1;"
                "DROP TABLE jobs_v1;")
            self._db.execute("PRAGMA foreign_keys=ON")

    # ---- helpers ---------------------------------------------------------
    def _row(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_COLUMNS & d.keys():
            d[k] = json.loads(d[k]) if d[k] else (None if k == "draft" else [] if k == "stages" else {})
        return d

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [self._row(r) for r in self._db.execute(sql, args).fetchall()]

    def _x(self, sql: str, args: tuple = ()) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def chart_dir(self, chart_id: str) -> Path:
        return self.root / "charts" / chart_id

    # ---- songs -----------------------------------------------------------
    def upsert_song(self, *, title: str, artist: str, album: str | None = None, year: int | None = None,
                    duration_s: float | None = None, isrc: str | None = None, version: str | None = None,
                    provider: str | None = None, provider_id: str | None = None,
                    urls: dict | None = None, song_id: str | None = None, kind: str = "song",
                    prompt: str | None = None) -> dict:
        sid = song_id or song_id_for(title, artist, provider, provider_id)
        existing = self.get_song(sid)
        ids = dict(existing["provider_ids"]) if existing else {}
        if provider and provider_id:
            ids[provider] = provider_id
        merged_urls = {**(existing["urls"] if existing else {}), **(urls or {})}
        with self._lock:
            if existing:
                self._db.execute(
                    "UPDATE songs SET album=COALESCE(album, ?), year=COALESCE(year, ?), "
                    "duration_s=COALESCE(duration_s, ?), isrc=COALESCE(isrc, ?), version=COALESCE(version, ?), "
                    "provider_ids=?, urls=? WHERE id=?",
                    (album, year, duration_s, isrc, version, json.dumps(ids), json.dumps(merged_urls), sid))
            else:
                now = time.time()
                self._db.execute(
                    "INSERT INTO songs (id, title, artist, album, year, duration_s, isrc, version, provider, "
                    "provider_ids, urls, created_at, kind, prompt, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, title, artist, album, year, duration_s, isrc, version, provider, json.dumps(ids),
                     json.dumps(merged_urls), now, kind, prompt, now))
            self._db.commit()
        return self.get_song(sid)

    def get_song(self, song_id: str) -> dict | None:
        r = self._q("SELECT * FROM songs WHERE id=?", (song_id,))
        return r[0] if r else None

    def find_songs(self, text: str, limit: int = 20) -> list[dict]:
        """Songs already in the catalog whose title or artist matches every word of `text`."""
        from ..song.lookup import text_key
        words = text_key(text).split()
        rows = self._q("SELECT * FROM songs ORDER BY created_at DESC")
        out = []
        for r in rows:
            hay = text_key(f"{r['title']} {r['artist']} {r['album'] or ''}")
            if all(w in hay.split() or w in hay for w in words):
                out.append(r)
        return out[:limit]

    def list_songs(self, limit: int = 200) -> list[dict]:
        return self._q("SELECT * FROM songs ORDER BY title COLLATE NOCASE LIMIT ?", (limit,))

    def list_projects(self, text: str = "", kind: str | None = None, limit: int = 500) -> list[dict]:
        rows = self._q("SELECT * FROM songs ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?", (limit,))
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        if text.strip():
            from ..song.lookup import text_key
            words = text_key(text).split()
            rows = [r for r in rows if all(w in text_key(f"{r['title']} {r['artist']} {r['prompt'] or ''}")
                                           for w in words)]
        return rows

    def touch(self, song_id: str) -> None:
        self._x("UPDATE songs SET updated_at=? WHERE id=?", (time.time(), song_id))

    def rename(self, song_id: str, title: str) -> dict:
        self._x("UPDATE songs SET title=?, updated_at=? WHERE id=?", (title, time.time(), song_id))
        return self.get_song(song_id)

    def set_draft(self, song_id: str, draft: dict | None) -> None:
        self._x("UPDATE songs SET draft=?, updated_at=? WHERE id=?",
                (json.dumps(draft) if draft is not None else None, time.time(), song_id))

    def delete_project(self, song_id: str) -> list[str]:
        """Delete a project with its jobs, sources and chart versions; returns the files to remove."""
        paths = [c["dir"] for c in self.charts_for(song_id)]
        for src in self.sources_for(song_id):
            others = self._q("SELECT id FROM sources WHERE sha256=? AND song_id!=?", (src["sha256"], song_id))
            if not others:
                paths.append(src["path"])
        with self._lock:
            for table in ("charts", "jobs", "sources"):
                self._db.execute(f"DELETE FROM {table} WHERE song_id=?", (song_id,))
            self._db.execute("DELETE FROM songs WHERE id=?", (song_id,))
            self._db.commit()
        return paths

    # ---- sources ---------------------------------------------------------
    def add_source(self, *, song_id: str, kind: str, rights: str, sha256: str, path: str,
                   original_name: str | None, info: dict) -> dict:
        existing = self._q("SELECT * FROM sources WHERE song_id=? AND sha256=?", (song_id, sha256))
        if existing:
            return existing[0]
        sid = new_id("src")
        self._x("INSERT INTO sources (id, song_id, kind, rights, sha256, original_name, path, info, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, song_id, kind, rights, sha256, original_name, path, json.dumps(info), time.time()))
        return self.get_source(sid)

    def get_source(self, source_id: str) -> dict | None:
        r = self._q("SELECT * FROM sources WHERE id=?", (source_id,))
        return r[0] if r else None

    def sources_for(self, song_id: str) -> list[dict]:
        return self._q("SELECT * FROM sources WHERE song_id=? ORDER BY created_at DESC", (song_id,))

    # ---- jobs ------------------------------------------------------------
    def create_job(self, *, song_id: str, source_id: str | None, engine: str, key: str, kind: str = "transcribe",
                   params: dict | None = None) -> dict:
        jid, now = new_id("job"), time.time()
        self._x("INSERT INTO jobs (id, song_id, source_id, kind, params, engine, idempotency_key, status, stages, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'queued', '[]', ?, ?)",
                (jid, song_id, source_id, kind, json.dumps(params or {}), engine, key, now, now))
        return self.get_job(jid)

    def get_job(self, job_id: str) -> dict | None:
        r = self._q("SELECT * FROM jobs WHERE id=?", (job_id,))
        return r[0] if r else None

    def job_by_key(self, key: str) -> dict | None:
        """The newest job for this source and engine that did not fail or get cancelled."""
        r = self._q("SELECT * FROM jobs WHERE idempotency_key=? AND status IN ('queued','running','succeeded') "
                    "ORDER BY created_at DESC LIMIT 1", (key,))
        return r[0] if r else None

    def jobs_for(self, song_id: str) -> list[dict]:
        return self._q("SELECT * FROM jobs WHERE song_id=? ORDER BY created_at DESC", (song_id,))

    def jobs_with_status(self, *statuses: str) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        return self._q(f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY created_at", statuses)

    def update_job(self, job_id: str, **fields: Any) -> dict:
        fields["updated_at"] = time.time()
        for k in JSON_COLUMNS & fields.keys():
            fields[k] = json.dumps(fields[k])
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
        return self.get_job(job_id)

    # ---- charts ----------------------------------------------------------
    def add_chart(self, *, chart_id: str, song_id: str, status: str, origin: str, bars: int, validation: dict,
                  summary: dict, job_id: str | None = None, source_id: str | None = None,
                  parent_id: str | None = None, note: str | None = None) -> dict:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(version), 0) FROM charts WHERE song_id=?", (song_id,)).fetchone()
            version = row[0] + 1
            self._db.execute(
                "INSERT INTO charts (id, song_id, version, parent_id, job_id, source_id, status, origin, bars, "
                "validation, summary, dir, created_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (chart_id, song_id, version, parent_id, job_id, source_id, status, origin, bars,
                 json.dumps(validation), json.dumps(summary), str(self.chart_dir(chart_id)), time.time(), note))
            self._db.execute("UPDATE songs SET updated_at=? WHERE id=?", (time.time(), song_id))
            self._db.commit()
        return self.get_chart(chart_id)

    def get_chart(self, chart_id: str) -> dict | None:
        r = self._q("SELECT * FROM charts WHERE id=?", (chart_id,))
        return r[0] if r else None

    def charts_for(self, song_id: str) -> list[dict]:
        return self._q("SELECT * FROM charts WHERE song_id=? ORDER BY version DESC", (song_id,))

    def latest_chart(self, song_id: str) -> dict | None:
        r = self.charts_for(song_id)
        return r[0] if r else None

    def close(self) -> None:
        with self._lock:
            self._db.close()


def default_data_dir() -> Path:
    return Path(os.environ.get("DRUM_AGENT_DATA_DIR") or Path.home() / ".drum_agent" / "web")
