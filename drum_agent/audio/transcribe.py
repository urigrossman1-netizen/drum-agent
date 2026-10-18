"""Audio recording -> Score (automatic, unverified transcription)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..model import Score, TimeSig
from ..quantize import BarDef, Onset, QuantizeOptions, quantize
from .beats import estimate_grid
from .detect import DetectOptions, detect
from .features import SR
from .structure import label_sections

AUDIO_SIMPLE_METERS = {"2/4", "3/4", "4/4", "5/4", "6/4", "7/4", "6/8", "9/8", "12/8"}


@dataclass
class TranscribeOptions:
    bpm: float | None = None
    time_signature: str | None = None
    downbeat: float | None = None
    feel: str = "auto"
    drums_only: bool = False
    sensitivity: float = 1.0
    allow_32nds: bool = True
    start: float | None = None
    end: float | None = None
    detector: str = "auto"  # "classifier", "nmf" or "auto" (the classifier when its weights are installed)


def load_audio(path: str | Path, start: float | None = None, end: float | None = None) -> np.ndarray:
    import librosa
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    duration = None if end is None else max(0.0, end - (start or 0.0))
    try:
        y, _ = librosa.load(str(path), sr=SR, mono=True, offset=start or 0.0, duration=duration)
    except Exception as exc:  # libsndfile can't read every container (e.g. AAC in .m4a)
        y = _ffmpeg_decode(path, start, duration, exc)
    if y.size < SR:
        raise ValueError(f"{path.name}: less than one second of audio")
    return y


def _ffmpeg_decode(path: Path, start: float | None, duration: float | None, cause: Exception) -> np.ndarray:
    """Decode with ffmpeg when libsndfile can't (librosa no longer falls back by itself)."""
    import shutil
    import subprocess
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise ValueError(f"{path.name}: can't decode this format ({cause}). Install ffmpeg, or convert the file "
                         f"to WAV or FLAC.") from cause
    cmd = [exe, "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"{path.name}: ffmpeg couldn't decode it either: "
                         f"{proc.stderr.decode(errors='replace')[-300:]}") from cause
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def transcribe_audio(y: np.ndarray, opts: TranscribeOptions, title: str = "Untitled") -> Score:
    if opts.time_signature and opts.time_signature not in AUDIO_SIMPLE_METERS:
        raise ValueError(f"--time-signature {opts.time_signature} is not supported for audio (beats must be equal "
                         f"length; supported: {', '.join(sorted(AUDIO_SIMPLE_METERS))}). For 5/8, 7/8 etc. "
                         f"transcribe from MIDI or write a chart spec.")
    det = detect(y, DetectOptions(drums_only=opts.drums_only, sensitivity=opts.sensitivity, method=opts.detector))
    if not det.hits:
        raise ValueError("no drum strokes detected; is there a drum part? Try --sensitivity 1.5")
    pre_feel = opts.feel if opts.feel != "auto" else None
    grid = estimate_grid(det.hits, det.onset_env, det.duration, opts.bpm, opts.time_signature, opts.downbeat, pre_feel)
    ts = TimeSig.parse(grid.time_sig)
    beats = grid.beat_times
    bpb = grid.beats_per_bar
    k0 = grid.downbeat_index
    first = min(h.time for h in det.hits)
    last = max(h.time for h in det.hits)
    # Earliest beat that holds a stroke (with the quantizer's 1/16-beat early guard).
    first_beat = k0
    while first_beat > 0 and beats[first_beat] - (beats[first_beat] - beats[first_beat - 1]) / 16 > first:
        first_beat -= 1
    bars: list[BarDef] = []
    pos = 0
    if first_beat < k0:
        bars.append(BarDef(0, ts, k0 - first_beat))
        pos = k0 - first_beat
    idx = k0
    while idx + bpb < len(beats) and beats[idx] <= last + 1e-6:
        bars.append(BarDef(pos, ts, bpb))
        pos += bpb
        idx += bpb
    beat_slice = beats[first_beat:first_beat + pos + 1]
    if len(beat_slice) < pos + 1:  # extend the grid if the last bar runs past the tracked beats
        ibi = beats[-1] - beats[-2]
        while len(beat_slice) < pos + 1:
            beat_slice.append(beat_slice[-1] + ibi)
    onsets = [Onset(h.time, h.inst, h.velocity, h.confidence, accent=h.accent, ghost=h.ghost, flam=h.flam)
              for h in det.hits]
    qopts = QuantizeOptions(feel=opts.feel, allow_32nds=opts.allow_32nds, fixed_tempo=None)
    res = quantize(onsets, beat_slice, bars, qopts)
    meter_notes: list[str] = []
    if not opts.time_signature:
        # Sections whose pattern doesn't fit the global meter (e.g. a 12/8 bridge in a 4/4 song).
        refined = _refine_section_meters(det.hits, beat_slice, bars, res.measures, ts)
        if refined is not None:
            beat_slice, bars, meter_notes = refined
            res = quantize(onsets, beat_slice, bars, qopts)
    # A short bar (e.g. one 2/4 bar ending a section) shifts every later downbeat;
    # crashes that move off beat 1 for good show where. A meter given by the user
    # holds throughout: no bars of another meter are inserted.
    if not opts.time_signature:
        beat_slice, bars, res, shift_notes = _realign_downbeats(onsets, beat_slice, bars, res, qopts)
        meter_notes += shift_notes
    measures = res.measures
    rolls = _notate_rolls(measures)
    while len(measures) > 1 and not measures[-1].hits:
        measures.pop()
    if measures and not measures[0].hits and not measures[0].is_pickup:
        # leading silence that slipped in
        while len(measures) > 1 and not measures[0].hits:
            measures.pop(0)
    density_note = _check_kick_density(measures)
    roadmap = label_sections(measures)
    counts = Counter(h.inst for m in measures for h in m.hits)
    low = sum(1 for m in measures for h in m.hits if h.confidence < 0.5)
    score = Score(measures=measures, title=title, chart_type="full_transcription", status="unverified_auto")
    score.swing = res.feel == "swing"
    # Strokes one drummer can't play together are a detection error somewhere in that bar.
    from ..playability import check, flag_bars
    unplayable = flag_bars(score, check(score))
    doubtful = _flag_near_misses(measures, det.stats.get("near_misses", []))
    score.analysis = {
        "input": "audio",
        "tempo_estimate": f"{grid.tempo:g} BPM (quarter note)",
        "meter": f"{grid.time_sig} (confidence {grid.meter_confidence})",
        "downbeat_confidence": grid.downbeat_confidence,
        "feel": res.feel + (f" (swing ratio {res.swing_ratio})" if res.swing_ratio else ""),
        "detected_onsets": len(det.hits),
        "instrument_counts": dict(counts.most_common()),
        "low_confidence_hits": low,
        "bars_with_near_misses": doubtful,
        "rolls_notated": rolls,
        "mean_abs_offset_ms": res.mean_abs_offset_ms,
        "grid_counts": res.grid_counts,
        "sections": [f"{r['label']}: bar {r['first_bar']}, {r['bars']} bars, {r['main_cymbal'] or 'no cymbal'}"
                     + (f", {r['fills']} fill bar(s)" if r["fills"] else "") for r in roadmap],
        "notes": grid.notes + meter_notes + ([density_note] if density_note else []) + (
            [f"{unplayable} bar(s) contain strokes one drummer can't play together (flagged); a stroke there was "
             f"probably detected on the wrong instrument."] if unplayable else []) + [
            "Section letters are pattern-based; rename them with --sections once you know the song form.",
        ] + ([] if det.stats.get("detector", "").startswith("classifier") else [
            "Hi-hat pedal strokes are not detected (no detector class); add them by hand if needed.",
        ]),
        "detector": det.stats.get("detector", "nmf"),
    }
    return score


