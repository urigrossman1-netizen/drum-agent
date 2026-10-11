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
              title: str | None = None, keep_leading_silence: bool = False) -> tuple[Score, MidiImportReport]:
    mid = mido.MidiFile(str(path))
    tpb = mid.ticks_per_beat
    report = MidiImportReport()
    tempo_map = _tempo_map(mid)

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

    # Beat grid from ticks and time signatures, through one bar after the last note.
    last_tick = max(t for t, _, _ in notes)
    beat_ticks: list[int] = []
    bar_defs: list[BarDef] = []
    tick = 0
    ts_i = 0
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
    name = title or (track_names[0] if track_names else Path(path).stem)
    score = Score(measures=measures, title=name, chart_type="full_transcription",
                  status="verified", source=f"MIDI file {Path(path).name}")
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
    if result.feel == "swing":
        measures[0].tempo_text = "Swing"
    return score, report
