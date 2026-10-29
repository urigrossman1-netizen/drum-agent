"""End-to-end evaluation: chart -> synthesized audio -> transcription -> notation accuracy.

For each chart and condition, renders audio with FluidSynth (or numpy), runs
the full transcription pipeline and compares the result with the chart:
* onset F (50 ms) and notation F (same bar, same position, same instrument)
* bar count, tempo and meter found

Usage:
  python scripts/eval_notation.py                      # default charts x default conditions
  python scripts/eval_notation.py --charts 06,11,northbound --conditions std_band --jobs 4
  python scripts/eval_notation.py --json out.json
  python scripts/eval_notation.py --library --conditions std_do,jazz_band_h --jobs 4   # all 113 library charts

Charts are names from tests/cases/, tests/audio_cases/ or examples/specs/
(prefix match, e.g. "06" or "northbound"). Results go to stdout and, with
--json, to a file. Conditions:
  std_do      Standard kit, drums only          jazz_do     Jazz kit (held out), drums only
  std_band    Standard kit + bass/keys          jazz_band_h Jazz kit + bass/keys, 8 ms humanize
  room_band   Room kit + bass/keys              brush_do    Brush kit (held out), drums only
"""

import argparse
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONDITIONS = {
    # name: (method, kit, accompaniment, humanize_ms, drums_only)
    "std_do": ("fluidsynth", 0, False, 0, True),
    "jazz_do": ("fluidsynth", 32, False, 0, True),
    "brush_do": ("fluidsynth", 40, False, 0, True),
    "std_band": ("fluidsynth", 0, True, 0, False),
    "room_band": ("fluidsynth", 8, True, 0, False),
    "jazz_band_h": ("fluidsynth", 32, True, 8, False),
}
DEFAULT_CHARTS = ["02", "03", "05", "06", "07", "10", "11", "12", "13", "northbound"]
DEFAULT_CONDITIONS = ["std_do", "jazz_do", "std_band", "jazz_band_h"]
SEARCH = [ROOT / "tests" / "cases", ROOT / "tests" / "audio_cases", ROOT / "examples" / "specs",
          ROOT / "library" / "rudiments", ROOT / "library" / "grooves"]


def library_charts() -> list[str]:
    return [p.stem for d in SEARCH[-2:] for p in sorted(d.glob("*.yaml"))]


def find_chart(name: str) -> Path:
    for d in SEARCH:
        for p in sorted(d.glob("*.yaml")):
            if p.stem.startswith(name) or name in p.stem:
                return p
    raise SystemExit(f"no chart matching {name!r}")


def run_one(chart: str, cond: str, opts: dict) -> dict:
    from drum_agent.audio.transcribe import TranscribeOptions, transcribe_file
    from drum_agent.charts import load_any
    from drum_agent.evaluate import evaluate_scores, notation_accuracy, notation_accuracy_by_class
    from drum_agent.synth import synthesize

    path = find_chart(chart)
    ref = load_any(path)
    method, kit, acc, hum, drums_only = CONDITIONS[cond]
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "x.wav"
        synthesize(ref, wav, method=method, kit_program=kit, accompaniment=acc, humanize_ms=hum, seed=3)
        try:
            est = transcribe_file(wav, TranscribeOptions(drums_only=drums_only, bpm=opts.get("bpm"),
                                                         separate=opts.get("separate", "auto")))
        except Exception as exc:  # report, don't hide
            return {"chart": path.stem, "condition": cond, "error": f"{type(exc).__name__}: {exc}"}
    na = notation_accuracy(ref, est)
    on = evaluate_scores(ref, est).overall
    flagged = {i for i, m in enumerate(est.measures) if m.uncertain}
    ref_keys = {}
    for i, _, h in ref.iter_hits():
        ref_keys.setdefault(i, set()).add((h.pos, h.inst))
    est_keys = {}
    for i, _, h in est.iter_hits():
        est_keys.setdefault(i, set()).add((h.pos, h.inst))
    wrong = {i for i in set(ref_keys) | set(est_keys) if ref_keys.get(i, set()) != est_keys.get(i, set())}
    return {
        "chart": path.stem, "condition": cond,
        "bars": len(est.measures), "ref_bars": len(ref.measures),
        "tempo": est.analysis.get("tempo_estimate"), "meter": est.analysis.get("meter"),
        "onset_F": round(on.f, 4), "notation_F": round(na.f, 4),
        "notation_by_class": {c: round(s.f, 3) for c, s in notation_accuracy_by_class(ref, est).items()},
        "bars_wrong": len(wrong), "bars_flagged": len(flagged),
        "flag_precision": round(len(flagged & wrong) / len(flagged), 3) if flagged else None,
        "flag_recall": round(len(flagged & wrong) / len(wrong), 3) if wrong else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--charts", default=",".join(DEFAULT_CHARTS))
    ap.add_argument("--conditions", default=",".join(DEFAULT_CONDITIONS))
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--bpm", type=float, default=None, help="tempo hint passed to every transcription")
    ap.add_argument("--json", default=None)
    ap.add_argument("--library", action="store_true", help="evaluate every chart in library/ (overrides --charts)")
    ap.add_argument("--separate", default="auto", choices=["auto", "on", "off"],
                    help="drum separation (HTDemucs) for the band conditions: auto = when demucs is installed")
    a = ap.parse_args()
    charts = library_charts() if a.library else a.charts.split(",")
    jobs = [(c, k) for c in charts for k in a.conditions.split(",")]
    for _, k in jobs:
        if k not in CONDITIONS:
            raise SystemExit(f"unknown condition {k}; choose from {', '.join(CONDITIONS)}")
    opts = {"bpm": a.bpm, "separate": a.separate}
    if a.jobs > 1:
        import multiprocessing
        # Fresh worker processes (not forks of this one): a fork of a process whose libraries
        # started threads (OpenMP, BLAS) can die at once ("BrokenProcessPool").
        with ProcessPoolExecutor(a.jobs, mp_context=multiprocessing.get_context("spawn")) as ex:
            results = list(ex.map(run_one, [c for c, _ in jobs], [k for _, k in jobs], [opts] * len(jobs)))
    else:
        results = [run_one(c, k, opts) for c, k in jobs]
    for r in results:
        if "error" in r:
            print(f"{r['chart'][:28]:28s} {r['condition']:11s} ERROR {r['error']}")
            continue
        print(f"{r['chart'][:28]:28s} {r['condition']:11s} bars {r['bars']:3d}/{r['ref_bars']:3d} "
              f"onsetF {r['onset_F']:.3f} notationF {r['notation_F']:.3f} wrong {r['bars_wrong']:3d} "
              f"flagged {r['bars_flagged']:3d}  {r['tempo']}")
    ok = [r for r in results if "error" not in r]
    if ok:
        import statistics
        mean = sum(r["notation_F"] for r in ok) / len(ok)
        print(f"MEAN notation F over {len(ok)} runs: {mean:.4f}  (errors: {len(results) - len(ok)})")
        for cond in dict.fromkeys(r["condition"] for r in ok):
            fs = [r["notation_F"] for r in ok if r["condition"] == cond]
            print(f"  {cond:11s} mean {sum(fs) / len(fs):.3f}  median {statistics.median(fs):.3f}  "
                  f"worst {min(fs):.3f}  >= 0.9: {sum(f >= 0.9 for f in fs)}/{len(fs)}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
