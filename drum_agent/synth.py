"""Render a Score to audio, for test fixtures and accuracy evaluation.

Two independent sound sources, so accuracy is never measured only on the
sounds the detector's templates came from:

* "fluidsynth": the GM soundfont FluidR3_GM (several drum kits: 0 Standard,
  8 Room, 16 Power, 24 Electronic, 25 TR-808, 32 Jazz, 40 Brush), optionally
  with a synthetic bass/keys accompaniment to emulate a band mix.
* "numpy": a small physical-ish drum synthesizer with different timbres.

The returned audio's ground truth is the Score itself (`Score.event_list()`
plus the tempo map), which is what makes end-to-end accuracy measurable.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

from .export.midi import CHANNEL, TICKS_PER_BEAT, build_midi
from .kit import DEFAULT_KIT
from .model import Score

SOUNDFONTS = ("/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2")
SR = 44100


def find_soundfont() -> str:
    for p in SOUNDFONTS:
        if Path(p).exists():
            return p
    raise FileNotFoundError("FluidR3_GM.sf2 not found (apt-get install fluid-soundfont-gm)")


def _humanize_midi(mid: mido.MidiFile, humanize_ms: float, seed: int, tempo_bpm: float) -> None:
    if humanize_ms <= 0:
        return
    rng = random.Random(seed)
    ticks_per_ms = TICKS_PER_BEAT * tempo_bpm / 60000.0
    for track in mid.tracks:
        tick, absolute = 0, []
        for msg in track:
            tick += msg.time
            absolute.append([tick, msg])
        for item in absolute:
            msg = item[1]
            if msg.type == "note_on" and msg.velocity > 0:
                item[0] = max(0, int(item[0] + rng.gauss(0, humanize_ms) * ticks_per_ms))
                item[1] = msg.copy(velocity=max(1, min(127, int(msg.velocity * rng.uniform(0.85, 1.1)))))
        absolute.sort(key=lambda x: x[0])
        track.clear()
        prev = 0
        for t, msg in absolute:
            track.append(msg.copy(time=t - prev))
            prev = t


def _accompaniment(score: Score, seed: int) -> mido.MidiTrack:
    """Bass on roots in 8ths and sustained keyboard chords, one chord per bar."""
    rng = random.Random(seed)
    roots = [40, 45, 43, 38, 41, 36]  # E A G D F C (bass register)
    track = mido.MidiTrack()
    track.append(mido.Message("program_change", channel=0, program=33, time=0))  # fingered bass
    track.append(mido.Message("program_change", channel=1, program=4, time=0))  # electric piano
    events = []
    pos = Fraction(0)
    for i, m in enumerate(score.measures):
        root = roots[(i // 2) % len(roots)] if rng.random() < 0.9 else roots[rng.randrange(len(roots))]
        start = int(pos * 4 * TICKS_PER_BEAT)
        length = int(m.actual_length * 4 * TICKS_PER_BEAT)
        step = TICKS_PER_BEAT // 2
        for t in range(start, start + length, step):
            events.append((t, mido.Message("note_on", channel=0, note=root, velocity=85)))
            events.append((t + step - 30, mido.Message("note_off", channel=0, note=root, velocity=0)))
        chord = [root + 24, root + 28, root + 31]
        for n in chord:
            events.append((start, mido.Message("note_on", channel=1, note=n, velocity=60)))
            events.append((start + length - 40, mido.Message("note_off", channel=1, note=n, velocity=0)))
        pos += m.actual_length
    events.sort(key=lambda e: (e[0], e[1].type == "note_on"))
    prev = 0
    for t, msg in events:
        track.append(msg.copy(time=t - prev))
        prev = t
    return track


def synthesize(score: Score, out: str | Path, method: str = "fluidsynth", kit_program: int = 0,
               accompaniment: bool = False, humanize_ms: float = 0.0, seed: int = 0,
               gain: float = 0.7) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if method == "numpy":
        audio = numpy_drums(score, humanize_ms=humanize_ms, seed=seed)
        sf.write(out, audio, SR)
        return out
    if shutil.which("fluidsynth") is None:
        raise RuntimeError("fluidsynth is not installed")
    mid = build_midi(score)
    drums = mid.tracks[1]
    drums.insert(1, mido.Message("program_change", channel=CHANNEL, program=kit_program, time=0))
    if accompaniment:
        mid.tracks.append(_accompaniment(score, seed))
    _humanize_midi(mid, humanize_ms, seed, score.initial_tempo)
    with tempfile.TemporaryDirectory() as td:
        mpath = Path(td) / "in.mid"
        mid.save(str(mpath))
        cmd = ["fluidsynth", "-ni", "-q", "-g", str(gain), "-r", str(SR), "-F", str(out), find_soundfont(), str(mpath)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=600)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"fluidsynth failed: {proc.stderr[-500:]}")
    return out


# ---------------------------------------------------------------------------
# A tiny drum synthesizer (different timbres from the soundfont)
# ---------------------------------------------------------------------------

def _env(n: int, decay_s: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.exp(-t / decay_s)


def _bandnoise(n: int, lo: float, hi: float, rng: np.random.Generator) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    sos = butter(4, [lo, min(hi, SR / 2 - 100)], btype="bandpass", fs=SR, output="sos")
    return sosfilt(sos, rng.standard_normal(n))


def _voice(inst: str, vel: float, rng: np.random.Generator) -> np.ndarray:
    """Physically plausible drum sounds that differ from the soundfont's samples.

    (An earlier version made the snare from high-passed noise; its spectrum
    peaked at 16 kHz like a cymbal, which made it an unfair test. Real snares
    centre around 2-4 kHz with a body near 200 Hz.)
    """
    t_of = lambda n: np.arange(n) / SR  # noqa: E731
    if inst in ("kick", "kick2"):
        n = int(0.45 * SR)
        t = t_of(n)
        f = 48 + 100 * np.exp(-t / 0.03)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.18)
        click = _bandnoise(n, 1500, 6000, rng) * _env(n, 0.006) * 0.5
        sig = body + click
    elif inst in ("snare", "rimshot"):
        n = int(0.4 * SR)
        t = t_of(n)
        body = (np.sin(2 * np.pi * 185 * t) + 0.6 * np.sin(2 * np.pi * 330 * t)) * _env(n, 0.06)
        wires = _bandnoise(n, 1200, 8000, rng) * _env(n, 0.14)
        sig = 0.8 * body + 1.1 * wires / (np.abs(wires).max() + 1e-9)
    elif inst == "cross_stick":
        n = int(0.1 * SR)
        t = t_of(n)
        sig = np.sin(2 * np.pi * 950 * t) * _env(n, 0.015) + 0.3 * _bandnoise(n, 2000, 6000, rng) * _env(n, 0.006)
    elif inst in ("tom1", "tom2", "floor_tom", "floor_tom2"):
        f0 = {"tom1": 190, "tom2": 140, "floor_tom": 95, "floor_tom2": 80}[inst]
        n = int(0.7 * SR)
        t = t_of(n)
        f = f0 * (1 + 0.25 * np.exp(-t / 0.06))
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(2 * np.pi * np.cumsum(1.6 * f) / SR)
        attack = _bandnoise(n, 400, 3000, rng) * _env(n, 0.01)
        sig = body * _env(n, 0.3) + 0.4 * attack / (np.abs(attack).max() + 1e-9)
    elif inst in ("hihat", "hihat_open", "hihat_half", "hihat_pedal", "hihat_splash"):
        decay = {"hihat": 0.035, "hihat_pedal": 0.025, "hihat_open": 0.32, "hihat_half": 0.14, "hihat_splash": 0.2}[inst]
        n = int(min(2.0, decay * 6 + 0.05) * SR)
        t = t_of(n)
        noise = _bandnoise(n, 6500, 15000, rng)
        metal = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (6870, 8130, 9450, 11200)) * 0.15
        sig = (noise / (np.abs(noise).max() + 1e-9) + metal) * _env(n, decay)
        if inst == "hihat_pedal":
            sig *= 0.5
    elif inst in ("ride", "ride_bell"):
        n = int(2.5 * SR)
        t = t_of(n)
        wash = _bandnoise(n, 3500, 12000, rng) * _env(n, 0.9)
        ping = _bandnoise(n, 2500, 6000, rng) * _env(n, 0.02)
        bell = sum(np.sin(2 * np.pi * f * t) for f in (2350, 3480, 5010)) * _env(n, 0.6)
        bell_gain = 1.2 if inst == "ride_bell" else 0.25
        sig = 0.6 * wash / (np.abs(wash).max() + 1e-9) + 0.5 * ping / (np.abs(ping).max() + 1e-9) + bell_gain * bell / 3
    elif inst in ("crash", "crash2", "china", "splash"):
        decay = {"crash": 1.6, "crash2": 1.3, "china": 1.0, "splash": 0.5}[inst]
        n = int(min(3.0, decay * 2.5) * SR)
        noise = _bandnoise(n, 1800, 14000, rng)
        sig = noise / (np.abs(noise).max() + 1e-9) * _env(n, decay) * 1.3
    else:
        n = int(0.2 * SR)
        sig = rng.standard_normal(n) * _env(n, 0.05)
    sig = sig / (np.max(np.abs(sig)) + 1e-9)
    return sig * vel


def numpy_drums(score: Score, humanize_ms: float = 0.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    starts = score.measure_start_seconds()
    total = starts[-1] + float(score.measures[-1].actual_length) * 4 * 60 / score.tempo_at(len(score.measures) - 1) + 3
    out = np.zeros(int(total * SR) + SR)
    for i, m, h in score.iter_hits():
        tempo = score.tempo_at(i)
        t = starts[i] + float(h.pos) * 4 * 60 / tempo + (rng.normal(0, humanize_ms) / 1000 if humanize_ms else 0)
        vel = 0.3 if h.ghost else (1.0 if h.accent else 0.7)
        sig = _voice(h.inst, vel * rng.uniform(0.9, 1.05), rng)
        k = max(0, int(t * SR))
        seg = out[k:k + len(sig)]
        seg += sig[:len(seg)]
    peak = np.max(np.abs(out)) + 1e-9
    return (out / peak * 0.8).astype(np.float32)
