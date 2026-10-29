"""Evaluate stroke detection on real recordings: the MDB Drums dataset.

MDB Drums (Southall et al., ISMIR 2017) is 23 MedleyDB tracks with every
drum stroke annotated, each as an isolated drum mix and as the full band mix.
Unlike the synthesized fixtures of eval_detection.py these are real kits in
real rooms, played by real drummers, so this is the honest accuracy number.

The audio is CC BY-NC-SA 4.0: it is downloaded to a local cache, never into
the repository. Tune on the MIREX 2017 training half (--split train) and
report the test half (--split test), so the reported number is held out.

Usage:
  python scripts/eval_real.py --download            # once, about 200 MB
  python scripts/eval_real.py --split train --jobs 4
  python scripts/eval_real.py --split test --mix both
  python scripts/eval_real.py --split train --mix both --separate   # also "sep": the band mix,
      drums separated with HTDemucs first (needs `pip install demucs`; drum_agent/audio/separate.py)
Writes tests/_artifacts/eval_real_<split>.json.
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


def score_track(ref: list[tuple[float, str]], est: list[tuple[float, str]]) -> dict[str, dict[str, int]]:
    """tp/ref/est per MDB class (OT, "other" percussion, is not scored)."""
    import numpy as np
    import mir_eval
    out = {}
    for c in CLASSES:
        r = sorted(t for t, k in ref if k == c)
        e = sorted(t for t, k in est if k == c)
        tp = len(mir_eval.util.match_events(np.array(r), np.array(e), TOL)) if r and e else 0
        out[c] = {"tp": tp, "ref": len(r), "est": len(e)}
    return out


def run_one(job: tuple[str, str, str]) -> tuple[str, str, dict, float]:
    track, mix, pipeline = job
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
        det = detect(y, DetectOptions(drums_only=drums_only))
        est = [(h.time, OURS_TO_MDB.get(h.inst, "OT")) for h in det.hits]
    else:
        from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio
        score = transcribe_audio(y, TranscribeOptions(drums_only=drums_only))
        est = [(h.time, OURS_TO_MDB.get(h.inst, "OT")) for _, _, h in score.iter_hits() if h.time is not None]
    ref = read_annotations(p["class"])
    return track, mix, score_track(ref, est), time.time() - t0


def _separator() -> str:
    from drum_agent.audio.separate import MODEL
    return MODEL


def summarize(rows: dict[tuple[str, str], dict]) -> dict:
    pooled: dict[str, dict] = {}
    for mix in sorted({m for _, m in rows}):
        acc = defaultdict(lambda: {"tp": 0, "ref": 0, "est": 0})
        for (track, m), res in rows.items():
            if m != mix:
                continue
            for c, s in res.items():
                for k in ("tp", "ref", "est"):
                    acc[c][k] += s[k]
        table = {}
        for c in CLASSES:
            f, p, r = _f(acc[c]["tp"], acc[c]["ref"], acc[c]["est"])
            table[c] = {"F": round(f, 3), "P": round(p, 3), "R": round(r, 3), **acc[c]}
        for name, group in (("KD/SD/HH", CLASSES[:3]), ("all 5", CLASSES)):
            tp = sum(acc[c]["tp"] for c in group)
            ref = sum(acc[c]["ref"] for c in group)
            est = sum(acc[c]["est"] for c in group)
            f, p, r = _f(tp, ref, est)
            table[name] = {"F": round(f, 3), "P": round(p, 3), "R": round(r, 3), "tp": tp, "ref": ref, "est": est}
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
    jobs = [(t, m, a.pipeline) for t in tracks for m in mixes]
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
    print(f"\nMDB Drums, {a.split if not a.tracks else a.tracks}, pipeline={a.pipeline}, onset F at 50 ms "
          f"({time.time() - t0:.0f}s):")
    print(f"{'':6s} " + " ".join(f"{c:>6s}" for c in CLASSES) + f" {'KD/SD/HH':>9s} {'all 5':>6s} {'track-mean':>10s}")
    for mix, table in summary.items():
        print(f"{mix:6s} " + " ".join(f"{table[c]['F']:6.3f}" for c in CLASSES)
              + f" {table['KD/SD/HH']['F']:9.3f} {table['all 5']['F']:6.3f} {table['mean track F (KD/SD/HH)']:10.3f}")
    out = ROOT / "tests" / "_artifacts" / f"eval_real_{a.split if not a.tracks else 'custom'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "pipeline": a.pipeline,
                               "tracks": {f"{t}/{m}": r for (t, m), r in rows.items()}}, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
