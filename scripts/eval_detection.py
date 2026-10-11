"""Evaluate stroke detection on synthesized audio with known ground truth.

Conditions mix kits used to build the templates (0 Standard, 8 Room) with
held-out sounds (32 Jazz, 40 Brush, the numpy synthesizer), with and without
a bass/keys accompaniment and humanized timing.

Usage: python scripts/eval_detection.py [--cases 03,06] [--conditions std,jazz_band]
Writes a JSON summary to tests/_artifacts/eval_detection.json.
"""

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from drum_agent.audio.detect import DetectOptions, detect  # noqa: E402
from drum_agent.charts import load_any  # noqa: E402
from drum_agent.evaluate import evaluate_events, score_events  # noqa: E402
from drum_agent.synth import synthesize  # noqa: E402

CONDITIONS = {
    # name: (method, kit, accompaniment, humanize_ms, drums_only, held_out)
    "std": ("fluidsynth", 0, False, 0, True, False),
    "room": ("fluidsynth", 8, False, 0, True, False),
    "jazz": ("fluidsynth", 32, False, 0, True, True),
    "brush": ("fluidsynth", 40, False, 0, True, True),
    "numpy": ("numpy", 0, False, 0, True, True),
    "std_band": ("fluidsynth", 0, True, 0, False, False),
    "jazz_band_human": ("fluidsynth", 32, True, 10, False, True),
}
DEFAULT_CASES = ["03_sixteenth_syncopation", "04_simultaneous_hits", "05_hihat_open_closed",
                 "06_tom_fill_barline", "07_ghost_accent_roll", "10_arrangement_tempo"]


def run(cases, conditions, verbose=True):
    results = {}
    pooled = defaultdict(lambda: defaultdict(list))
    with tempfile.TemporaryDirectory() as td:
        for case in cases:
            score = load_any(ROOT / "tests" / "cases" / f"{case}.yaml")
            ref = score_events(score, use_performed=False, audible=True)
            for cond in conditions:
                method, kit, acc, hum, drums_only, held = CONDITIONS[cond]
                wav = Path(td) / f"{case}_{cond}.wav"
                synthesize(score, wav, method=method, kit_program=kit, accompaniment=acc, humanize_ms=hum, seed=3)
                y, sr = sf.read(wav)
                y = y.mean(axis=1) if y.ndim > 1 else y
                det = detect(y, DetectOptions(drums_only=drums_only))
                est = [(h.time, h.inst) for h in det.hits]
                res = evaluate_events(ref, est, 0.05).as_dict()
                results[f"{case}/{cond}"] = res
                for c, s in res["per_class"].items():
                    pooled[cond][c].append(s)
                pooled[cond]["_overall"].append(res["overall"])
                if verbose:
                    o = res["overall"]
                    worst = sorted(((s["F"], c) for c, s in res["per_class"].items() if s["ref"]), key=lambda x: x[0])[:3]
                    print(f"{case:28s} {cond:16s} F={o['F']:.3f} P={o['P']:.3f} R={o['R']:.3f}  worst: "
                          + ", ".join(f"{c} {f:.2f}" for f, c in worst), flush=True)
    summary = {}
    for cond, classes in pooled.items():
        row = {}
        for c, items in classes.items():
            ref = sum(i["ref"] for i in items)
            est = sum(i["est"] for i in items)
            tp = sum(round(i["R"] * i["ref"]) for i in items)
            p = tp / est if est else 0.0
            r = tp / ref if ref else 0.0
            row[c] = {"F": round(2 * p * r / (p + r), 3) if p + r else 0.0, "P": round(p, 3), "R": round(r, 3), "ref": ref}
        summary[cond] = row
    return results, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=",".join(DEFAULT_CASES))
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    a = ap.parse_args()
    cases = [c if c in DEFAULT_CASES or "_" in c else c for c in a.cases.split(",")]
    cases = [next(x for x in DEFAULT_CASES + [p.stem for p in (ROOT / "tests" / "cases").glob("*.yaml")] if x.startswith(c)) for c in cases]
    results, summary = run(cases, a.conditions.split(","))
    print("\nPooled per condition (onset F, 50 ms):")
    classes = sorted({c for row in summary.values() for c in row if c != "_overall"})
    print(f"{'condition':18s} {'overall':>8s} " + " ".join(f"{c[:9]:>9s}" for c in classes))
    for cond, row in summary.items():
        print(f"{cond:18s} {row['_overall']['F']:8.3f} " + " ".join(
            f"{row[c]['F']:9.2f}" if c in row and row[c]['ref'] else f"{'-':>9s}" for c in classes))
    out = ROOT / "tests" / "_artifacts" / "eval_detection.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
