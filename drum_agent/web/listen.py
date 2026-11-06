"""The recording for listening along: compressed, and slowed or sped up with its pitch kept.

The player puts the recording on the same audio clock as the chart's drums, so a section loop
restarts on the sample and the two stay together. That needs a decoded buffer: a media element
can keep the pitch by itself, but it seeks with a gap on every loop and drifts against the
clock. So each speed is a rendition made here: FFmpeg's `atempo` (pitch kept), Opus in Ogg, a
tenth of the size of the WAV. At normal speed it is only compressed.

Renditions are private copies of the recording: served under the same owner checks as the
recording, removed with it, and only the most recently used few are kept per recording.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

SPEEDS = tuple(round(0.5 + 0.05 * k, 2) for k in range(21))  # the practice-speed slider: 50% to 150%
BITRATE = "160k"
KEEP = 6  # renditions kept per recording
TIMEOUT_S = 300
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class ListenError(RuntimeError):
    pass


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def rendition(folder: Path, source: Path, speed: float) -> Path:
    """The Opus rendition of `source` at `speed` in `folder`, made on first use."""
    if speed not in SPEEDS:
        raise ValueError(f"speed must be one of {SPEEDS[0]}..{SPEEDS[-1]} in steps of 0.05")
    out = folder / f"{round(speed * 100):03d}.ogg"
    with _lock(str(out)):
        if out.is_file():
            os.utime(out)  # most recently used
            return out
        exe = shutil.which("ffmpeg")
        if exe is None:
            raise ListenError("ffmpeg is not installed on this server")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        cmd = [exe, "-v", "error", "-y", "-i", str(source), "-map", "0:a:0"]
        if speed != 1:
            cmd += ["-filter:a", f"atempo={speed:g}"]
        cmd += ["-c:a", "libopus", "-b:a", BITRATE, "-f", "ogg", str(tmp)]
        try:
            run = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            tmp.unlink(missing_ok=True)
            raise ListenError(f"preparing the recording took longer than {TIMEOUT_S} s") from None
        if run.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise ListenError(f"ffmpeg could not prepare the recording: {run.stderr.decode(errors='replace')[-200:]}")
        tmp.replace(out)
        _prune(folder, keep=out)
    return out


def _prune(folder: Path, keep: Path) -> None:
    done = sorted(folder.glob("*.ogg"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in [p for p in done if p != keep][KEEP - 1:]:
        old.unlink(missing_ok=True)
