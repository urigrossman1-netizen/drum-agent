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


def load_audio(path: str | Path, start: float | None = None, end: float | None = None) -> np.ndarray:
    import librosa
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    duration = None if end is None else max(0.0, end - (start or 0.0))
    y, _ = librosa.load(str(path), sr=SR, mono=True, offset=start or 0.0, duration=duration)
    if y.size < SR:
        raise ValueError(f"{path.name}: less than one second of audio")
    return y


def transcribe_audio(y: np.ndarray, opts: TranscribeOptions, title: str = "Untitled") -> Score:
    if opts.time_signature and opts.time_signature not in AUDIO_SIMPLE_METERS:
        raise ValueError(f"--time-signature {opts.time_signature} is not supported for audio (beats must be equal "
                         f"length; supported: {', '.join(sorted(AUDIO_SIMPLE_METERS))}). For 5/8, 7/8 etc. "
                         f"transcribe from MIDI or write a chart spec.")
    det = detect(y, DetectOptions(drums_only=opts.drums_only, sensitivity=opts.sensitivity))
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
    measures = res.measures
    while len(measures) > 1 and not measures[-1].hits:
        measures.pop()
    if measures and not measures[0].hits and not measures[0].is_pickup:
        # leading silence that slipped in
        while len(measures) > 1 and not measures[0].hits:
            measures.pop(0)
    roadmap = label_sections(measures)
    counts = Counter(h.inst for m in measures for h in m.hits)
    low = sum(1 for m in measures for h in m.hits if h.confidence < 0.5)
    score = Score(measures=measures, title=title, chart_type="full_transcription", status="unverified_auto")
    score.swing = res.feel == "swing"
    score.analysis = {
        "input": "audio",
        "tempo_estimate": f"{grid.tempo:g} BPM (quarter note)",
        "meter": f"{grid.time_sig} (confidence {grid.meter_confidence})",
        "downbeat_confidence": grid.downbeat_confidence,
        "feel": res.feel + (f" (swing ratio {res.swing_ratio})" if res.swing_ratio else ""),
        "detected_onsets": len(det.hits),
        "instrument_counts": dict(counts.most_common()),
        "low_confidence_hits": low,
        "mean_abs_offset_ms": res.mean_abs_offset_ms,
        "grid_counts": res.grid_counts,
        "sections": [f"{r['label']}: bar {r['first_bar']}, {r['bars']} bars, {r['main_cymbal'] or 'no cymbal'}"
                     + (f", {r['fills']} fill bar(s)" if r["fills"] else "") for r in roadmap],
        "notes": grid.notes + [
            "Section letters are pattern-based; rename them with --sections once you know the song form.",
            "Hi-hat pedal strokes are not detected (no detector class); add them by hand if needed.",
        ],
    }
    return score


def transcribe_file(path: str | Path, opts: TranscribeOptions) -> Score:
    y = load_audio(path, opts.start, opts.end)
    score = transcribe_audio(y, opts, title=Path(path).stem.replace("_", " "))
    score.source = f"audio file {Path(path).name}" + (f" from {opts.start:g}s" if opts.start else "")
    return score


def analyze_file(path: str | Path, bpm: float | None = None, time_signature: str | None = None) -> dict:
    """High-level analysis only (no note-level output): tempo, meter, sections, instrumentation."""
    y = load_audio(path)
    score = transcribe_audio(y, TranscribeOptions(bpm=bpm, time_signature=time_signature))
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
