"""Find the song among the user's own audio files.

The best audio for a chart is a file the user already has: a bounce of their
band, a purchased download, a CD rip. `find_local` looks under the music
folders (default `~/Music` plus `DRUM_AGENT_MUSIC_DIRS`, separated like PATH)
and matches files by their tags (read with ffprobe) or by their names
("Artist - Title.flac", "Artist/Album/03 Title.mp3").

A music folder can be huge, on a slow disk, or hold symlinks that loop, so
the scan is bounded: a cap on files looked at, a cap on tag reads, a time
limit, and every directory visited once (by device and inode). Files are only
read, never moved or modified.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .lookup import Results, artist_key, format_duration, similarity, title_key, version_penalty

AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aiff", ".aif", ".opus"})
MUSIC_DIRS_ENV = "DRUM_AGENT_MUSIC_DIRS"
MAX_FILES = 20_000  # audio files looked at per search
MAX_PROBES = 300  # files whose tags are read (ffprobe is ~30 ms a file)
MAX_SECONDS = 20.0  # for the whole search, scan and tag reads
PROBE_TIMEOUT = 10.0
MIN_SCORE = 0.75  # below this a file is not offered as the song

# File names that say nothing about the song: their tags are read first.
_GENERIC_NAME = re.compile(r"^(?:\d+|track\s*\d+|audio\s*\d*|untitled\s*\d*|unknown.*|rec(?:ording)?\s*\d*)$")
_TRACK_NUMBER = re.compile(r"^\s*(?:\d{1,2}[-.]\s*)?\d{1,3}(?:\s*[-._)]\s*|\s+)")


@dataclass
class LocalMatch:
    path: Path
    title: str | None
    artist: str | None
    duration_s: float | None
    matched_by: str  # "tags" or "file name"
    score: float

    def describe(self) -> str:
        what = " - ".join(x for x in (self.title, self.artist) if x) or self.path.name
        dur = f", {format_duration(self.duration_s)}" if self.duration_s else ""
        return f"your library: {self.path} ({self.matched_by}: {what}{dur})"


def default_roots() -> list[Path]:
    """~/Music plus every folder in DRUM_AGENT_MUSIC_DIRS that exists."""
    roots = [Path("~/Music").expanduser()]
    roots += [Path(p).expanduser() for p in os.environ.get(MUSIC_DIRS_ENV, "").split(os.pathsep) if p.strip()]
    return _existing_unique(roots)


def _existing_unique(roots: list[Path]) -> list[Path]:
    out, seen = [], set()
    for r in roots:
        try:
            r = r.resolve()
            if not r.is_dir() or r in seen:
                continue
        except OSError:
            continue
        seen.add(r)
        out.append(r)
    return out


def iter_audio_files(roots: list[Path], max_files: int, deadline: float, warnings: list[str]) -> Iterator[Path]:
    """Audio files under `roots`, depth first in name order. Follows directory symlinks but
    visits each directory once, so a link back to a parent can't loop; hidden entries are skipped."""
    seen_dirs: set[tuple[int, int]] = set()
    stack = list(reversed(roots))
    count = 0
    while stack:
        d = stack.pop()
        try:
            st = d.stat()
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            continue
        if (st.st_dev, st.st_ino) in seen_dirs:
            continue
        seen_dirs.add((st.st_dev, st.st_ino))
        subdirs = []
        for e in entries:
            if time.monotonic() > deadline:
                warnings.append(f"library scan hit its time limit after {count} audio files; point --library "
                                f"at the right folder")
                return
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    subdirs.append(Path(e.path))
                    continue
                if not e.is_file() or Path(e.name).suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
            except OSError:
                continue
            yield Path(e.path)
            count += 1
            if count >= max_files:
                warnings.append(f"library scan stopped at {max_files} audio files; point --library at the "
                                f"right folder")
                return
        stack.extend(reversed(subdirs))


