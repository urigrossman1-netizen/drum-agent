"""Find a song's recording among the user's own audio files, in the personal app.

In the Drum Agent app on the user's own computer, typing a song is enough when the user
has the recording: a purchased download, a CD rip, a bounce of their band. The app looks
in their music folders (`song.local`: ~/Music and the folders in DRUM_AGENT_MUSIC_DIRS,
matched by tags or file names, the scan bounded in files and time), takes the file that
matches best (title and artist; a live take or a remix only after the plain recording),
decodes it into the song's source on the personal-practice basis (the chart says so and is
not shared) and charts it. The user sees which file was used and can pick another one, or
upload a recording.

Only in personal mode (`sources.personal_mode()`: one person, their own computer). A
shared server never reads its own disk for a visitor's song: there the recording is
uploaded. Video sites and streaming services are never a source (`song.fetch`).
"""

from __future__ import annotations

from pathlib import Path

from ..song import local
from ..song.fetch import DURATION_TOLERANCE, FetchError
from ..song.local import AUDIO_EXTENSIONS, LocalMatch
from .sources import add_local, personal_mode
from .store import Store

MAX_CANDIDATES = 8


def folders() -> list[Path]:
    return local.default_roots()


def status() -> dict:
    """Can songs be looked for in the user's music folders here? {"available", "reason", "folders", "detail"}."""
    if not personal_mode():
        return {"available": False, "reason": "shared_server", "folders": [],
                "detail": "This is a shared server: it never looks for songs on its own disk. Upload a recording "
                          "you have the right to transcribe."}
    roots = [str(p) for p in folders()]
    if not roots:
        return {"available": False, "reason": "no_folders", "folders": [],
                "detail": f"No music folder found: ~/Music doesn't exist and {local.MUSIC_DIRS_ENV} names none."}
    return {"available": True, "reason": None, "folders": roots, "detail": "Your music folders: " + ", ".join(roots)}


def candidates(song: dict) -> tuple[list[LocalMatch], list[str]]:
    """The user's files that look like this song, best first, and the scan's warnings."""
    found = local.find_local(song["title"], song["artist"])
    return list(found)[:MAX_CANDIDATES], list(found.warnings)


def public(m: LocalMatch, expected_s: float | None) -> dict:
    off = round(abs(m.duration_s - expected_s) / expected_s, 3) if expected_s and m.duration_s else None
    return {"file": str(m.path), "name": m.path.name, "folder": str(m.path.parent), "title": m.title,
            "artist": m.artist, "duration_s": m.duration_s, "matched_by": m.matched_by, "score": m.score,
            "length_off": off, "length_ok": off is None or off <= DURATION_TOLERANCE}


def chosen(path: str) -> LocalMatch:
    """A file the user picked from the list: an audio file inside one of the music folders."""
    try:
        p = Path(str(path)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise FetchError("that file doesn't exist (any more)") from None
    if not p.is_file() or p.suffix.lower() not in AUDIO_EXTENSIONS:
        raise FetchError("that is not an audio file Drum Agent reads (" + ", ".join(sorted(AUDIO_EXTENSIONS)) + ")")
    if not any(root == p.parent or root in p.parents for root in folders()):
        raise FetchError("that file is not in your music folders")
    return LocalMatch(p, None, None, local.audio_duration(p), "your choice", 1.0)


def fetch_source(store: Store, song: dict, match: LocalMatch) -> dict:
    """Decode the file into the song's source (personal basis); the user's file is only read."""
    return add_local(store, song, match.path, {"file": match.path.name, "folder": str(match.path.parent),
                                               "title": match.title, "artist": match.artist,
                                               "duration_s": match.duration_s, "matched_by": match.matched_by})
