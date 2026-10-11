"""MIDI writer: Score -> Standard MIDI File (GM drums, channel 10).

Built directly from the IR in performance order (no repeat compression), so
it is an independent check on the layout plan. Two timing modes:

* "quantized": notes at their notated positions with the score's tempo map.
* "performed": notes at the original onset times (Hit.time) where available,
  at a fixed 120 BPM grid, preserving the drummer's timing.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import mido

from ..kit import DEFAULT_KIT, Kit
from ..model import Score

TICKS_PER_BEAT = 960
CHANNEL = 9  # GM percussion (channel 10, zero-based 9)
NOTE_LEN = Fraction(1, 32)  # notated length of a drum stroke in whole notes


def _velocity(h) -> int:
    if h.ghost:
        return min(h.velocity, 40) if h.velocity != 90 else 35
    if h.accent:
        return max(h.velocity, 115) if h.velocity != 90 else 120
    return h.velocity


def build_midi(score: Score, kit: Kit = DEFAULT_KIT, timing: str = "quantized") -> mido.MidiFile:
    if timing not in ("quantized", "performed"):
        raise ValueError("timing must be 'quantized' or 'performed'")
    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT, type=1)
    meta = mido.MidiTrack()
    drums = mido.MidiTrack()
    mid.tracks += [meta, drums]
    meta.append(mido.MetaMessage("track_name", name=score.title, time=0))
    drums.append(mido.MetaMessage("track_name", name="Drum Set", time=0))

    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []  # (tick, order, msg)
    starts = score.measure_starts()

    def whole_to_ticks(pos: Fraction) -> int:
        return int(round(pos * 4 * TICKS_PER_BEAT))

    if timing == "quantized":
        prev_ts = None
        for i, m in enumerate(score.measures):
            tick = whole_to_ticks(starts[i])
            if m.tempo is not None:
                events.append((tick, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(m.tempo))))
            ts = (m.time_sig.num, m.time_sig.den)
            if ts != prev_ts:
                events.append((tick, 1, mido.MetaMessage("time_signature", numerator=ts[0], denominator=ts[1])))
                prev_ts = ts
            if m.section:
                events.append((tick, 2, mido.MetaMessage("marker", text=m.section)))
    else:
        events.append((0, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120))))

    sec_starts = score.measure_start_seconds()
    for i, m, h in score.iter_hits():
        note = kit[h.inst].midi
        vel = _velocity(h)
        if timing == "quantized":
            on = whole_to_ticks(starts[i] + h.pos)
            # Stroke length in ticks: a 32nd at the bar's tempo, shortened for chokes.
            length = whole_to_ticks(NOTE_LEN)
        else:
            t = h.time if h.time is not None else sec_starts[i] + float(h.pos) * 4 * 60 / score.tempo_at(i)
            on = int(round(t * 2 * TICKS_PER_BEAT))  # 120 BPM: 2 beats per second
            length = TICKS_PER_BEAT // 8
        grace_gap = TICKS_PER_BEAT // 16
        if h.flam:
            events.append((max(0, on - grace_gap), 3, mido.Message("note_on", channel=CHANNEL, note=note, velocity=max(1, vel // 2))))
            events.append((max(0, on - grace_gap) + grace_gap // 2, 4, mido.Message("note_off", channel=CHANNEL, note=note, velocity=0)))
        if h.drag:
            for k in (2, 1):
                t0 = max(0, on - k * grace_gap)
                events.append((t0, 3, mido.Message("note_on", channel=CHANNEL, note=note, velocity=max(1, vel // 2))))
                events.append((t0 + grace_gap // 2, 4, mido.Message("note_off", channel=CHANNEL, note=note, velocity=0)))
        if h.roll is not None and timing == "quantized":
            stroke = whole_to_ticks(Fraction(1, 32))
            end = on + whole_to_ticks(h.roll)
            t0 = on
            while t0 < end:
                events.append((t0, 5, mido.Message("note_on", channel=CHANNEL, note=note, velocity=vel if t0 == on else max(1, int(vel * 0.75)))))
                events.append((t0 + stroke // 2, 4, mido.Message("note_off", channel=CHANNEL, note=note, velocity=0)))
                t0 += stroke
            continue
        if h.choke:
            length = whole_to_ticks(Fraction(1, 16))
        events.append((on, 5, mido.Message("note_on", channel=CHANNEL, note=note, velocity=vel)))
        events.append((on + length, 4, mido.Message("note_off", channel=CHANNEL, note=note, velocity=0)))

    events.sort(key=lambda e: (e[0], e[1]))
    last = {"meta": 0, "drums": 0}
    for tick, _, msg in events:
        track = meta if msg.is_meta else drums
        key = "meta" if msg.is_meta else "drums"
        msg.time = tick - last[key]
        last[key] = tick
        track.append(msg)
    end_tick = whole_to_ticks(sum((m.actual_length for m in score.measures), Fraction(0)))
    meta.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last["meta"])))
    drums.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last["drums"])))
    return mid


def write_midi(score: Score, path: str | Path, kit: Kit = DEFAULT_KIT, timing: str = "quantized") -> Path:
    path = Path(path)
    build_midi(score, kit, timing).save(str(path))
    return path