def probe_tags(path: Path, timeout: float = PROBE_TIMEOUT) -> dict | None:
    """Title, artist and duration from ffprobe, or None if ffprobe is missing or can't read the file.

    Streams are read too: Ogg and Opus keep their tags on the stream, not the container."""
    exe = shutil.which("ffprobe")
    if exe is None:
        return None
    cmd = [exe, "-v", "error", "-hide_banner", "-show_format", "-show_streams", "-of", "json", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        data = json.loads(proc.stdout or b"{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0 or not isinstance(data, dict):
        return None
    tags: dict[str, str] = {}
    for s in data.get("streams") or []:
        tags.update({str(k).lower(): str(v) for k, v in ((s or {}).get("tags") or {}).items()})
    fmt = data.get("format") or {}
    tags.update({str(k).lower(): str(v) for k, v in (fmt.get("tags") or {}).items()})
    try:
        duration = float(fmt.get("duration")) or None
    except (TypeError, ValueError):
        duration = None
    return {"title": tags.get("title") or None,
            "artist": tags.get("artist") or tags.get("album_artist") or tags.get("albumartist") or None,
            "duration_s": duration}


def audio_duration(path: Path) -> float | None:
    """Length in seconds without decoding the audio (ffprobe, else libsndfile's header)."""
    info = probe_tags(Path(path))
    if info and info["duration_s"]:
        return info["duration_s"]
    try:
        import soundfile
        return float(soundfile.info(str(path)).duration) or None
    except Exception:  # noqa: BLE001 (any unreadable file just has no known length)
        return None


def _name_parts(path: Path) -> tuple[str, str | None]:
    """(title, artist) guessed from "03 Artist - Title.mp3", else (stem, parent folder names)."""
    stem = _TRACK_NUMBER.sub("", path.stem.replace("_", " ")).strip() or path.stem
    parts = [p.strip() for p in re.split(r"\s+-\s+", stem) if p.strip()]
    if len(parts) >= 2:
        return parts[-1], parts[0]
    return stem, None


def _score(query: str, artist: str | None, title: str | None, file_artist: str | None,
           folders: tuple[str, ...] = ()) -> float:
    t = max(similarity(query, title), similarity(title_key(query), title_key(title)))
    if not artist:
        return max(t, similarity(query, f"{title} {file_artist or ''}"), similarity(query, f"{file_artist} {title}"))
    names = [n for n in (file_artist, *folders) if n]
    a = max((max(similarity(artist, n), similarity(artist_key(artist), artist_key(n))) for n in names), default=0.0)
    return 0.6 * t + 0.4 * a


def _name_match(query: str, artist: str | None, path: Path) -> LocalMatch:
    title, file_artist = _name_parts(path)
    folders = (path.parent.name, path.parent.parent.name)
    score = _score(query, artist, title, file_artist, folders)
    return LocalMatch(path, title, file_artist, None, "file name", round(score, 3))


def find_local(query: str, artist: str | None = None, roots: list[str | Path] | None = None, *,
               max_files: int = MAX_FILES, max_probes: int = MAX_PROBES, time_limit: float = MAX_SECONDS,
               min_score: float = MIN_SCORE) -> Results:
    """The user's audio files that look like `query` (by `artist`), best first.

    The result is a list of LocalMatch with `.warnings` (a truncated scan, no ffprobe)."""
    deadline = time.monotonic() + time_limit
    warnings: list[str] = []
    if roots is None:
        dirs = default_roots()
    else:
        dirs = _existing_unique([Path(r).expanduser() for r in roots])
        missing = [str(r) for r in roots if not Path(r).expanduser().is_dir()]
        if missing:
            warnings.append("not a folder (skipped): " + ", ".join(missing))
    files = list(dict.fromkeys(p.resolve() for p in iter_audio_files(dirs, max_files, deadline, warnings)))
    by_name = {p: _name_match(query, artist, p) for p in files}

    # Tags settle it, but reading them costs a process per file: files whose name already
    # looks right go first, then files whose name says nothing ("Track 03"), then the rest.
    def priority(p: Path) -> tuple[int, float]:
        generic = bool(_GENERIC_NAME.match(p.stem.strip().lower()))
        return (0 if by_name[p].score >= 0.4 else 1 if generic else 2, -by_name[p].score)

    to_probe = sorted(files, key=priority)[:max_probes]
    if to_probe and shutil.which("ffprobe") is None:
        warnings.append("ffprobe not found: matched by file name only (install ffmpeg to read tags)")
        to_probe = []
    elif len(files) > max_probes:
        warnings.append(f"tags read for {max_probes} of {len(files)} files (the most likely ones)")

    def probe(p: Path) -> tuple[Path, dict | None, bool]:
        late = time.monotonic() > deadline
        return p, (None if late else probe_tags(p)), late

    matches = dict(by_name)
    skipped = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for p, tags, late in pool.map(probe, to_probe):
            skipped += late
            if not tags:
                continue
            m = matches[p]
            m.duration_s = tags["duration_s"]
            if tags["title"]:
                s = round(_score(query, artist, tags["title"], tags["artist"], (p.parent.name,)), 3)
                if s >= m.score:
                    matches[p] = LocalMatch(p, tags["title"], tags["artist"], tags["duration_s"], "tags", s)
    if skipped:
        warnings.append(f"time limit reached: tags of {skipped} file(s) not read")
    # A live take or a remix in the library is still offered, after the plain one (unless asked for).
    asked = f"{query} {artist or ''}"
    good = sorted((m for m in matches.values() if m.score >= min_score),
                  key=lambda m: (-(m.score - version_penalty(m.title, asked)), str(m.path)))
    return Results(good, warnings)
