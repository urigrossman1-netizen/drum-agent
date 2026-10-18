"""Unit tests for structural rules in the audio pipeline (no audio needed).

These pin rules whose effect was measured end to end with
scripts/eval_notation.py; the tests keep their behaviour from drifting.
"""

from fractions import Fraction as F

from drum_agent.audio.detect import DrumHit, _drop_flam_crashes
from drum_agent.audio.transcribe import _find_downbeat_shift, _repetition_score
from drum_agent.model import Hit, Measure, TimeSig
from drum_agent.quantize import BarDef

TS = TimeSig(4, 4)


def hit(t, inst, flam=False):
    return DrumHit(t, inst, 1.0, 90, 0.9, flam=flam)


# --- false crashes from flams ----------------------------------------------------

def test_crash_on_a_flam_grace_or_flammed_stroke_is_dropped():
    hits = [hit(1.000, "crash"), hit(1.040, "snare", flam=True),  # grace position, no kick
            hit(2.000, "crash"), hit(2.000, "snare", flam=True)]  # accented flam, no kick
    assert [h.inst for h in _drop_flam_crashes(hits)] == ["snare", "snare"]


def test_real_crashes_survive():
    hits = [hit(0.0, "crash"), hit(0.0, "kick"),  # phrase start: crash + kick
            hit(1.0, "crash"), hit(1.0, "snare"),  # crash with a plain snare stroke
            hit(3.0, "crash"), hit(3.0, "kick"), hit(3.03, "snare", flam=True)]  # crash + kick, flam after
    assert sum(h.inst == "crash" for h in _drop_flam_crashes(hits)) == 3


# --- downbeat shifts ----------------------------------------------------------------

def bars_with_crashes(crash_at: dict[int, F], n: int = 24):
    bars = [BarDef(4 * i, TS, 4) for i in range(n)]
    measures = []
    for i in range(n):
        hits = [Hit(F(1, 4), "snare"), Hit(F(3, 4), "snare")]
        if i in crash_at:
            hits += [Hit(crash_at[i], "crash"), Hit(crash_at[i], "kick")]
        measures.append(Measure(TS, hits))
    return bars, measures


def test_shift_found_where_crashes_move_to_beat_three():
    bars, ms = bars_with_crashes({0: F(0), 4: F(0), 8: F(0), 12: F(1, 2), 16: F(1, 2), 20: F(1, 2)})
    assert _find_downbeat_shift(bars, ms) == (12, 2, 24)


def test_two_shifts_are_found_one_after_the_other():
    bars, ms = bars_with_crashes({0: F(0), 4: F(0), 8: F(1, 2), 12: F(1, 2), 16: F(1, 4), 20: F(1, 4)})
    assert _find_downbeat_shift(bars, ms) == (8, 2, 16)  # governs bars 8-15
    # The next change (beat 3 -> beat 2) is only judged after bar 8 is re-barred and
    # re-quantized, when the outro's crashes sit off beat 1 of the corrected barring.
    assert _find_downbeat_shift(bars, ms, after_bar=8) is None


def test_single_accent_crash_is_not_a_shift():
    bars, ms = bars_with_crashes({0: F(0), 4: F(0), 6: F(1, 2), 8: F(0), 12: F(0)})
    assert _find_downbeat_shift(bars, ms) is None


def test_not_enough_evidence_is_not_a_shift():
    bars, ms = bars_with_crashes({0: F(0), 12: F(1, 2), 16: F(1, 2)})  # one downbeat crash only
    assert _find_downbeat_shift(bars, ms) is None
    bars, ms = bars_with_crashes({0: F(0), 4: F(0), 12: F(1, 2)})  # one crash after
    assert _find_downbeat_shift(bars, ms) is None