# A bar holding a stroke the classifier almost heard (a class at half its threshold or
# more, or one a playability rule removed) is flagged. Calibrated on library grooves,
# not on the evaluation charts: 87% of such bars held an error, and with the flags
# from low confidence they caught 75% of the wrong bars (21% without them).
NEAR_FLAG = 0.5


def _flag_near_misses(measures, near: list[tuple[float, str, float]]) -> int:
    """Flag bars with near misses; returns how many bars were newly flagged."""
    import bisect
    starts = [m.start_time for m in measures]
    if not near or not measures or any(s is None for s in starts):
        return 0
    per_bar: dict[int, set[str]] = {}
    for time, cls, ratio in near:
        if ratio < NEAR_FLAG:
            continue
        i = bisect.bisect_right(starts, time + 0.03) - 1  # a stroke a little early belongs to its bar
        if 0 <= i < len(measures):
            per_bar.setdefault(i, set()).add(cls)
    newly = 0
    for i, classes in sorted(per_bar.items()):
        m = measures[i]
        newly += not m.uncertain
        m.uncertain = True
        m.notes.append("possible missed or misheard stroke: " + ", ".join(sorted(classes)))
    return newly


def _check_kick_density(measures) -> str | None:
    """Flag a kick line denser than any drummer plays for long (bass bleed in a mix)."""
    import statistics
    per_beat = []
    for m in measures:
        beats = len(m.time_sig.beats()) if not m.is_pickup else 0
        if beats:
            per_beat.append(sum(1 for h in m.hits if h.inst == "kick") / beats)
    if len(per_beat) < 2:
        return None
    med = statistics.median(per_beat)
    if med <= 2.5:  # more than ~10 kicks per 4/4 bar, bar after bar, is implausible
        return None
    for m in measures:
        for h in m.hits:
            if h.inst == "kick":
                h.confidence = round(min(h.confidence, 0.45), 3)
        m.uncertain = True
        if "kick line implausibly dense" not in " ".join(m.notes):
            m.notes.append("kick line implausibly dense (bass bleed?)")
    return (f"WARNING: the kick line is implausibly dense (median {med:.1f} kicks per beat). This usually "
            f"means bass-guitar or synth-bass attacks were taken for kicks. Transcribe an isolated drum stem "
            f"(--drums-only) or a MIDI drum track, or verify every kick by ear.")


