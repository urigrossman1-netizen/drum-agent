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


# Event order at equal ticks: meta first, then note-offs, then grace notes, then
# strokes, so a stroke that ends exactly where the next one starts never cancels it.
_META, _OFF, _GRACE, _ON = 0, 3, 4, 5
GRACE_GAP_TICKS = TICKS_PER_BEAT // 16  # 1/64 note; verify.GRACE_GAP must match


def _velocity(h) -> int:
    if h.ghost:
        return min(h.velocity, 40) if h.velocity != 90 else 35
    if h.accent:
        return max(h.velocity, 115) if h.velocity != 90 else 120
    if h.inst == "hihat_half":  # spec §5: same note as open, played softer
        return min(h.velocity, 70)
    return h.velocity


def pickup_time_signature(length: Fraction, den: int) -> tuple[int, int] | None:
    """MIDI time signature for a pickup bar of `length` whole notes (None if it has none)."""
    while den <= 64:
        n = length * den
        if n.denominator == 1:
            return int(n), den
        den *= 2
    return None


def performed_bar_starts(score: Score) -> list[float]:
    """Seconds at which each bar starts on the recording's clock.

    Bars from audio carry start_time; others (and hits a human added) are placed
    after the previous bar at the bar's tempo, so everything shares one clock.
    """
    out: list[float] = []
    for i, m in enumerate(score.measures):
        if m.start_time is not None:
            out.append(float(m.start_time))
        elif out:
            prev = score.measures[i - 1]
            out.append(out[-1] + float(prev.actual_length) * 4 * 60 / score.tempo_at(i - 1))
        else:
            out.append(0.0)
    return out


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

    def on_off(tick: int, length: int, note: int, vel: int, order: int) -> None:
        events.append((tick, order, mido.Message("note_on", channel=CHANNEL, note=note, velocity=vel)))
        events.append((tick + length, _OFF, mido.Message("note_off", channel=CHANNEL, note=note, velocity=0)))

    if timing == "quantized":
        prev_ts = None
        if not score.measures or score.measures[0].tempo is None:
            # Bar 1 without a mark plays at the tempo the model assumes (120), not the
            # reader's default, and the file says so explicitly.
            events.append((0, _META, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(score.initial_tempo))))
        for i, m in enumerate(score.measures):
            tick = whole_to_ticks(starts[i])
            if m.tempo is not None:
                events.append((tick, _META, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(m.tempo))))
            ts = (m.time_sig.num, m.time_sig.den)
            short = pickup_time_signature(m.actual_length, m.time_sig.den) if i == 0 and m.is_pickup else None
            if short is not None:
                # A pickup gets its own short meter, so readers put bar 2 on a barline;
                # the real meter follows at bar 2.
                events.append((tick, _META, mido.MetaMessage("time_signature", numerator=short[0], denominator=short[1])))
                prev_ts = short
            elif ts != prev_ts:
                events.append((tick, _META, mido.MetaMessage("time_signature", numerator=ts[0], denominator=ts[1])))
                prev_ts = ts
            if m.section:
                events.append((tick, _META, mido.MetaMessage("marker", text=m.section)))
    else:
        events.append((0, _META, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120))))

    bar_secs = performed_bar_starts(score) if timing == "performed" else []
    for i, m, h in score.iter_hits():
        note = kit[h.inst].midi
        vel = _velocity(h)
        if timing == "quantized":
            on = whole_to_ticks(starts[i] + h.pos)
            # Stroke length in ticks: a 32nd at the bar's tempo, shortened for chokes.
            length = whole_to_ticks(NOTE_LEN)
            stroke = whole_to_ticks(Fraction(1, 32))
        else:
            sec_per_whole = 4 * 60 / score.tempo_at(i)
            t = h.time if h.time is not None else bar_secs[i] + float(h.pos) * sec_per_whole
            on = int(round(t * 2 * TICKS_PER_BEAT))  # 120 BPM: 2 beats per second
            length = TICKS_PER_BEAT // 8
            stroke = int(round(sec_per_whole / 32 * 2 * TICKS_PER_BEAT))
        # Grace notes that would start before the file are left out (not merged
        # into the main stroke); verify.expected_midi_keys applies the same rule.
        graces = ([1] if h.flam else []) + ([2, 1] if h.drag else [])
        for k in graces:
            t0 = on - k * GRACE_GAP_TICKS
            if t0 >= 0:
                on_off(t0, GRACE_GAP_TICKS // 2, note, max(1, vel // 2), _GRACE)
        if h.roll is not None:
            if timing == "quantized":
                end = on + whole_to_ticks(h.roll)
            else:
                end = on + int(round(float(h.roll) * sec_per_whole * 2 * TICKS_PER_BEAT))
            t0 = on
            while t0 < end:
                on_off(t0, stroke // 2, note, vel if t0 == on else max(1, int(vel * 0.75)), _ON)
                t0 += stroke
            continue
        if h.choke:
            length = whole_to_ticks(Fraction(1, 16))
        on_off(on, length, note, vel, _ON)

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
