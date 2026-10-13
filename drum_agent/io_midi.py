"""MIDI drum track -> IR, via the shared quantizer.

A MIDI file carries exact strokes and a beat grid (ticks + time signatures),
so this is the most accurate input path: no audio detection is involved. The
quantizer still runs, because e-kit performances recorded without
quantization drift off the grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import mido

from .kit import GM_IMPORT_MAP
from .model import Score, TimeSig
from .quantize import BarDef, Onset, QuantizeOptions, quantize


@dataclass
class MidiImportReport:
    notes: int = 0
    unmapped: dict[int, int] = field(default_factory=dict)
    channels: list[int] = field(default_factory=list)
    trimmed_leading_bars: int = 0
    pickup: Fraction | None = None  # whole notes
    pickup_reason: str = ""
    graces_folded: int = 0
    warnings: list[str] = field(default_factory=list)


TEMPO_MARK_CHANGE = 0.02  # relative change from the last mark that earns a new one


def _bar_ticks(ts: TimeSig, tpb: int) -> int:
    return int(round(ts.bar_length * 4 * tpb))


def _barlines(ts_changes: list[tuple[int, TimeSig]], start: int, upto: int, tpb: int) -> set[int]:
    """Barline ticks of a grid whose first full bar starts at `start`; a meter change
    applies from the first barline at or after it."""
    lines = set()
    tick, i = start, 0
    while tick <= upto:
        while i + 1 < len(ts_changes) and ts_changes[i + 1][0] <= tick:
            i += 1
        lines.add(tick)
        tick += _bar_ticks(ts_changes[i][1], tpb)
    return lines


def _is_pickup_length(length: Fraction, ts: TimeSig) -> bool:
    """Could a bar of `length` be the anacrusis of `ts`? Less than one beat, or the tail
    of whole beats of a bar (a 2/4 bar before 6/8 is neither: it is a real bar)."""
    beats = ts.beats()
    if length >= ts.bar_length:
        return False
    if length < beats[-1][1]:
        return True
    acc = Fraction(0)
    for _, ln in reversed(beats):
        acc += ln
        if acc == length:
            return True
    return False


def _infer_pickup(ts_changes: list[tuple[int, TimeSig]], markers: list[tuple[int, str]],
                  tpb: int, strong: list[int] | None = None) -> tuple[int, str] | None:
    """Pickup length in ticks, inferred from the file's own bar structure, or None.

    `strong` are the ticks of kick and crash strokes: an inferred shift of the
    barlines must put at least as many of them on downbeats as tick-0 barlines do.
    """
    # Notation programs (and our own writer) export a pickup as a short opening meter.
    if len(ts_changes) >= 2 and ts_changes[0][0] == 0:
        (t0, ts0), (t1, ts1) = ts_changes[0], ts_changes[1]
        if t1 == _bar_ticks(ts0, tpb) and _is_pickup_length(ts0.bar_length, ts1):
            return t1, f"the file opens with one {ts0} bar before {ts1}"
    # Meter changes and section markers belong on barlines. If they all sit the
    # same distance after the barlines counted from tick 0, the music starts
    # with a pickup of that length. One cue marker alone is not enough evidence.
    meter_anchors = {t for t, _ in ts_changes[1:]}
    anchors = sorted(meter_anchors | {t for t, _ in markers if t > 0})
    if not anchors or (len(anchors) < 2 and not meter_anchors):
        return None
    d = anchors[0] % _bar_ticks(ts_changes[0][1], tpb)
    if d == 0:
        return None
    if not set(anchors) <= _barlines(ts_changes, d, anchors[-1], tpb):
        return None
    if strong:
        end = max(strong)
        on_shifted = sum(t in _barlines(ts_changes, d, end, tpb) for t in strong)
        on_plain = sum(t in _barlines(ts_changes, 0, end, tpb) for t in strong)
        if on_shifted < on_plain:
            return None  # the strokes say the barlines start at tick 0
    return d, "meter changes/markers fall that far after the barlines counted from the start"


GRACE_DRUMS = {"snare", "rimshot", "tom1", "tom2", "floor_tom", "floor_tom2"}


def _fold_graces(notes: list[tuple[int, int, int]], tpb: int) -> tuple[list[tuple[int, int, int, bool, bool]], int]:
    """Soft strokes just before a louder one on the same drum are its grace notes.

    Within a 32nd note and at most 0.7x the main stroke's velocity: one grace
    makes a flam, two make a drag (as our MIDI writer and e-kits play them).
    Returns (tick, note, velocity, flam, drag) and the number of graces folded.
    """
    reach = tpb // 8
    out: list[list] = []
    folded = 0
    by_inst: dict[str, list[list]] = {}
    for t, n, v in sorted(notes):
        inst = GM_IMPORT_MAP[n]
        seq = by_inst.setdefault(inst, [])
        graces = 0
        while (inst in GRACE_DRUMS and seq and graces < 2 and t - seq[-1][0] <= reach
               and seq[-1][2] <= 0.7 * v and not seq[-1][3] and not seq[-1][4] and seq[-1][0] < t):
            seq.pop()
            graces += 1
        folded += graces
        seq.append([t, n, v, graces == 1, graces == 2])
    for seq in by_inst.values():
        out += seq
    return [tuple(x) for x in sorted(out)], folded


def _markers(mid: mido.MidiFile) -> list[tuple[int, str]]:
    out = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "marker" and msg.text.strip():
                out.append((tick, msg.text.strip()))
    return sorted(out)


def _tempo_map(mid: mido.MidiFile) -> list[tuple[int, int]]:
    changes = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                changes.append((tick, msg.tempo))
    changes.sort(key=lambda c: c[0])  # stable: of two events at one tick the later one wins
    if not changes or changes[0][0] != 0:
        changes.insert(0, (0, 500000))
    return changes


def _tempo_at(tempo_map: list[tuple[int, int]], tick: int) -> int:
    """Microseconds per quarter in force at `tick` (ticks before 0 use the opening tempo)."""
    tick = max(tick, 0)
    return [tm for t, tm in tempo_map if t <= tick][-1]


def _tick_to_seconds(tick: int, tempo_map: list[tuple[int, int]], tpb: int) -> float:
    secs = 0.0
    for i, (t0, tempo) in enumerate(tempo_map):
        t1 = tempo_map[i + 1][0] if i + 1 < len(tempo_map) else None
        if t1 is not None and tick > t1:
            secs += (t1 - t0) * tempo / 1e6 / tpb
        else:
            secs += (tick - t0) * tempo / 1e6 / tpb
            break
    return secs


def open_midi(path: str | Path) -> mido.MidiFile:
    """Text meta events in UTF-8 (what we and most current software write), else Latin-1."""
    try:
        return mido.MidiFile(str(path), charset="utf-8")
    except UnicodeDecodeError:
        return mido.MidiFile(str(path), charset="latin1")


def read_midi(path: str | Path, channel: int | None = None, options: QuantizeOptions | None = None,
              title: str | None = None, keep_leading_silence: bool = False,
              pickup: Fraction | str | None = "auto") -> tuple[Score, MidiImportReport]:
    """Import a drum track. `pickup`: length of an anacrusis in whole notes, "auto"
    (infer it from a short opening meter or from off-barline meter changes and
    markers), or None/0 for none."""
    mid = open_midi(path)
    tpb = mid.ticks_per_beat
    report = MidiImportReport()
    tempo_map = _tempo_map(mid)
    markers = _markers(mid)

    ts_changes: list[tuple[int, TimeSig]] = []
    raw: list[tuple[int, int, int, int]] = []  # tick, note, velocity, channel
    track_names = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "time_signature":
                ts_changes.append((tick, TimeSig(msg.numerator, msg.denominator)))
            elif msg.type == "track_name" and msg.name.strip():
                track_names.append(msg.name.strip())
            elif msg.type == "note_on" and msg.velocity > 0:
                raw.append((tick, msg.note, msg.velocity, msg.channel))
    ts_changes.sort(key=lambda x: x[0])  # stable; then the last meter at a tick wins
    ts_changes = [c for i, c in enumerate(ts_changes) if i + 1 == len(ts_changes) or ts_changes[i + 1][0] != c[0]]
    ts_changes = [c for i, c in enumerate(ts_changes) if i == 0 or c[1] != ts_changes[i - 1][1]]
    if not ts_changes or ts_changes[0][0] != 0:
        ts_changes.insert(0, (0, TimeSig(4, 4)))

    chans = sorted({c for *_, c in raw})
    if channel is None:
        channel = 9 if 9 in chans else None
        if channel is None:
            raise ValueError(f"no notes on MIDI channel 10 (drums); channels present: {[c + 1 for c in chans]}. "
                             f"Pass --channel to choose one.")
    report.channels = [channel + 1]
    notes = [(t, n, v) for t, n, v, c in raw if c == channel]
    if not notes:
        raise ValueError(f"no notes on channel {channel + 1}")

    mapped = []
    for t, n, v in notes:
        if n in GM_IMPORT_MAP:
            mapped.append((t, n, v))
        else:
            report.unmapped[n] = report.unmapped.get(n, 0) + 1
    if not mapped:
        raise ValueError("no MIDI notes map to the drum kit")
    strokes, report.graces_folded = _fold_graces(mapped, tpb)
    onsets = [Onset(time=_tick_to_seconds(t, tempo_map, tpb), inst=GM_IMPORT_MAP[n], velocity=v, flam=f, drag=d)
              for t, n, v, f, d in strokes]
    report.notes = len(onsets)
    notes = [(t, n, v) for t, n, v, _, _ in strokes]  # unmapped notes (count-in clicks) don't shape the grid

    # Pickup: explicit, inferred, or none.
    pickup_ticks = 0
    if pickup == "auto":
        strong = [t for t, n, _ in notes if GM_IMPORT_MAP[n] in ("kick", "crash", "crash2", "china")]
        found = _infer_pickup(ts_changes, markers, tpb, strong)
        if found:
            pickup_ticks, report.pickup_reason = found
    elif pickup:
        length = Fraction(pickup)
        opening = ts_changes[0][1]
        if (len(ts_changes) > 1 and ts_changes[0][0] == 0 and opening.bar_length == length
                and ts_changes[1][0] == int(round(length * 4 * tpb))):
            opening = ts_changes[1][1]  # the file's short opening meter is this pickup
        if not 0 < length < opening.bar_length:
            raise ValueError(f"pickup {length} must be shorter than the first bar "
                             f"({opening.bar_length} whole note in {opening}); notes would be lost")
        if (length * 32).denominator != 1:
            raise ValueError(f"pickup {length} is not a whole number of 32nd notes; "
                             f"use a length like 1/4, 3/8 or 1/16")
        pickup_ticks = int(round(length * 4 * tpb))
        report.pickup_reason = "given by the user"
    if pickup_ticks and ts_changes[0][0] == 0 and len(ts_changes) > 1 and ts_changes[1][0] == pickup_ticks \
            and ts_changes[0][1].bar_length < ts_changes[1][1].bar_length:
        ts_changes = ts_changes[1:]  # the short opening meter only described the pickup
        ts_changes[0] = (0, ts_changes[0][1])

    # Beat grid from ticks and time signatures, through one bar after the last note.
    last_tick = max(t for t, _, _ in notes)
    beat_ticks: list[int] = []
    bar_defs: list[BarDef] = []
    tick = 0
    ts_i = 0
    if pickup_ticks:
        # The pickup is the tail of a full bar of the meter that follows it,
        # rounded up to whole beats (an 8th-note pickup shows an 8th rest first).
        ts_real = [t for k, t in ts_changes if k <= pickup_ticks][-1]
        tail, acc = [], 0
        for _, length in reversed(ts_real.beats()):
            if acc >= pickup_ticks:
                break
            tail.append(int(round(length * 4 * tpb)))
            acc += tail[-1]
        report.pickup = Fraction(acc, 4 * tpb)
        bar_defs.append(BarDef(0, ts_real, len(tail)))
        t = pickup_ticks - acc
        for length_ticks in reversed(tail):
            beat_ticks.append(t)
            t += length_ticks
        tick = pickup_ticks
    # One bar past the last note, so a final stroke played a little early still
    # rounds onto the next downbeat (empty trailing bars are dropped later).
    end_tick = last_tick + 4 * tpb
    while tick <= end_tick:
        while ts_i + 1 < len(ts_changes) and ts_changes[ts_i + 1][0] <= tick:
            ts_i += 1
        ts = ts_changes[ts_i][1]
        beats = ts.beats()
        bar_defs.append(BarDef(len(beat_ticks), ts, len(beats)))
        for _, length in beats:
            beat_ticks.append(tick)
            tick += int(round(length * 4 * tpb))
    beat_ticks.append(tick)

    # Optionally drop empty bars before the first stroke (count-ins, silence).
    first_note_tick = min(t for t, _, _ in notes)
    if not keep_leading_silence:
        while len(bar_defs) > 1:
            nxt = bar_defs[1].first_beat
            # Same tolerance as the quantizer: a stroke up to 1/16 beat early belongs to the beat.
            if beat_ticks[nxt] - (beat_ticks[nxt + 1] - beat_ticks[nxt]) // 16 <= first_note_tick:
                drop = bar_defs[1].first_beat
                beat_ticks = beat_ticks[drop:]
                bar_defs = [BarDef(b.first_beat - drop, b.time_sig, b.beats) for b in bar_defs[1:]]
                report.trimmed_leading_bars += 1
            else:
                break

    # Structure that doesn't fit the grid means the barlines are probably wrong.
    bar_starts = {beat_ticks[b.first_beat] for b in bar_defs}
    for t, ts in ts_changes[1:]:
        if t not in bar_starts and t <= last_tick:
            report.warnings.append(
                f"meter change to {ts} at tick {t} falls inside a bar; the file may start with a pickup "
                f"(try --pickup) or the meter map is wrong. The chart's barlines need checking.")

    beat_times = [_tick_to_seconds(t, tempo_map, tpb) for t in beat_ticks]
    opts = options or QuantizeOptions()
    result = quantize(onsets, beat_times, bar_defs, opts)
    if result.dropped:
        report.warnings.append(f"{result.dropped} stroke(s) fell outside the bar grid and were left out")
    measures = result.measures
    # Drop trailing empty bars, and leading ones left when the first stroke was
    # played early enough to round onto the next downbeat.
    while len(measures) > 1 and not measures[-1].hits:
        measures.pop()
    while not keep_leading_silence and len(measures) > 1 and not measures[0].hits:
        measures.pop(0)
        bar_defs = bar_defs[1:]
        report.trimmed_leading_bars += 1
    # The grid rounds a pickup up to whole beats; a shorter one (an 8th before the
    # downbeat) is written at its real length, without the leading rest.
    if pickup_ticks and measures[0].is_pickup and bar_defs[0].first_beat == 0:
        exact = Fraction(pickup_ticks, 4 * tpb)
        shift = measures[0].actual_length - exact
        if 0 < shift and all(h.pos >= shift for h in measures[0].hits):
            measures[0].length = exact
            for h in measures[0].hits:
                h.pos -= shift
            report.pickup = exact
    # Tempo marks from the MIDI tempo map are exact; prefer them over beat-interval estimates.
    for m in measures:
        m.tempo = None
    starts = [b.first_beat for b in bar_defs]
    current = None
    snap = tpb // 16  # a tempo event this close after a barline belongs to it
    for i, m in enumerate(measures):
        tick_at = beat_ticks[starts[i]]
        bpm = round(mido.tempo2bpm(_tempo_at(tempo_map, tick_at + snap)), 2)
        # A tempo-mapped performance moves by a BPM or so every beat; mark only real changes.
        if current is None or abs(bpm - current) / current >= TEMPO_MARK_CHANGE:
            m.tempo = bpm
            current = bpm
    bar_ticks_all = [beat_ticks[b.first_beat] for b in bar_defs]
    for t, _ in tempo_map[1:]:
        if t > last_tick or any(0 <= t - bt <= snap for bt in bar_ticks_all):
            continue
        k = max((i for i, bt in enumerate(bar_ticks_all) if bt <= t), default=0)
        report.warnings.append(f"tempo change at tick {t} falls inside bar {k + 1}; the chart shows it from "
                               f"bar {k + 2}")
    # Section names from markers (DAW / e-kit files often have them).
    bar_tick = [beat_ticks[b.first_beat] for b in bar_defs][:len(measures)]
    for t, text in markers:
        k = max((i for i, bt in enumerate(bar_tick) if bt <= t), default=None)
        if k is not None:
            if bar_tick[k] != t:
                report.warnings.append(f"marker {text!r} at tick {t} is not on a barline; placed at bar {k + 1}")
            measures[k].section = text
    name = title or (track_names[0] if track_names else Path(path).stem)
    # The strokes are the player's, but barlines and quantization are automatic.
    score = Score(measures=measures, title=name, chart_type="full_transcription",
                  status="unverified_import", source=f"MIDI file {Path(path).name}")
    score.swing = result.feel == "swing"
    score.analysis = {
        "input": "midi",
        "notes": report.notes,
        "unmapped_notes": {str(k): v for k, v in report.unmapped.items()},
        "feel": result.feel,
        "merged_duplicates": result.merged,
        "mean_abs_offset_ms": result.mean_abs_offset_ms,
        "grid_counts": result.grid_counts,
    }
    if report.pickup:
        score.analysis["pickup"] = f"{report.pickup} ({report.pickup_reason})"
    if report.warnings:
        score.analysis["notes"] = list(report.warnings)
    if result.feel == "swing":
        measures[0].tempo_text = "Swing"
    return score, report