def test_repetition_score_prefers_bars_that_repeat_earlier_ones():
    a = Measure(TS, [Hit(F(k, 8), "hihat") for k in range(8)] + [Hit(F(1, 4), "snare"), Hit(F(0), "kick")])
    b = Measure(TS, [Hit(F(k, 8), "ride") for k in range(8)] + [Hit(F(1, 2), "snare")])
    assert _repetition_score([a, a, a, a], 2, 2) == 1.0
    assert _repetition_score([a, a, b, b], 2, 2) < 0.2


def test_bars_with_near_misses_are_flagged():
    # A class the classifier almost accepted (half its threshold or more) marks a likely
    # missed stroke: its bar is flagged and the note names the instrument.
    from drum_agent.audio.transcribe import NEAR_FLAG, _flag_near_misses
    from drum_agent.model import Measure, TimeSig
    bars = [Measure(time_sig=TimeSig(4, 4), start_time=2.0 * i) for i in range(3)]
    near = [(0.5, "snare", NEAR_FLAG + 0.1),   # bar 1
            (2.4, "tom", NEAR_FLAG - 0.1),     # too far below its threshold: no flag
            (3.9, "crash", 0.9)]               # bar 2
    assert _flag_near_misses(bars, near) == 2
    assert [m.uncertain for m in bars] == [True, True, False]
    assert "snare" in bars[0].notes[-1] and "crash" in bars[1].notes[-1]
    near_downbeat = [(5.98, "kick", 0.8)]  # within 30 ms before a barline: the next bar's downbeat
    assert _flag_near_misses(bars, near_downbeat) == 1 and bars[2].uncertain


# --- tempo: near ties ---------------------------------------------------------------

def strokes(bpm0, bpm1, seconds, pattern, seed=1):
    """Synthetic strokes for the beat tracker, the tempo moving linearly from bpm0 to bpm1.
    pattern(beat, rng, add) calls add(fraction of the beat, inst, strength, ghost)."""
    import random
    rng = random.Random(seed)
    out, t, beat = [], 0.2, 0
    while t < seconds:
        p = 60 / (bpm0 + (bpm1 - bpm0) * t / seconds)
        pattern(beat, rng, lambda frac, inst, s=1.0, ghost=False:
                out.append(DrumHit(t + frac * p + rng.gauss(0, 0.01), inst, s, 80, 0.9, ghost=ghost)))
        t += p
        beat += 1
    return sorted(out, key=lambda h: h.time)


def tracked_tempo(hits, seconds):
    from drum_agent.audio.beats import drum_envelope, track_beats
    from drum_agent.audio.features import HOP, SR
    return track_beats(drum_envelope(hits, int(seconds * SR / HOP) + 10), seconds, None, hits)[0]


def test_steady_swing_is_not_read_at_three_quarter_tempo():
    # Ride on every beat, the skip note on the last triplet of 2 and 4, hi-hat foot on 2 and
    # 4, some comping. Swung 8ths fall exactly on a constant 16th grid at 3/4 of the tempo,
    # so re-ranking near ties by their constant grids moved this 120 BPM take to 90.
    def jazz_ride(beat, rng, add):
        add(0, "ride", 0.8)
        if beat % 2:
            add(2 / 3, "ride", 0.6)
            add(0, "hihat_pedal", 0.7)
        if rng.random() < 0.3:
            add(rng.choice([0, 2 / 3]), "snare", 0.4, ghost=True)
        if rng.random() < 0.15:
            add(2 / 3, "kick", 0.6)
    assert abs(tracked_tempo(strokes(120, 120, 20, jazz_ride), 20) / 120 - 1) < 0.04


def test_a_slowing_take_keeps_its_metrical_level():
    def roll_groove(beat, rng, add):  # 8 snare strokes a beat, kick on 1 and 3, crash on 1
        for k in range(8):
            add(k / 8, "snare", 0.5)
        if beat % 2 == 0:
            add(0, "kick")
        if beat % 4 == 0:
            add(0, "crash")
    assert 100 <= tracked_tempo(strokes(130, 100, 30, roll_groove), 30) <= 130  # it was 88, 3/4 of the tempo
