"""Drum sounds for playback in the browser: real sampled drums, rendered once from the
General MIDI soundfont FluidR3_GM (MIT licence) with fluidsynth, using the kit's own
MIDI notes (`drum_agent/kit.py`), and cached as short mono WAV files.

Nothing is downloaded and no audio is committed to the repository: the files are made
on the server the first time they are asked for. Without fluidsynth or the soundfont
the page uses its synthesized kit instead (and says so).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

from ..kit import DEFAULT_KIT

SR = 44100
LONG = {"crash", "crash2", "china", "ride", "ride_bell", "splash", "hihat_open", "hihat_half"}
_lock = threading.Lock()


def soundfont() -> str | None:
    try:
        from ..synth import find_soundfont
        return find_soundfont()
    except (FileNotFoundError, ImportError):
        return None


def available() -> bool:
    return shutil.which("fluidsynth") is not None and soundfont() is not None


def instruments() -> list[dict]:
    """The kit's instruments in staff order (top to bottom), for the grid and the player."""
    out = []
    for inst in sorted(DEFAULT_KIT.instruments, key=lambda i: -i.position):
        out.append({"id": inst.id, "name": inst.name, "midi": inst.midi, "position": inst.position,
                    "family": inst.family, "foot": DEFAULT_KIT.is_foot(inst.id)})
    return out


def sample_path(cache: Path, inst_id: str) -> Path:
    """The WAV for one instrument, rendered on first use."""
    if inst_id not in DEFAULT_KIT:
        raise KeyError(inst_id)
    out = cache / f"{inst_id}.wav"
    if out.is_file():
        return out
    with _lock:
        if out.is_file():
            return out
        if not available():
            raise FileNotFoundError("fluidsynth or the FluidR3_GM soundfont is not installed")
        cache.mkdir(parents=True, exist_ok=True)
        _render(DEFAULT_KIT[inst_id].midi, inst_id in LONG, out)
    return out


def _render(note: int, long: bool, out: Path) -> None:
    import mido
    import soundfile as sf
    seconds = 2.6 if long else 1.1
    with tempfile.TemporaryDirectory() as td:
        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message("note_on", channel=9, note=note, velocity=112, time=0))
        track.append(mido.Message("note_off", channel=9, note=note, velocity=0, time=480))
        track.append(mido.MetaMessage("end_of_track", time=int(480 * 2 * seconds)))
        mpath, wav = Path(td) / "n.mid", Path(td) / "n.wav"
        mid.save(mpath)
        subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.9", "-r", str(SR), "-F", str(wav), soundfont(), str(mpath)],
                       capture_output=True, timeout=60, check=True)
        y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    start = int(np.argmax(np.abs(y) > 1e-3)) if np.any(np.abs(y) > 1e-3) else 0
    y = y[start:start + int(seconds * sr)]
    fade = min(len(y), int(0.08 * sr))
    if fade:
        y[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    peak = float(np.abs(y).max() or 1.0)
    sf.write(str(out), (y / peak * 0.9).astype(np.float32), sr, subtype="PCM_16")
