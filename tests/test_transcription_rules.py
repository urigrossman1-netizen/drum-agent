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
    assert _find_downbeat_shift(bars, ms) == (12, 2)


def test_two_shifts_are_found_one_after_the_other():
    bars, ms = bars_with_crashes({0: F(0), 4: F(0), 8: F(1, 2), 12: F(1, 2), 16: F(1, 4), 20: F(1, 4)})
    assert _find_downbeat_shift(bars, ms) == (8, 2)
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
