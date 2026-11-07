"""Evaluate stroke detection on real recordings: the MDB Drums dataset.

MDB Drums (Southall et al., ISMIR 2017) is 23 MedleyDB tracks with every
drum stroke annotated, each as an isolated drum mix and as the full band mix.
Unlike the synthesized fixtures of eval_detection.py these are real kits in
real rooms, played by real drummers, so this is the honest accuracy number.

The audio is CC BY-NC-SA 4.0: it is downloaded to a local cache, never into
the repository. Tune on the MIREX 2017 training half (--split train) and
report the test half (--split test), so the reported number is held out.

Usage:
  python scripts/eval_real.py --download            # once, about 330 MB (92 files)
  python scripts/eval_real.py --split train --jobs 4
  python scripts/eval_real.py --split test --mix both
  python scripts/eval_real.py --split train --mix both --separate   # also "sep": the band mix,
      drums separated with HTDemucs first (needs `pip install demucs`; drum_agent/audio/separate.py)
  python scripts/eval_real.py --split train --pipeline transcribe   # the finished chart's notes,
      not the detector's strokes (what the user gets)
  python scripts/eval_real.py --split train --detector nmf --label nmf-baseline

Reported, per class (MDB's KD, SD, HH, TT, CY) and pooled: precision, recall and F at 50 ms
(MIREX) and at 30 ms, the mean |timing error| of the matched strokes, recall on fast
passages (strokes at most 100 ms apart on one drum), and a confusion matrix: for the strokes
not found on their own class, what was written instead within 50 ms ("missed" when nothing).
Writes tests/_artifacts/eval_real_<split>.json and, to keep the history,
benchmarks/results/<date>_<label>.json (+ .md): the numbers with the commit, detector and
machine they came from. Only numbers are written there, never audio or annotations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "https://raw.githubusercontent.com/CarlSouthall/MDBDrums/master/MDB%20Drums"
CACHE = Path(os.environ.get("DRUM_AGENT_DATA", Path.home() / ".cache" / "drum-agent")) / "mdb-drums"

# MIREX 2017 drum transcription splits (MIREX2017.md in the dataset repository).
TRAIN = ["80sRock", "BebopJazz", "Britpop", "CoolJazz", "Disco", "FunkJazz", "FusionJazz", "Reggae",
         "Rock", "Rockabilly", "Shadows", "Zeppelin"]  # MIREX2017.md spells it "Zepplin"
TEST = ["Beatles", "Country1", "FreeJazz", "Gospel", "Grunge", "Hendrix", "LatinJazz", "ModalJazz",
        "Punk", "SpeedMetal", "SwingJazz"]

# MDB class labels: KD kick, SD snare, HH hi-hat, TT toms, CY cymbals (ride and crash), OT other.
OURS_TO_MDB = {
    "kick": "KD", "kick2": "KD",
    "snare": "SD", "rimshot": "SD", "cross_stick": "SD",
    "hihat": "HH", "hihat_open": "HH", "hihat_half": "HH", "hihat_pedal": "HH", "hihat_splash": "HH",
    "tom1": "TT", "tom2": "TT", "floor_tom": "TT", "floor_tom2": "TT",
    "ride": "CY", "ride_bell": "CY", "crash": "CY", "crash2": "CY", "china": "CY", "splash": "CY",
}
CLASSES = ["KD", "SD", "HH", "TT", "CY"]
TOL = 0.05  # seconds, the MIREX tolerance
TOL_STRICT = 0.03
FAST = 0.100  # a stroke this close to the next or previous one on the same class is in a fast passage
RESULTS = ROOT / "benchmarks" / "results"


def _paths(track: str) -> dict[str, Path]:
    name = f"MusicDelta_{track}"
    return {
        "drums": CACHE / "drum_only" / f"{name}_Drum.wav",
        "mix": CACHE / "full_mix" / f"{name}_MIX.wav",
        "class": CACHE / "class" / f"{name}_class.txt",
        "subclass": CACHE / "subclass" / f"{name}_subclass.txt",
    }


def _remote(track: str) -> dict[str, str]:
    name = f"MusicDelta_{track}"
    return {
        "drums": f"{BASE}/audio/drum_only/{name}_Drum.wav",
        "mix": f"{BASE}/audio/full_mix/{name}_MIX.wav",
        "class": f"{BASE}/annotations/class/{name}_class.txt",
        "subclass": f"{BASE}/annotations/subclass/{name}_subclass.txt",
    }


def download() -> None:
    print(f"MDB Drums (CC BY-NC-SA 4.0) -> {CACHE}")
    for track in TRAIN + TEST:
        local, remote = _paths(track), _remote(track)
        for key in ("class", "subclass", "drums", "mix"):
            dest = local[key]
            if dest.exists() and dest.stat().st_size > 0:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = remote[key]
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(url, timeout=120) as r:
                        data = r.read()
                    break
                except OSError as exc:
                    if attempt == 3:
                        raise SystemExit(f"download failed: {urllib.parse.unquote(url)}: {exc}")
                    time.sleep(2 ** (attempt + 1))
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
        print(f"  {track}")


def read_annotations(path: Path) -> list[tuple[float, str]]:
    out = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out.append((float(parts[0]), parts[1]))
    return out


def _f(tp: int, ref: int, est: int) -> tuple[float, float, float]:
    p = tp / est if est else (1.0 if not ref else 0.0)
    r = tp / ref if ref else (1.0 if not est else 0.0)
    return (2 * p * r / (p + r) if p + r else 0.0), p, r


def _match(r: list[float], e: list[float], tol: float) -> list[tuple[int, int]]:
    import numpy as np
    import mir_eval
    return mir_eval.util.match_events(np.array(r), np.array(e), tol) if r and e else []


def score_track(ref: list[tuple[float, str]], est: list[tuple[float, str]]) -> dict[str, dict]:
    """Per MDB class (OT, "other" percussion, is not scored): tp/ref/est at 50 ms and tp30 at
    30 ms, the summed timing error of the 50 ms matches (err_ms), and the fast-passage strokes
    (ref_fast) with how many were found (tp_fast). Under "confusion": for each class, the
    strokes it had no match for, by what was written instead within 50 ms, or "missed"; and
    "extra": strokes written where the recording has nothing within 50 ms, by class."""
    out: dict[str, dict] = {}
    left_r: list[tuple[float, str]] = []  # unmatched within their own class
    left_e: list[tuple[float, str]] = []
    for c in CLASSES:
        r = sorted(t for t, k in ref if k == c)
        e = sorted(t for t, k in est if k == c)
        pairs = _match(r, e, TOL)
        fast = {i for i in range(len(r)) if (i > 0 and r[i] - r[i - 1] <= FAST)
                or (i + 1 < len(r) and r[i + 1] - r[i] <= FAST)}
        found = {i for i, _ in pairs}
        out[c] = {"tp": len(pairs), "ref": len(r), "est": len(e), "tp30": len(_match(r, e, TOL_STRICT)),
                  "err_ms": round(sum(abs(e[j] - r[i]) for i, j in pairs) * 1000, 3),
                  "ref_fast": len(fast), "tp_fast": len(fast & found)}
        used_e = {j for _, j in pairs}
        left_r += [(r[i], c) for i in range(len(r)) if i not in found]
        left_e += [(e[j], c) for j in range(len(e)) if j not in used_e]
    # What took the place of each unmatched stroke: the nearest unmatched stroke of another
    # class within 50 ms (one-to-one, by time).
    left_r.sort()
    left_e.sort()
    pairs = _match([t for t, _ in left_r], [t for t, _ in left_e], TOL)
    confusion = {c: {} for c in CLASSES}
    hit_r, hit_e = set(), set()
    for i, j in pairs:
        rc, ec = left_r[i][1], left_e[j][1]
        confusion[rc][ec] = confusion[rc].get(ec, 0) + 1
        hit_r.add(i)
        hit_e.add(j)
    for i, (_, rc) in enumerate(left_r):
        if i not in hit_r:
            confusion[rc]["missed"] = confusion[rc].get("missed", 0) + 1
    extra = {c: 0 for c in CLASSES}
    for j, (_, ec) in enumerate(left_e):
        if j not in hit_e:
            extra[ec] += 1
    out["confusion"] = confusion
    out["extra"] = extra
    return out


def run_one(job: tuple[str, str, str, str]) -> tuple[str, str, dict, float]:
    track, mix, pipeline, detector = job
    import soundfile as sf
    from drum_agent.audio.detect import DetectOptions, detect
    p = _paths(track)
    y, sr = sf.read(p["mix" if mix == "sep" else mix], dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if sr != 44100:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=44100)
    t0 = time.time()
    if mix == "sep":  # the band mix, with the drums pulled out first (cached: separation is slow)
        import numpy as np
        stem = CACHE / "separated" / f"{track}_{_separator()}.npy"
        if stem.is_file():
            y = np.load(stem)
        else:
            from drum_agent.audio.separate import separate_drums
            y = separate_drums(y, 44100)
            stem.parent.mkdir(parents=True, exist_ok=True)
            np.save(stem, y)
    drums_only = mix in ("drums", "sep")
    if pipeline == "detect":
        det = detect(y, DetectOptions(drums_only=drums_only, method=detector))
        est = [(h.time, OURS_TO_MDB.get(h.inst, "OT")) for h in det.hits]
    else:
        from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio
        # separate="off": "mix" is the band mix as given, and "sep" was separated above (the
        # transcriber would otherwise separate "mix" itself whenever demucs is installed).
        score = transcribe_audio(y, TranscribeOptions(drums_only=drums_only, detector=detector, separate="off"))
        est = [(h.time, OURS_TO_MDB.get(h.inst, "OT")) for _, _, h in score.iter_hits() if h.time is not None]
    ref = read_annotations(p["class"])
    return track, mix, score_track(ref, est), time.time() - t0


def _separator() -> str:
    from drum_agent.audio.separate import MODEL
    return MODEL


COUNTS = ("tp", "ref", "est", "err_ms", "tp30", "ref_fast", "tp_fast")


def _cell(acc: dict) -> dict:
    f, p, r = _f(acc["tp"], acc["ref"], acc["est"])
    f30 = _f(acc["tp30"], acc["ref"], acc["est"])[0]
    return {"F": round(f, 3), "P": round(p, 3), "R": round(r, 3), "F30": round(f30, 3), **acc,
            "timing_ms": round(acc["err_ms"] / acc["tp"], 1) if acc["tp"] else None,
            "R_fast": round(acc["tp_fast"] / acc["ref_fast"], 3) if acc["ref_fast"] else None}


def summarize(rows: dict[tuple[str, str], dict]) -> dict:
    pooled: dict[str, dict] = {}
    for mix in sorted({m for _, m in rows}):
        acc = defaultdict(lambda: dict.fromkeys(COUNTS, 0))
        confusion = {c: defaultdict(int) for c in CLASSES}
        extra = defaultdict(int)
        for (track, m), res in rows.items():
            if m != mix:
                continue
            for c in CLASSES:
                for k in COUNTS:
                    acc[c][k] += res[c].get(k, 0)
                for other, n in res.get("confusion", {}).get(c, {}).items():
                    confusion[c][other] += n
                extra[c] += res.get("extra", {}).get(c, 0)
        table = {c: _cell(acc[c]) for c in CLASSES}
        for name, group in (("KD/SD/HH", CLASSES[:3]), ("all 5", CLASSES)):
            table[name] = _cell({k: sum(acc[c][k] for c in group) for k in COUNTS})
        table["confusion"] = {c: dict(sorted(v.items())) for c, v in confusion.items()}
        table["extra"] = dict(extra)
        # Mean of per-track F (the MIREX convention) for the three main classes.
        per_track = []
        for (track, m), res in rows.items():
            if m == mix:
                tp = sum(res[c]["tp"] for c in CLASSES[:3])
                ref = sum(res[c]["ref"] for c in CLASSES[:3])
                est = sum(res[c]["est"] for c in CLASSES[:3])
                per_track.append(_f(tp, ref, est)[0])
        table["mean track F (KD/SD/HH)"] = round(sum(per_track) / len(per_track), 3) if per_track else 0.0
        pooled[mix] = table
    return pooled


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true", help="fetch the dataset into the cache and exit")
    ap.add_argument("--split", default="train", choices=["train", "test", "all"])
    ap.add_argument("--mix", default="both", choices=["drums", "mix", "both"])
    ap.add_argument("--tracks", help="comma list of track names (overrides --split), e.g. Rock,Punk")
    ap.add_argument("--pipeline", default="detect", choices=["detect", "transcribe"],
                    help="score the detector's strokes, or the strokes left in the finished score")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--separate", action="store_true",
                    help="also score 'sep': the band mix with the drums separated by HTDemucs first")
    ap.add_argument("--detector", default="auto", choices=["auto", "classifier", "nmf"],
                    help="which detector (auto: the onset classifier when its weights are installed)")
    ap.add_argument("--label", help="name of this run in benchmarks/results (default: split, pipeline, detector)")
    ap.add_argument("--no-save", action="store_true", help="don't write benchmarks/results")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.download:
        download()
        return
    tracks = a.tracks.split(",") if a.tracks else {"train": TRAIN, "test": TEST, "all": TRAIN + TEST}[a.split]
    missing = [t for t in tracks if not _paths(t)["class"].exists()]
    if missing:
        raise SystemExit(f"dataset not in {CACHE} ({', '.join(missing[:3])}...): run with --download first")
    mixes = ["drums", "mix"] if a.mix == "both" else [a.mix]
    if a.separate:
        from drum_agent.audio.separate import available
        if not available():
            raise SystemExit("--separate needs the demucs package: pip install demucs")
        mixes.append("sep")
    jobs = [(t, m, a.pipeline, a.detector) for t in tracks for m in mixes]
    rows: dict[tuple[str, str], dict] = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for track, mix, res, secs in ex.map(run_one, jobs):
            rows[(track, mix)] = res
            if not a.quiet:
                cells = []
                for c in CLASSES:
                    s = res[c]
                    cells.append(f"{c} {_f(s['tp'], s['ref'], s['est'])[0]:.2f}" if s["ref"] or s["est"] else f"{c}  -  ")
                print(f"{track:12s} {mix:5s} " + "  ".join(cells) + f"  ({secs:.0f}s)", flush=True)
    summary = summarize(rows)
    elapsed = time.time() - t0
    report = render(summary, f"MDB Drums, {a.split if not a.tracks else a.tracks}, pipeline={a.pipeline}, "
                             f"detector={a.detector} ({elapsed:.0f}s)")
    print("\n" + report)
    out = ROOT / "tests" / "_artifacts" / f"eval_real_{a.split if not a.tracks else 'custom'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"summary": summary, "pipeline": a.pipeline, "detector": a.detector, "split": a.split,
              "tracks": {f"{t}/{m}": r for (t, m), r in rows.items()}, "meta": _meta(a, tracks, elapsed)}
    out.write_text(json.dumps(result, indent=1))
    print(f"wrote {out}")
    if not a.no_save:
        RESULTS.mkdir(parents=True, exist_ok=True)
        label = a.label or f"{a.split if not a.tracks else 'custom'}_{a.pipeline}_{a.detector}"
        stem = RESULTS / f"{time.strftime('%Y-%m-%d')}_{_slug(label)}"
        stem.with_suffix(".json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        stem.with_suffix(".md").write_text(f"# {label}\n\n```\n{report}\n```\n\n{_meta_md(result['meta'])}\n",
                                           encoding="utf-8")
        print(f"wrote {stem}.json and .md")


def render(summary: dict, title: str) -> str:
    """The tables, as printed and as kept in benchmarks/results/*.md."""
    lines = [f"{title}: onset F at 50 ms"]
    lines.append(f"{'':6s} " + " ".join(f"{c:>6s}" for c in CLASSES) + f" {'KD/SD/HH':>9s} {'all 5':>6s} "
                 f"{'F@30ms':>7s} {'track-mean':>10s}")
    for mix, t in summary.items():
        lines.append(f"{mix:6s} " + " ".join(f"{t[c]['F']:6.3f}" for c in CLASSES)
                     + f" {t['KD/SD/HH']['F']:9.3f} {t['all 5']['F']:6.3f} {t['all 5']['F30']:7.3f}"
                     + f" {t['mean track F (KD/SD/HH)']:10.3f}")
    lines.append("\nAll 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the "
                 "matched ones, recall in fast passages (<= 100 ms apart on one drum):")
    for mix, t in summary.items():
        t5 = t["all 5"]
        lines.append(f"{mix:6s} P {t5['P']:.3f}  R {t5['R']:.3f}  missed {t5['ref'] - t5['tp']:5d} of "
                     f"{t5['ref']:5d}  extra {t5['est'] - t5['tp']:5d}  timing {t5['timing_ms']} ms  "
                     f"fast-passage R {t5['R_fast']}")
    lines.append("\nStrokes not found on their own class: what was written instead within 50 ms "
                 "(rows: the recording; 'missed': nothing), and strokes written where there was none:")
    for mix, t in summary.items():
        lines.append(f"{mix}:")
        cols = CLASSES + ["missed"]
        lines.append(f"  {'':4s}" + "".join(f"{c:>8s}" for c in cols))
        for c in CLASSES:
            row = t["confusion"].get(c, {})
            lines.append(f"  {c:4s}" + "".join(f"{row.get(o, 0) or '.':>8}" for o in cols))
        lines.append("  extra " + "  ".join(f"{c} {t['extra'].get(c, 0)}" for c in CLASSES))
    return "\n".join(lines)


def _git_exe() -> str | None:
    """Git, found even when it is not on PATH (a background shell on Windows often lacks it)."""
    import shutil
    found = shutil.which("git")
    if found:
        return found
    for var, sub in (("ProgramFiles", "Git"), ("ProgramW6432", "Git"), ("LOCALAPPDATA", "Programs/Git")):
        base = os.environ.get(var)
        if base and (Path(base) / sub / "cmd" / "git.exe").is_file():
            return str(Path(base) / sub / "cmd" / "git.exe")
    return None


# What the numbers depend on: a change here, uncommitted, makes the recorded commit not the whole story.
SOURCES = ("drum_agent", "scripts/eval_real.py")


def _meta(a, tracks, elapsed: float) -> dict:
    import platform
    import subprocess
    git, commit, dirty = _git_exe(), None, None
    if git:
        try:
            commit = subprocess.run([git, "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                    text=True, timeout=10).stdout.strip() or None
            if commit:
                dirty = bool(subprocess.run([git, "-C", str(ROOT), "status", "--porcelain", "--", *SOURCES],
                                            capture_output=True, text=True, timeout=10).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            commit = None
    model = None
    try:
        from drum_agent.audio.classifier import load_model
        model = load_model().version
    except Exception:  # noqa: BLE001 - no weights: the NMF detector is what ran
        pass
    meta = {"date": time.strftime("%Y-%m-%d %H:%M"), "commit": commit, "uncommitted_changes": dirty,
            "classifier": model, "separation": _separator() if a.separate else None, "tracks": list(tracks),
            "machine": f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}, "
                       f"Python {platform.python_version()}", "seconds": round(elapsed)}
    if commit is None:  # say why, so a record without its commit is not mistaken for one with nothing to say
        meta["commit_unknown"] = "git not found" if git is None else "git could not read the repository"
    return meta


def _meta_md(meta: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in meta.items() if k != "tracks") + \
        f"\n- tracks: {', '.join(meta['tracks'])}"


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"


if __name__ == "__main__":
    main()
