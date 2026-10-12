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
    warnings: list[str] = field(default_factory=list)


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


def _infer_pickup(ts_changes: list[tuple[int, TimeSig]], markers: list[tuple[int, str]],
                  tpb: int) -> tuple[int, str] | None:
    """Pickup length in ticks, inferred from the file's own bar structure, or None."""
    # Notation programs (and our own writer) export a pickup as a short opening meter.
    if len(ts_changes) >= 2 and ts_changes[0][0] == 0:
        (t0, ts0), (t1, ts1) = ts_changes[0], ts_changes[1]
        if t1 == _bar_ticks(ts0, tpb) and ts0.bar_length < ts1.bar_length:
            return t1, f"the file opens with one {ts0} bar before {ts1}"
    # Meter changes and section markers belong on barlines. If they all sit the
    # same distance after the barlines counted from tick 0, the music starts
    # with a pickup of that length.
    anchors = sorted({t for t, _ in ts_changes[1:]} | {t for t, _ in markers if t > 0})
    if not anchors:
        return None
    d = anchors[0] % _bar_ticks(ts_changes[0][1], tpb)
    if d == 0:
        return None
    if set(anchors) <= _barlines(ts_changes, d, anchors[-1], tpb):
        return d, "meter changes/markers fall that far after the barlines counted from the start"
    return None


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
    changes.sort()
    if not changes or changes[0][0] != 0:
        changes.insert(0, (0, 500000))
    return changes


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


def read_midi(path: str | Path, channel: int | None = None, options: QuantizeOptions | None = None,
              title: str | None = None, keep_leading_silence: bool = False,
              pickup: Fraction | str | None = "auto") -> tuple[Score, MidiImportReport]:
    """Import a drum track. `pickup`: length of an anacrusis in whole notes, "auto"
    (infer it from a short opening meter or from off-barline meter changes and
    markers), or None/0 for none."""
    mid = mido.MidiFile(str(path))
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
    ts_changes.sort(key=lambda x: x[0])
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

    onsets: list[Onset] = []
    for t, n, v in notes:
        inst = GM_IMPORT_MAP.get(n)
        if inst is None:
            report.unmapped[n] = report.unmapped.get(n, 0) + 1
            continue
        onsets.append(Onset(time=_tick_to_seconds(t, tempo_map, tpb), inst=inst, velocity=v))
    report.notes = len(onsets)
    if not onsets:
        raise ValueError("no MIDI notes map to the drum kit")

    # Pickup: explicit, inferred, or none.
    pickup_ticks = 0
    if pickup == "auto":
        found = _infer_pickup(ts_changes, markers, tpb)
        if found:
            pickup_ticks, report.pickup_reason = found
    elif pickup:
        pickup_ticks = int(round(Fraction(pickup) * 4 * tpb))
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
    while tick <= last_tick:
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
            if beat_ticks[nxt] - tpb // 16 <= first_note_tick:
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
    measures = result.measures
    # Drop trailing empty bars.
    while len(measures) > 1 and not measures[-1].hits:
        measures.pop()
    # Tempo marks from the MIDI tempo map are exact; prefer them over beat-interval estimates.
    for m in measures:
        m.tempo = None
    starts = [b.first_beat for b in bar_defs]
    current = None
    for i, m in enumerate(measures):
        tick_at = beat_ticks[starts[i]]
        tempo_us = [tm for t, tm in tempo_map if t <= tick_at][-1]
        bpm = round(mido.tempo2bpm(tempo_us), 2)
        if bpm != current:
            m.tempo = bpm
            current = bpm
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
