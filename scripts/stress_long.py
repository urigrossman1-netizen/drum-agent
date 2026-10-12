"""Stress test: a long band recording through the whole pipeline.

Builds an ~8.5-minute song (the Northbound example three times, so it has three
2/4 bars), synthesizes it with bass and keys, transcribes and engraves it, and
reports time, peak memory, the checks and the accuracy against the chart.

Usage: python scripts/stress_long.py [--copies 3] [--out DIR]
"""

import argparse
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copies", type=int, default=3)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out or tempfile.mkdtemp(prefix="drum_stress_"))
    out.mkdir(parents=True, exist_ok=True)
    spec = yaml.safe_load((ROOT / "examples/specs/03_full_song_northbound.yaml").read_text())
    secs = spec["sections"]
    spec["title"] = f"Northbound x{a.copies}"
    spec["sections"] = []
    for c in range(a.copies):
        copy = [dict(s, label=s["label"] + (f" ({c + 1})" if c else "")) for s in secs]
        copy[0]["time"] = "4/4"  # the previous copy ended after a 2/4 bar
        spec["sections"] += copy
    chart = out / "long.yaml"
    chart.write_text(yaml.safe_dump(spec))
    run = [sys.executable, "-m", "drum_agent"]
    subprocess.run(run + ["synth", str(chart), "-o", str(out / "long.wav"), "--accompaniment"], check=True, cwd=ROOT)
    t = time.time()
    p = subprocess.run(run + ["transcribe", str(out / "long.wav"), "--rights", "original", "-o", str(out / "chart")],
                       capture_output=True, text=True, cwd=ROOT)
    secs_taken = time.time() - t
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    print(f"transcribe + engrave: exit {p.returncode}, {secs_taken:.0f} s, peak memory {peak:.0f} MB")
    print("\n".join(line for line in p.stdout.splitlines() if "check:" in line))
    if p.returncode:
        print(p.stderr[-2000:])
        raise SystemExit(1)
    ev = subprocess.run(run + ["evaluate", str(chart), str(out / "chart" / "long.json")],
                        capture_output=True, text=True, cwd=ROOT)
    print("\n".join(line for line in ev.stdout.splitlines() if line.startswith(("Onset", "Notation", "  note"))))
    print(f"files in {out}")


if __name__ == "__main__":
    main()