ROLL_MIN_STROKES = 8  # a quarter note of 32nds; shorter bursts stay written out


def _notate_rolls(measures) -> int:
    """Write long runs of 32nd strokes on one drum as a single rolled note.

    Fast single strokes (a couple of 32nds) stay written out; a sustained
    stream of 32nds is a roll, and drum charts write it with roll slashes.
    """
    from fractions import Fraction
    step = Fraction(1, 32)
    count = 0
    for m in measures:
        for inst in ("snare", "tom1", "tom2", "floor_tom"):
            strokes = sorted((h for h in m.hits if h.inst == inst), key=lambda h: h.pos)
            i = 0
            while i < len(strokes):
                j = i
                while j + 1 < len(strokes) and strokes[j + 1].pos - strokes[j].pos == step:
                    j += 1
                n = j - i + 1
                if n >= ROLL_MIN_STROKES:
                    run = strokes[i:j + 1]
                    head = run[0]
                    length = min(n * step, m.actual_length - head.pos)
                    others = [h for h in m.hits if h.inst not in (inst,) and head.pos < h.pos < head.pos + length
                              and h.inst not in ("kick", "kick2", "hihat_pedal")]
                    if not others:  # the hands are busy with the roll
                        head.roll = length
                        head.confidence = min(h.confidence for h in run)
                        for h in run[1:]:
                            m.hits.remove(h)
                        count += 1
                i = j + 1
    return count


def _crash_phases(bars: list[BarDef], measures) -> list[tuple[int, int]]:
    """(bar, beat index) of every crash on a beat, in bars of one simple meter."""
    out = []
    for i, (b, m) in enumerate(zip(bars, measures)):
        ts = b.time_sig
        if ts.is_compound or ts.is_irregular or b.beats != len(ts.beats()):
            continue
        beat_len = ts.beats()[0][1]
        for h in m.hits:
            q = h.pos / beat_len
            if h.inst == "crash" and q.denominator == 1:
                out.append((i, int(q)))
    return sorted(out)


