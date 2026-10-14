"""Playability: strokes one drummer can't play together are found, and only those."""

from fractions import Fraction as F

from drum_agent.charts import compile_spec
from drum_agent.model import Hit, Measure, Score, TimeSig
from drum_agent.playability import check, describe, flag_bars


def bar(hits, tempo=100.0):
    return Score([Measure(TimeSig(4, 4), hits, tempo=tempo)])


def kinds(score):
    return [(i.bar, i.pos, i.kind) for i in check(score)]


def test_a_normal_groove_is_playable():
    s = compile_spec({"tempo": 120, "sections": [{"bars": [{
        "hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-----x-x-------", "hf": "--x---x---x---x-"}]}]})
    assert check(s) == []


def test_three_hands_at_once():
    s = bar([Hit(F(0), "hihat"), Hit(F(0), "snare"), Hit(F(0), "crash"), Hit(F(0), "kick")])
    assert kinds(s) == [(0, F(0), "hands")]
    assert "3 hands" in check(s)[0].message


def test_a_flam_takes_both_hands():
    ok = bar([Hit(F(0), "snare", flam=True), Hit(F(0), "kick")])
    assert check(ok) == []
    bad = bar([Hit(F(0), "snare", flam=True), Hit(F(0), "hihat")])
    assert kinds(bad) == [(0, F(0), "hands")]


def test_left_foot_conflicts():
    s = bar([Hit(F(0), "hihat_pedal"), Hit(F(0), "kick2"), Hit(F(0), "kick")])
    assert kinds(s) == [(0, F(0), "feet")]
    assert check(bar([Hit(F(0), "kick"), Hit(F(0), "kick2")])) == []  # double pedal: both feet


def test_open_hihat_as_the_foot_closes_it():
    s = bar([Hit(F(1, 4), "hihat_open"), Hit(F(1, 4), "hihat_pedal")])
    assert kinds(s) == [(0, F(1, 4), "hihat")]


def test_strokes_inside_a_two_handed_roll():
    s = bar([Hit(F(0), "snare", roll=F(1, 2)), Hit(F(1, 4), "hihat"), Hit(F(1, 4), "kick")])
    assert kinds(s) == [(0, F(1, 4), "roll")]  # the kick under the roll is fine


def test_single_strokes_too_fast_for_one_hand():
    # 64ths at 200 BPM are 19 ms apart: a roll, not single strokes on one drum.
    hits = [Hit(F(k, 64), "snare") for k in range(4)]
    s = bar(hits, tempo=200.0)
    assert {i.kind for i in check(s)} == {"speed"}
    assert check(bar([Hit(F(k, 16), "snare") for k in range(4)], tempo=200.0)) == []


def test_flag_bars_marks_bars_for_review():
    s = Score([Measure(TimeSig(4, 4), [Hit(F(0), "kick")], tempo=100.0),
               Measure(TimeSig(4, 4), [Hit(F(0), "hihat"), Hit(F(0), "snare"), Hit(F(0), "ride")])])
    assert flag_bars(s, check(s)) == 1
    assert not s.measures[0].uncertain and s.measures[1].uncertain
    assert any("not playable" in n for n in s.measures[1].notes)
    assert describe(s, check(s)) == ["score bar 2, beat 1: 3 hands needed at once (hihat, ride, snare)"]
