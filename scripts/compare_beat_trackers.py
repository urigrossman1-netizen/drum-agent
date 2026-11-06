"""Our beat, tempo and meter tracking against Beat This! (CPJKU, MIT), on synthesized charts
whose tempo, meter and bars are known exactly: the ten standard test charts and the library's
odd-meter grooves (g58-g63: 7/8, 5/4, 5/8, 9/8), each drums only and with a band.

Benchmark only; Beat This! is not part of the app (docs/DEVELOPMENT_PROGRESS.md, phase 3).

  pip install beat-this
  # its weights, fetched yourself and loaded from the file (torch.load(weights_only=True)):
  #   https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt
  #   SHA-256 8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331 (77 MB, 2026-11-06)
  python scripts/compare_beat_trackers.py --checkpoint ~/.cache/drum-agent/models/beat-this/final0.ckpt
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
SHA256 = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
STANDARD = ["02", "03", "05", "06", "07", "10", "11", "12", "13", "northbound"]
ODD = ["g58", "g59", "g60", "g61", "g62", "g63"]


def run(job, checkpoint: str):
    chart, band = job
    import eval_notation as EN
    from beat_this.inference import Audio2Beats
    from drum_agent.audio.transcribe import TranscribeOptions, load_audio, transcribe_audio
    from drum_agent.charts import load_any
    from drum_agent.synth import synthesize
    path = EN.find_chart(chart)
    ref = load_any(path)
    with tempfile.TemporaryDirectory() as td:
        y = load_audio(synthesize(ref, Path(td) / "x.wav", method="fluidsynth", accompaniment=band, seed=3))
    ours = transcribe_audio(y, TranscribeOptions(drums_only=not band, separate="auto" if band else "off"))
    beats, downs = Audio2Beats(checkpoint_path=checkpoint, device="cpu")(y, 44100)
    per_bar = Counter(int(np.sum((beats >= a - 0.03) & (beats < b - 0.03))) for a, b in zip(downs, downs[1:]))
    bt_bpm = 60 / float(np.median(np.diff(beats))) if len(beats) > 1 else float("nan")
    return {"chart": path.stem, "input": "band" if band else "drums",
            "truth": f"{ref.measures[min(1, len(ref.measures) - 1)].time_sig} @ {ref.initial_tempo:g}",
            "ours": f"{ours.analysis['meter'].split()[0]} @ {float(ours.analysis['tempo_estimate'].split()[0]):g}",
            "beat_this": f"{per_bar.most_common(1)[0][0] if per_bar else 0} beats/bar @ {bt_bpm:.1f}",
            "bars": f"{len(ref.measures)} / {len(ours.measures)} / {max(0, len(downs) - 1)}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True, help="Beat This! final0.ckpt, downloaded beforehand")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    ckpt = Path(a.checkpoint).expanduser()
    if hashlib.sha256(ckpt.read_bytes()).hexdigest() != SHA256:
        raise SystemExit(f"{ckpt}: not the pinned final0 checkpoint (SHA-256 {SHA256})")
    jobs = [(c, band) for c in STANDARD + ODD for band in (False, True)]
    print(f"{'chart':30} {'input':6} {'truth':12} {'ours':14} {'Beat This!':24} bars: truth / ours / Beat This!")
    with ProcessPoolExecutor(a.jobs) as pool:
        for r in pool.map(partial(run, checkpoint=str(ckpt)), jobs):
            print(f"{r['chart'][:30]:30} {r['input']:6} {r['truth']:12} {r['ours']:14} {r['beat_this']:24} {r['bars']}",
                  flush=True)


if __name__ == "__main__":
    main()
