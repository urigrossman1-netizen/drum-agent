"""Fill the catalog: the project's own example song, and song lists (CSV).

`seed_examples` stores the Northbound example (an original composition written as a
chart spec, so its chart is the song itself) as an existing chart. `import_csv` adds
songs from a list (title, artist and optionally album, year) as NEEDS_SOURCE entries:
it creates no charts and analyses nothing; each song waits for an authorized recording.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..charts import load_any
from .jobs import JobRunner
from .store import Store

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "specs"
SEED = ("03_full_song_northbound.yaml",)


def seed_examples(store: Store, runner: JobRunner) -> list[dict]:
    out = []
    for name in SEED:
        path = EXAMPLES / name
        if not path.is_file():
            continue
        score = load_any(path)
        song = store.upsert_song(title=score.title, artist=score.artist or "Unknown", version="studio",
                                 provider="library")
        if store.charts_for(song["id"]):
            continue
        try:
            out.append(runner._save_chart(song, score, lambda stage: None, origin="library_chart"))
        except Exception:
            store.delete_project(song["id"])  # not left behind as a song waiting for a recording
            raise
    return out


def import_csv(store: Store, path: str | Path) -> int:
    """Rows with 'title' and 'artist' columns (case-insensitive; 'song' is accepted for title)."""
    count = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            title, artist = row.get("title") or row.get("song"), row.get("artist")
            if not title or not artist:
                continue
            year = row.get("year", "")
            store.upsert_song(title=title, artist=artist, album=row.get("album") or None,
                              year=int(year) if year.isdigit() else None, version=row.get("version") or None)
            count += 1
    return count
