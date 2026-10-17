"""Quantization: performed onsets + a beat clock -> bars with exact positions.

Shared by MIDI import and audio transcription. Each onset is placed relative
to the beat that contains it (beat times may drift, so tempo changes and
rubato are followed, not forced onto one grid). Each beat then gets the
subdivision grid with the lowest cost:

    cost = sum((timing error / sigma)^2) + complexity(grid) + collision penalty

so a sloppy 16th stays a 16th, real triplets become triplets, and noise
doesn't produce 32nd-note clutter unless the evidence is strong. The original
timing is kept on each hit (`time`, `offset_ms`).
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass, field
from fractions import Fraction

from .model import Hit, Measure, TimeSig


@dataclass
class Onset:
    time: float  # seconds
    inst: str
    velocity: int = 90
    confidence: float = 1.0
    accent: bool = False
    ghost: bool = False
    flam: bool = False
    drag: bool = False


@dataclass
class BarDef:
    first_beat: int  # index into the beat list
    time_sig: TimeSig
    beats: int  # number of beats in this bar (fewer than the meter for a pickup)


@dataclass
class QuantizeOptions:
    feel: str = "auto"  # auto | straight | swing | triplet
    allow_32nds: bool = True
    sigma_base: float = 0.012  # seconds
    sigma_rel: float = 0.03  # fraction of the beat duration
    tempo_change_threshold: float = 0.04  # relative change needed for a new tempo mark
    fixed_tempo: float | None = None  # force one tempo mark (quarter BPM)
    uncertain_conf: float = 0.5  # hits below this confidence are "low confidence"
    # Onsets are exact positions (a game chart's ticks), not played times: a beat whose
    # onsets all sit on some grid within this share of a beat is written on such a grid.
    exact_tol: float | None = None


@dataclass
class QuantizeResult:
    measures: list[Measure]
    feel: str
    swing_ratio: float | None
    merged: int = 0
    grid_counts: dict[str, int] = field(default_factory=dict)
    bar_tempi: list[float] = field(default_factory=list)
    mean_abs_offset_ms: float = 0.0
    dropped: int = 0  # onsets outside the beat grid (reported by callers)


_BINARY_COST = {1: 0.0, 2: 0.5, 4: 2.0, 3: 3.0, 6: 5.0, 8: 6.5, 12: 9.0}
_BINARY_COST_TRIPLET = {1: 0.0, 3: 0.5, 2: 1.5, 6: 2.5, 4: 3.5, 8: 8.0, 12: 6.0}
_TERNARY_COST = {1: 0.0, 3: 0.5, 6: 2.5, 2: 4.0, 4: 6.0, 12: 7.0}
# In a swing feel, swung 8ths are read through the warp; a beat that is really a
# triplet or straight-16th figure is read unwarped with these grids instead.
_SWING_WARPED = (1, 2)
_SWING_UNWARPED = {3: 1.5, 6: 4.0, 12: 8.0, 4: 3.0, 8: 6.5}
# Without 32nds no slot may be shorter than a 16th-note triplet, whatever the beat.
_MIN_SLOT_NO_32NDS = Fraction(1, 24)


def detect_feel(rels: list[float]) -> tuple[str, float | None]:
    """Classify within-beat positions (binary beats) as straight, swing or triplet."""
    def near(lo: float, hi: float) -> list[float]:
        return [r for r in rels if lo <= r <= hi]

    straight8 = len(near(0.45, 0.555))
    swung = near(0.6, 0.73)
    third = len(near(0.29, 0.39))
    sixteenths = len(near(0.2, 0.29)) + len(near(0.73, 0.8))
    if len(swung) >= 8 and len(swung) > 2 * straight8 and third < 0.35 * len(swung) and sixteenths < 0.5 * len(swung):
        return "swing", statistics.median(swung)
    if len(swung) + third >= 8 and third >= 0.35 * len(swung) and (len(swung) + third) > 1.5 * (straight8 + sixteenths):
        return "triplet", None
    return "straight", None


def _warp(rel: float, swing_pos: float) -> float:
    """Map a swung offbeat (at swing_pos) to 0.5 so it is written as a straight 8th."""
    if rel <= swing_pos:
        return rel * 0.5 / swing_pos
    return 0.5 + (rel - swing_pos) * 0.5 / (1 - swing_pos)


def _fits_exactly(n: int, rels: list[tuple[Onset, float]], tol: float) -> bool:
    """Every onset within `tol` (a share of the beat) of a slot of the n-grid, and no two
    onsets of one instrument on the same slot (that would merge distinct strokes)."""
    slots = set()
    for o, r in rels:
        slot = round(r * n)
        if abs(r - slot / n) > tol or (slot, o.inst) in slots:
            return False
        slots.add((slot, o.inst))
    return True


def _beat_is_binary(length: Fraction) -> bool:
    n, d = length.numerator, length.denominator
    return n & (n - 1) == 0 and d & (d - 1) == 0


def quantize(onsets: list[Onset], beat_times: list[float], bars: list[BarDef],
             options: QuantizeOptions | None = None) -> QuantizeResult:
    """Place onsets into bars. `beat_times` must extend one beat past the last bar."""
    opts = options or QuantizeOptions()
    if len(beat_times) < 2:
        raise ValueError("need at least two beat times")
    n_beats = len(beat_times) - 1

    # Beat -> (bar index, beat index in bar, beat start, beat length in whole notes)
    beat_info: list[tuple[int, int, Fraction, Fraction]] = []
    for bi, bar in enumerate(bars):
        meter_beats = bar.time_sig.beats()
        skip = len(meter_beats) - bar.beats  # pickup bars are the tail of a full bar
        offset = meter_beats[skip][0] if skip else Fraction(0)
        for k in range(bar.beats):
            start, length = meter_beats[skip + k]
            beat_info.append((bi, k, start - offset, length))
    if len(beat_info) != n_beats:
        raise ValueError(f"bars cover {len(beat_info)} beats but {n_beats} beat intervals were given")

    durations = [beat_times[k + 1] - beat_times[k] for k in range(n_beats)]
    if any(d <= 0 for d in durations):
        raise ValueError("beat times must be strictly increasing")

    # Assign onsets to beats (an onset up to 1/16 beat early belongs to the next beat).
    per_beat: list[list[tuple[Onset, float]]] = [[] for _ in range(n_beats)]
    guards = [beat_times[k] - durations[k] / 16 for k in range(n_beats)]
    dropped = 0
    for o in sorted(onsets, key=lambda o: o.time):
        k = bisect.bisect_right(guards, o.time) - 1
        if k < 0 or k >= n_beats:
            dropped += 1
            continue
        rel = (o.time - beat_times[k]) / durations[k]
        per_beat[k].append((o, rel))

    # Feel: from binary beats only.
    feel, swing_pos = opts.feel, None
    rels_all = [rel for k in range(n_beats) if _beat_is_binary(beat_info[k][3])
                for _, rel in per_beat[k] if 0.1 < rel < 0.9]
    if feel == "auto":
        feel, swing_pos = detect_feel(rels_all)
    elif feel == "swing":
        sw = [r for r in rels_all if 0.55 <= r <= 0.75]
        swing_pos = statistics.median(sw) if sw else 2 / 3

    placed: dict[tuple[int, Fraction, str], tuple[Hit, float]] = {}
    grid_counts: dict[str, int] = {}
    merged = 0
    abs_offsets: list[float] = []
    beat_uncertain = [False] * n_beats

    for k in range(n_beats):
        items = per_beat[k]
        if not items:
            continue
        bar_i, _, bstart, blen = beat_info[k]
        d = durations[k]
        binary = _beat_is_binary(blen)
        if binary:
            table = _BINARY_COST_TRIPLET if feel == "triplet" else _BINARY_COST
        else:
            table = _TERNARY_COST
        sigma = opts.sigma_base + opts.sigma_rel * d
        swing = feel == "swing" and binary and bool(swing_pos)
        warped = [(o, _warp(r, swing_pos) if swing and 0 <= r <= 1 else r) for o, r in items]
        candidates = []  # (grid, complexity, positions used)
        if swing:
            candidates += [(n, table[n], warped) for n in _SWING_WARPED]
            candidates += [(n, c, items) for n, c in _SWING_UNWARPED.items()]
        else:
            candidates += [(n, c, items) for n, c in table.items()]
        if not opts.allow_32nds:
            candidates = [c for c in candidates if blen / c[0] >= _MIN_SLOT_NO_32NDS]
        if opts.exact_tol is not None:
            # Time-based costs would let a cheaper grid win at a fast tempo (a 32nd is
            # closer in time to a sextuplet than any timing error); exact positions keep
            # a grid that fits them all, and off-grid ones are judged as usual.
            fits = [c for c in candidates if _fits_exactly(c[0], c[2], opts.exact_tol)]
            candidates = fits or candidates
        best = None
        for n, complexity, rels in candidates:
            cost = complexity
            seen: dict[tuple[int, str], int] = {}
            for o, r in rels:
                slot = min(max(round(r * n), 0), n)
                err = (r - slot / n) * d
                cost += (err / sigma) ** 2 * max(o.confidence, 0.2)
                key = (slot, o.inst)
                seen[key] = seen.get(key, 0) + 1
            cost += 4.0 * sum(c - 1 for c in seen.values())
            if best is None or cost < best[0]:
                best = (cost, n, rels)
        _, n, use_rels = best
        swung_reading = swing and use_rels is warped
        grid_counts[str(n)] = grid_counts.get(str(n), 0) + 1
        residuals = []
        for (o, r_orig), (_, r) in zip(items, use_rels):
            slot = min(max(round(r * n), 0), n)
            target_k, target_slot = k, slot
            if slot == n:
                if k + 1 < n_beats:
                    target_k, target_slot = k + 1, 0
                else:
                    target_slot = n - 1
            tb, _, tstart, tlen = beat_info[target_k]
            pos = tstart + tlen * Fraction(target_slot, n)
            q_time = beat_times[target_k] + (target_slot / n) * durations[target_k]
            if swung_reading and target_k == k and n == 2 and target_slot == 1:
                q_time = beat_times[k] + swing_pos * d  # the swung offbeat's nominal time
            offset_ms = (o.time - q_time) * 1000
            residuals.append(abs(offset_ms) / 1000 / sigma)
            abs_offsets.append(abs(offset_ms))
            hit = Hit(pos=pos, inst=o.inst, velocity=max(1, min(127, int(o.velocity))),
                      accent=o.accent, ghost=o.ghost and not o.accent, flam=o.flam, drag=o.drag and not o.flam,
                      confidence=round(min(1.0, max(0.0, o.confidence)), 3),
                      time=round(o.time, 4), offset_ms=round(offset_ms, 1))
            key = (tb, pos, o.inst)
            if key in placed:
                merged += 1
                old, _ = placed[key]
                if hit.velocity > old.velocity:
                    hit.confidence = max(hit.confidence, old.confidence)
                    placed[key] = (hit, o.time)
            else:
                placed[key] = (hit, o.time)
        if residuals and statistics.mean(residuals) > 1.6:
            beat_uncertain[k] = True

    # A hi-hat can't be open and closed at the same instant: when two detections of
    # different hi-hat states land on one slot, keep the more confident one.
    hh_states = ("hihat", "hihat_open", "hihat_half")
    by_slot: dict[tuple[int, Fraction], list[tuple[int, Fraction, str]]] = {}
    for key in placed:
        if key[2] in hh_states:
            by_slot.setdefault((key[0], key[1]), []).append(key)
    for keys in by_slot.values():
        if len(keys) > 1:
            keys.sort(key=lambda k: (placed[k][0].confidence, placed[k][0].velocity), reverse=True)
            for k in keys[1:]:
                del placed[k]
                merged += 1

    # Build measures.
    measures: list[Measure] = []
    beat_k = 0
    bar_tempi: list[float] = []
    for bi, bar in enumerate(bars):
        ts = bar.time_sig
        meter_beats = ts.beats()
        length = None
        if bar.beats < len(meter_beats):
            length = sum((ln for _, ln in meter_beats[len(meter_beats) - bar.beats:]), Fraction(0))
        ks = list(range(beat_k, beat_k + bar.beats))
        tempi = [240 * float(beat_info[k][3]) / durations[k] for k in ks]
        bar_tempi.append(statistics.median(tempi) if tempi else 120.0)
        m = Measure(time_sig=ts, length=length, start_time=round(beat_times[ks[0]], 4) if ks else None)
        m.hits = sorted((h for (b, _, _), (h, _) in placed.items() if b == bi), key=lambda h: (h.pos, h.inst))
        low = [h for h in m.hits if h.confidence < opts.uncertain_conf]
        very_low = [h for h in low if h.confidence < 0.6 * opts.uncertain_conf]
        # One borderline stroke in a busy bar is normal; flag bars where doubt piles up.
        if len(low) >= 2 or very_low or any(beat_uncertain[k] for k in ks):
            m.uncertain = True
            if low:
                m.notes.append(f"{len(low)} low-confidence hit(s): " +
                               ", ".join(sorted({h.inst for h in low})))
            if any(beat_uncertain[k] for k in ks):
                m.notes.append("timing does not fit a clear subdivision")
        measures.append(m)
        beat_k += bar.beats

    _apply_tempo_marks(measures, bar_tempi, opts)
    if feel == "swing":
        measures[0].tempo_text = "Swing"
    return QuantizeResult(measures, feel, round(swing_pos, 3) if swing_pos else None, merged, grid_counts,
                          [round(t, 2) for t in bar_tempi],
                          round(statistics.mean(abs_offsets), 1) if abs_offsets else 0.0, dropped)


def _apply_tempo_marks(measures: list[Measure], bar_tempi: list[float], opts: QuantizeOptions) -> None:
    if not measures:
        return
    if opts.fixed_tempo is not None:
        measures[0].tempo = round(opts.fixed_tempo, 2)
        return
    n = len(bar_tempi)

    def window(i: int) -> float:
        return statistics.median(bar_tempi[max(0, i - 1):min(n, i + 3)])

    current = round(statistics.median(bar_tempi[:min(n, 4)]))
    measures[0].tempo = float(current)
    i = 1
    while i < n:
        # A change between simple and compound meter always gets a fresh tempo mark
        # (the beat unit changes from quarter to dotted quarter or back).
        if measures[i].time_sig.is_compound != measures[i - 1].time_sig.is_compound:
            current = round(window(i))
            measures[i].tempo = float(current)
            i += 1
            continue
        w = window(i)
        thr = opts.tempo_change_threshold
        if abs(w - current) / current > thr and i + 1 < n and abs(window(i + 1) - current) / current > thr:
            # The windows see a change coming a bar early; the mark goes on the first
            # bar whose own tempo has moved, with the tempo of the bars after it.
            j = next((t for t in range(i, min(n, i + 3)) if abs(bar_tempi[t] - current) / current > thr), i + 1)
            current = round(statistics.median(bar_tempi[j:min(n, j + 3)]))
            measures[j].tempo = float(current)
            i = j + 2
            continue
        i += 1


def beats_from_meter(start_time: float, beat_seconds: list[float]) -> list[float]:
    """Cumulative beat times from per-beat durations."""
    out = [start_time]
    for d in beat_seconds:
        out.append(out[-1] + d)
    return out
