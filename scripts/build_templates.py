"""Build drum spectral templates from the FluidR3 GM soundfont.

Renders isolated hits of each instrument class from three drum kits
(0 Standard, 8 Room, 16 Power, 24 Electronic, 25 TR-808) at three velocities, and stores the mean
early-decay spectrum per (class, kit). The Jazz (32) and Brush (40) kits and
the numpy synthesizer are kept out so accuracy evaluation uses unseen sounds.

Usage: python scripts/build_templates.py  ->  drum_agent/data/templates.npz
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drum_agent.audio.features import HOP, SR, band_spectrogram, stack_frames  # noqa: E402
from drum_agent.audio.templates import CLASS_NOTES  # noqa: E402
from drum_agent.synth import find_soundfont  # noqa: E402

KITS = tuple(int(k) for k in __import__("os").environ.get("TEMPLATE_KITS", "0,8,16,24,25").split(","))
VELOCITIES = (60, 95, 125)
SPACING = 2.0  # seconds between hits


def render_kit(program: int, notes: list[int]) -> np.ndarray:
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))  # 120 BPM: 1 beat = 0.5 s
    tr.append(mido.Message("program_change", channel=9, program=program, time=0))
    gap = int(SPACING / 0.5 * 480)
    first = True
    for n in notes:
        for v in VELOCITIES:
            tr.append(mido.Message("note_on", channel=9, note=n, velocity=v, time=0 if first else gap - 10))
            tr.append(mido.Message("note_off", channel=9, note=n, velocity=0, time=10))
            first = False
    with tempfile.TemporaryDirectory() as td:
        mp, wp = Path(td) / "k.mid", Path(td) / "k.wav"
        mid.save(str(mp))
        subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.7", "-r", str(SR), "-F", str(wp), find_soundfont(), str(mp)],
                       check=True, capture_output=True)
        y, sr = sf.read(wp)
    return y.mean(axis=1) if y.ndim > 1 else y


def main() -> None:
    classes = list(CLASS_NOTES)
    templates, labels, kits, decays = [], [], [], []
    for program in KITS:
        notes = [n for c in classes for n in CLASS_NOTES[c]]
        y = render_kit(program, notes)
        S = band_spectrogram(y.astype(np.float32))
        St = stack_frames(S)
        k = 0
        for c in classes:
            for n in CLASS_NOTES[c]:
                specs = []
                for v in VELOCITIES:
                    start = int(round(k * SPACING * SR / HOP))
                    seg = S[:, start:start + int(0.5 * SR / HOP)]
                    if seg.sum() <= 1e-6:
                        k += 1
                        continue
                    peak = int(np.argmax(seg.sum(axis=0)[:20]))
                    early = St[:, start + peak:start + peak + 2].mean(axis=1)  # stacked onset frame
                    specs.append(early / (early.sum() + 1e-9))
                    env = seg.sum(axis=0)
                    env = env / (env.max() + 1e-9)
                    below = np.nonzero(env[peak:] < 0.25)[0]
                    decays.append((c, program, (below[0] if len(below) else len(env)) * HOP / SR))
                    k += 1
                if specs:
                    templates.append(np.mean(specs, axis=0))
                    labels.append(c)
                    kits.append(program)
    W = np.array(templates, dtype=np.float32).T  # bands x templates
    out = ROOT / "drum_agent" / "data" / "templates.npz"
    np.savez_compressed(out, W=W, labels=np.array(labels), kits=np.array(kits))
    print(f"wrote {out}: {W.shape[1]} templates for {len(set(labels))} classes from kits {KITS}")
    by = {}
    for c, p, d in decays:
        by.setdefault(c, []).append(d)
    for c, ds in by.items():
        print(f"  {c:12s} decay to 25%: median {np.median(ds) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