def _find_downbeat_shift(bars: list[BarDef], measures, after_bar: int = -1) -> tuple[int, int, int] | None:
    """First bar (after `after_bar`) from which crashes sit on beat p+1 instead of beat 1.

    Crash phases are grouped into runs; single off-phase crashes (accents) are
    ignored. A shift is a run of at least two downbeat crashes followed by a run
    of at least two crashes on another beat. Each change is reported on its own,
    so two short bars in a song are found one after the other.
    """
    runs: list[list] = []  # [phase, [bar, ...]]
    for i, ph in _crash_phases(bars, measures):
        if runs and runs[-1][0] == ph:
            runs[-1][1].append(i)
        else:
            runs.append([ph, [i]])
    merged: list[list] = []
    for ph, bs in (r for r in runs if len(r[1]) >= 2):
        if merged and merged[-1][0] == ph:
            merged[-1][1] += bs
        else:
            merged.append([ph, list(bs)])
    for k, ((ph0, _), (ph1, bs1)) in enumerate(zip(merged, merged[1:])):
        i = bs1[0]
        if ph0 == 0 and ph1 != 0 and i > after_bar:
            ts = bars[i].time_sig
            if all(b.time_sig == ts and b.beats == len(ts.beats()) for b in bars[i:]):
                # The shift governs the bars up to the next change of crash phase.
                end = merged[k + 2][1][0] if k + 2 < len(merged) else len(bars)
                return i, ph1, end
    return None


def _repetition_score(measures, start: int, earlier: int, stop: int | None = None) -> float:
    """Mean best match (Jaccard on (position, instrument)) of bars start..stop-1 with bars before `earlier`."""
    def key(m):
        return {(h.pos, h.inst) for h in m.hits}
    ref = [key(m) for m in measures[:earlier] if len(m.hits) >= 3]
    scores = []
    for m in measures[start:stop]:
        k = key(m)
        if len(k) >= 3 and ref:
            scores.append(max(len(k & r) / len(k | r) for r in ref))
    return sum(scores) / len(scores) if scores else 0.0


REPEAT_STRONG = 0.6  # mean best-match of bars with earlier bars that counts as "clearly repeating"


def _realign_downbeats(onsets, beats: list[float], bars: list[BarDef], res, qopts):
    """Insert a short bar where the downbeat shifts, if that explains the music better.

    The change is kept only if the bars after it repeat earlier material more
    closely than before (a section that merely accents beat 3 doesn't), and the
    inserted bar is flagged for a listen.
    """
    notes: list[str] = []
    inserted: list[tuple[int, TimeSig]] = []
    after_bar = -1
    for _ in range(4):  # at most a few short bars per song
        found = _find_downbeat_shift(bars, res.measures, after_bar)
        if found is None:
            break
        b, p, end = found
        ts = bars[b].time_sig
        start = bars[b].first_beat
        bpb = len(ts.beats())
        short = TimeSig(p, ts.den)
        new_bars = bars[:b] + [BarDef(start, short, p)]
        new_bars += [BarDef(start + p + j * bpb, ts, bpb) for j in range(len(bars) - b)]
        need = new_bars[-1].first_beat + new_bars[-1].beats + 1
        new_beats = list(beats)
        while len(new_beats) < need:
            new_beats.append(new_beats[-1] + (new_beats[-1] - new_beats[-2]))
        res2 = quantize(onsets, new_beats, new_bars, qopts)
        before = _repetition_score(res.measures, b, b, end)
        after = _repetition_score(res2.measures, b + 1, b, end + 1)
        # Keep the barring only when it already explains strong repetition of
        # earlier bars better (e.g. crash accents on beat 3 over the same groove).
        # New material that repeats nothing earlier either way leaves the crashes
        # as the evidence.
        if (before >= REPEAT_STRONG and after < before + 0.05) or after < before - 0.05:
            notes.append(f"crashes move to beat {p + 1} from bar {b + 1}, but a short bar there doesn't make the "
                         f"music repeat better ({after:.2f} vs {before:.2f}); barring kept. Check the downbeats "
                         f"from bar {b + 1} by ear.")
            after_bar = b
            continue
        bars, beats, res = new_bars, new_beats, res2
        after_bar = b + 1
        inserted.append((b, short))
        notes.append(f"bar {b + 1}: the downbeat shifts by {p} beat(s) (crashes moved from beat 1 to beat {p + 1}); "
                     f"a {short} bar was inserted (bars after it repeat earlier ones {after:.2f} vs {before:.2f}). "
                     f"Verify by ear.")
    # Flag every inserted bar (each re-quantization builds fresh measures).
    for b, short in inserted:
        m = res.measures[b]
        m.uncertain = True
        m.notes.append(f"short bar ({short}) inserted: the downbeat shifts here")
    return beats, bars, res, notes


def _refine_section_meters(hits, beats: list[float], bars: list[BarDef], measures, ts: TimeSig):
    """Re-meter sections whose drum pattern repeats every 6 tracked beats (12/8) or 3 (3/4).

    The beat tracker follows one pulse. A 12/8 shuffle section inside a 4/4 song
    is tracked at two eighths per beat, which is rhythmically right but reads
    badly (syncopated straight 8ths). Here each section is tested on its own.
    """
    from .beats import _beat_features, _repetition
    from .structure import find_sections
    if str(ts) != "4/4" or len(bars) < 4:
        return None
    starts = find_sections(measures)
    if len(starts) < 2:
        return None
    bounds = starts + [len(bars)]
    new_beats: list[float] = []
    new_bars: list[BarDef] = []
    notes: list[str] = []
    changed = False
    beat_arr = np.array(beats)

    def interp(x: float) -> float:
        i = int(np.floor(x))
        if i >= len(beat_arr) - 1:
            i = len(beat_arr) - 2
        return float(beat_arr[i] + (x - i) * (beat_arr[i + 1] - beat_arr[i]))

    # Bars before the first section (pickup) are kept.
    def keep(bar_from: int, bar_to: int) -> None:
        for b in bars[bar_from:bar_to]:
            first = len(new_beats)
            for j in range(b.beats):
                new_beats.append(beats[b.first_beat + j])
            new_bars.append(BarDef(first, b.time_sig, b.beats))

    def snare_on_beat(bar: BarDef) -> bool | None:
        """True if the bar's strong snares sit on tracked beats (4/4 backbeat),
        False if between them (12/8 backbeat at two eighths per tracked beat)."""
        on = off = 0
        for h in hits:
            if h.inst != "snare" or h.ghost or h.strength < 0.5:
                continue
            k = bar.first_beat
            if not beat_arr[k] - 0.05 <= h.time < beat_arr[min(k + bar.beats, len(beat_arr) - 1)] - 0.05:
                continue
            j = int(np.searchsorted(beat_arr, h.time + 0.05, side="right")) - 1
            rel = (h.time - beat_arr[j]) / (beat_arr[j + 1] - beat_arr[j]) if j + 1 < len(beat_arr) else 0
            rel = rel - round(rel)
            if abs(rel) < 0.12:
                on += 1
            elif abs(abs(rel) - 0.5) < 0.12:
                off += 1
        if on + off == 0:
            return None
        if on >= 2 and off == 0:
            return True  # clearly a 4/4 backbeat
        if off >= on:
            return False
        return None  # mixed evidence: neither trims nor blocks

    # Candidate regions come from sections; trim 4/4-looking bars off their ends.
    regions: list[tuple[int, int]] = []
    for si in range(len(bounds) - 1):
        b0, b1 = bounds[si], bounds[si + 1]
        while b0 < b1 and snare_on_beat(bars[b0]) is True:
            b0 += 1
        while b1 > b0 and snare_on_beat(bars[b1 - 1]) is True:
            b1 -= 1
        regions.append((b0, b1))
    cuts = sorted({bounds[0], bounds[-1]} | {b for r in regions for b in r} | set(bounds))
    bounds = cuts

    keep(0, bounds[0])
    for si in range(len(bounds) - 1):
        b0, b1 = bounds[si], bounds[si + 1]
        sec_bars = bars[b0:b1]
        votes = [snare_on_beat(b) for b in sec_bars]
        if votes.count(True) > votes.count(False):  # mostly a 4/4 backbeat; one stray snare can't veto
            keep(b0, b1)
            continue
        if len(sec_bars) < 3 or any(b.beats != 4 for b in sec_bars):
            keep(b0, b1)
            continue
        k_start = sec_bars[0].first_beat
        k_end = sec_bars[-1].first_beat + sec_bars[-1].beats
        sec_beats = beat_arr[k_start:k_end + 1]
        sec_hits = [h for h in hits if sec_beats[0] - 0.05 <= h.time < sec_beats[-1] - 0.05]
        F = _beat_features(sec_hits, sec_beats)
        r4, r6 = _repetition(F, 4), _repetition(F, 6)
        # 8th-level strokes only (no 16th positions), as a 12/8 reading needs.
        pos = []
        for h in sec_hits:
            k = int(np.searchsorted(sec_beats, h.time, side="right")) - 1
            if 0 <= k < len(sec_beats) - 1:
                pos.append((h.time - sec_beats[k]) / (sec_beats[k + 1] - sec_beats[k]))
        pos = np.array(pos)
        on_eighths = float(np.mean(np.min(np.abs(pos[:, None] - np.array([0, 0.5, 1.0])[None, :]), axis=1) < 0.08)) if len(pos) else 0
        n_tracked = k_end - k_start
        if r6 > r4 + 0.1 and r6 > 0.55 and on_eighths > 0.8 and n_tracked >= 12:
            n128 = n_tracked // 6
            for j in range(n128):
                first = len(new_beats)
                for q in range(4):
                    new_beats.append(interp(k_start + j * 6 + q * 1.5))
                new_bars.append(BarDef(first, TimeSig(12, 8), 4))
            rest = n_tracked - n128 * 6
            if rest:
                first = len(new_beats)
                for q in range(rest):
                    new_beats.append(beats[k_start + n128 * 6 + q])
                new_bars.append(BarDef(first, TimeSig(rest, 4), rest))
            notes.append(f"bars {b0 + 1}-{b1}: pattern repeats every 6 beats with 8th-note strokes; written in 12/8 "
                         f"(repetition 6 beats {r6:.2f} vs 4 beats {r4:.2f})")
            changed = True
        else:
            keep(b0, b1)
    if not changed:
        return None
    new_beats.append(beats[bars[-1].first_beat + bars[-1].beats] if bars[-1].first_beat + bars[-1].beats < len(beats)
                     else new_beats[-1] + (new_beats[-1] - new_beats[-2]))
    return new_beats, new_bars, notes


def transcribe_file(path: str | Path, opts: TranscribeOptions) -> Score:
    y = load_audio(path, opts.start, opts.end)
    score = transcribe_audio(y, opts, title=Path(path).stem.replace("_", " "))
    score.source = f"audio file {Path(path).name}" + (f" from {opts.start:g}s" if opts.start else "")
    return score


def analyze_file(path: str | Path, bpm: float | None = None, time_signature: str | None = None,
                 detector: str = "auto") -> dict:
    """High-level analysis only (no note-level output): tempo, meter, sections, instrumentation."""
    y = load_audio(path)
    score = transcribe_audio(y, TranscribeOptions(bpm=bpm, time_signature=time_signature, detector=detector))
    return {
        "file": str(path),
        "duration_s": round(len(y) / SR, 1),
        "tempo": score.analysis["tempo_estimate"],
        "meter": score.analysis["meter"],
        "feel": score.analysis["feel"],
        "bars": len(score.measures),
        "sections": score.analysis["sections"],
        "note": "High-level analysis only. Full transcription requires --rights (own, permission, licensed, "
                "public_domain, original); otherwise obtain a licensed chart.",
    }
