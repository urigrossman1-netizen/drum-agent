"""Rhythm spelling: notes, rests, tuplets, beams and ties (NOTATION_SPEC §4)."""

import random
from fractions import Fraction as F

import pytest

from drum_agent.charts import compile_spec
from drum_agent.model import Hit, Measure, TimeSig
from drum_agent.kit import DEFAULT_KIT
from drum_agent.rhythm import SpellingError, check_tokens, spell_measure, spell_voice

# The rhythm rules are the same in every voicing. These tests were written with
# snare and toms in the stems-up voice, i.e. the hands-up (Weinberg/PAS) voicing.
HANDS_UP = DEFAULT_KIT.with_voicing("hands-up")


def spell_hu(m):
    return spell_measure(m, HANDS_UP)


def bar(pattern: dict, time: str = "4/4", length=None) -> Measure:
    spec = {"time": time, "sections": [{"bars": [dict(pattern, **({"length": length} if length else {}))]}]}
    if length:
        spec["pickup"] = length
    return compile_spec(spec).measures[0]


def shape(tokens):
    """(kind, pos, written value, dots, tuplet) per token."""
    return [(t.kind, t.pos, t.value, t.dots, t.tuplet) for t in tokens]


def values(tokens):
    out = []
    for t in tokens:
        v = f"{'r' if t.kind != 'note' else 'x'}{(1 / t.value).numerator}{'.' * t.dots}"
        out.append(v)
    return " ".join(out)


# --- 1. quarter-note groove ----------------------------------------------------

def test_quarter_groove():
    m = bar({"sn": "-x-x", "bd": "x-x-"})
    sm = spell_hu(m)
    assert values(sm.voices[1]) == "r4 x4 r4 x4"
    assert values(sm.voices[2]) == "x4 r4 x4 r4"


# --- 2. eighth notes and beaming ------------------------------------------------

def test_eighth_rock_beams_in_fours():
    m = bar({"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x---x---"})
    v1 = spell_hu(m).voices[1]
    assert values(v1) == "x8 x8 x8 x8 x8 x8 x8 x8"
    assert [t.beams[1] for t in v1] == ["begin", "continue", "continue", "end"] * 2
    assert [len(t.hits) for t in v1] == [1, 1, 2, 1, 1, 1, 2, 1]  # snare+hat chords


def test_eighths_beam_per_beat_when_mixed_with_sixteenths():
    m = bar({"hh": "x-x-xxx-x-x-x-x-"})
    v1 = spell_hu(m).voices[1]
    assert values(v1) == "x8 x8 x16 x16 x8 x8 x8 x8 x8"
    begins = [t.pos for t in v1 if t.beams.get(1) == "begin"]
    assert begins == [F(0), F(1, 4), F(1, 2)]  # beat 2 has 16ths, so beats 1 and 2 are separate


# --- 3. sixteenths and syncopation ----------------------------------------------

def test_sixteenth_syncopation():
    m = bar({"bd": "x--x--x---x--x--"})
    v2 = spell_hu(m).voices[2]
    assert values(v2) == "x8. x16 r8 x8 r8 x8 r16 x8."
    check_tokens(v2, m)


def test_sixteenth_eighth_sixteenth():
    m = bar({"sn": "xx-x" + "-x-x" + "-xx-" + "x---"})
    assert values(spell_hu(m).voices[1]) == "x16 x8 x16 r16 x8 x16 r16 x16 x8 x4"


def test_hooks_for_dotted_rhythms():
    v = spell_hu(bar({"sn": "x--x" + "x--x" + "-x--" + "x---"})).voices[1]
    assert v[0].beams == {1: "begin"} and v[1].beams == {1: "end", 2: "backward hook"}
    assert values(v) == "x8. x16 x8. x16 r16 x8. x4"
    third_beat = [t for t in v if F(1, 2) <= t.pos < F(3, 4)]
    assert all(not t.beams for t in third_beat)  # a lone note in a beat is flagged, not beamed


# --- 4/rests: metrical hierarchy ------------------------------------------------

@pytest.mark.parametrize("pattern,expected", [
    ("x---------------", "x4 r4 r2"),
    ("----x-----------", "r4 x4 r2"),
    ("--------x-------", "r2 x4 r4"),
    ("------------x---", "r2 r4 x4"),
    ("--------------x-", "r2 r4 r8 x8"),
    ("-x--------------", "r16 x8. r4 r2"),
    ("---x------------", "r8 r16 x16 r4 r2"),
])
def test_rest_hierarchy_4_4(pattern, expected):
    v = spell_hu(bar({"bd": pattern})).voices[2]
    assert values(v) == expected


def test_no_half_rest_across_middle_of_bar():
    for _ in range(300):
        pat = "".join(random.choice("x---") for _ in range(16))
        v = spell_hu(bar({"bd": pat})).voices[2] if "x" in pat else []
        for t in v:
            if t.kind == "rest" and t.value == F(1, 2):
                assert t.pos in (0, F(1, 2)), (pat, v)


def test_empty_bar_and_silent_voice():
    sm = spell_hu(bar({"sn": "----", "bd": "----"}))
    assert sm.shared_rest and sm.voices[1][0].kind == "measure_rest" and not sm.voices[2]
    sm = spell_hu(bar({"bd": "x-x-"}))
    assert sm.voices[1][0].kind == "measure_rest" and not sm.shared_rest


# --- tuplets --------------------------------------------------------------------

def test_eighth_triplets_and_mixed_bar():
    v = spell_hu(bar({"sn": "xxx|x-x|xxxx|xxxxxx"})).voices[1]
    assert values(v) == "x8 x8 x8 x4 x8 x16 x16 x16 x16 x16 x16 x16 x16 x16 x16"
    assert [t.tuplet for t in v[:5]] == [(3, 2)] * 5
    assert [t.tuplet for t in v[-6:]] == [(6, 4)] * 6  # sextuplet, labelled 6
    assert v[0].tuplet_start and v[2].tuplet_stop and v[3].tuplet_start and v[4].tuplet_stop


def test_quarter_note_triplets_span_half_bar():
    m = bar({"t1": "x---x---x---" + "x--x--x--x--"})
    v = spell_hu(m).voices[1]
    assert values(v) == "x4 x4 x4 x8 x8 x8 x8"
    assert v[0].tuplet == (3, 2) and v[0].tuplet_start and v[2].tuplet_stop
    assert v[0].value == F(1, 4) and v[0].dur == F(1, 6)


def test_lone_stroke_on_quarter_triplet_grid_uses_eighth_triplets():
    # Kick on the "let" of 3 in a shuffle: 8th triplets, not a quarter-note triplet.
    v = spell_hu(bar({"bd": "x--|---|--x|---"})).voices[2]
    assert values(v) == "x4 r4 r4 x8 r4"
    assert all(t.tuplet in (None, (3, 2)) for t in v)
    assert v[2].tuplet == (3, 2) and v[2].value == F(1, 4) and v[2].dur == F(1, 6)
    # Both inner points present: a genuine quarter-note-triplet figure.
    v = spell_hu(bar({"bd": "x--|---|--x|-x-"})).voices[2]
    assert values(v) == "x4 r4 r4 x4 x4"
    assert v[2].tuplet_start and v[4].tuplet_stop


def test_compound_two_even_strokes_are_dotted_eighths():
    # Spec grid order for compound beats is 1, 3, 6, 2, 4, 12: dotted 8ths before duplets.
    v = spell_hu(bar({"sn": "xx|x"}, time="6/8")).voices[1]
    assert values(v) == "x8. x8. x4."
    assert v[0].tuplet is None


def test_compound_quadruplets():
    v = spell_hu(bar({"sn": "xxxx|x"}, time="6/8")).voices[1]
    assert values(v) == "x16 x16 x16 x16 x4."
    assert v[0].tuplet == (4, 6) and v[0].tuplet_start and v[3].tuplet_stop


def test_quintuplets_are_rejected_explicitly():
    m = Measure(TimeSig(4, 4), [Hit(F(k, 20), "snare") for k in range(5)])
    with pytest.raises(SpellingError):
        spell_hu(m)


# --- 32nds ----------------------------------------------------------------------

def test_thirty_seconds_and_half_beat_cap():
    v = spell_hu(bar({"sn": "xxxxxxxx|x---|x-x-|x"})).voices[1]
    assert values(v) == "x32 x32 x32 x32 x32 x32 x32 x32 x4 x8 x8 x4"
    assert v[0].beams == {1: "begin", 2: "begin", 3: "begin"}
    # A note starting on an off-32nd may not hide the 8th subdivision.
    m = Measure(TimeSig(4, 4), [Hit(F(1, 32), "snare"), Hit(F(7, 32), "snare")])
    v = spell_hu(m).voices[1]
    assert values(v) == "r32 x16. r16 r32 x32 r4 r2"


# --- compound, irregular, pickup ------------------------------------------------

def test_six_eight():
    assert values(spell_hu(bar({"bd": "x-----"}, "6/8")).voices[2]) == "x4. r4."
    assert values(spell_hu(bar({"bd": "-x----"}, "6/8")).voices[2]) == "r8 x4 r4."
    assert values(spell_hu(bar({"bd": "x-x--x"}, "6/8")).voices[2]) == "x4 x8 r4 x8"


def test_twelve_eight_rests():
    assert values(spell_hu(bar({"bd": "x-----------"}, "12/8")).voices[2]) == "x4. r4. r2."


def test_seven_eight_groups_2_2_3():
    v = spell_hu(bar({"hh": "xxxxxxx"}, "7/8")).voices[1]
    assert [t.beams[1] for t in v] == ["begin", "end", "begin", "end", "begin", "continue", "end"]


def test_five_eight_groups_2_3():
    v = spell_hu(bar({"bd": "x-x--"}, "5/8")).voices[2]
    assert values(v) == "x4 x4."


def test_pickup_bar():
    m = bar({"sn": "xxxx"}, length="1/4")
    assert m.is_pickup
    v = spell_hu(m).voices[1]
    assert values(v) == "x16 x16 x16 x16" and v[0].pos == 0
    check_tokens(v, m)


# --- rolls ------------------------------------------------------------------------

def test_roll_half_bar_is_one_half_note():
    v = spell_hu(bar({"sn": "x---x---r~~~~~~~"})).voices[1]
    assert values(v) == "x4 x4 x2"
    assert v[-1].is_roll and not v[-1].tie_start


def test_roll_across_middle_stays_tied():
    v = spell_hu(bar({"sn": "x---r~~~~~~~x---"})).voices[1]
    assert values(v) == "x4 x4 x4 x4"
    assert v[1].tie_start and v[2].tie_stop and not v[2].tie_start


def test_roll_from_downbeat_over_three_beats_is_dotted_half():
    m = bar({"sn": "r~~~~~~~~~~~x---"})
    v = spell_hu(m).voices[1]
    assert values(v) == "x2. x4"
    assert v[0].is_roll and v[0].dots == 1 and not v[0].tie_start
    check_tokens(v, m)
    # Not from the downbeat: stays a tied quarter + half (no beat 3 hidden).
    assert values(spell_hu(bar({"sn": "x---r~~~~~~~~~~~"})).voices[1]) == "x4 x4 x2"


def test_roll_overlapping_stroke_is_an_error():
    m = Measure(TimeSig(4, 4), [Hit(F(0), "snare", roll=F(1, 2)), Hit(F(1, 4), "tom1")])
    with pytest.raises(SpellingError):
        spell_hu(m)


# --- invariants on random bars ------------------------------------------------

@pytest.mark.parametrize("time,grids", [
    ("4/4", [4, 8, 16, 12, 24]), ("3/4", [3, 6, 12]), ("6/8", [6, 12]), ("7/8", [7, 14]),
    ("12/8", [12, 24]), ("5/4", [5, 10, 20]), ("2/4", [2, 4, 8]),
])
def test_random_bars_tile_and_beam_correctly(time, grids):
    rng = random.Random(hash(time) & 0xFFFF)
    for _ in range(150):
        n = rng.choice(grids)
        pat = {
            "hh": "".join(rng.choice("x--") for _ in range(n)),
            "sn": "".join(rng.choice("x---") for _ in range(n)),
            "bd": "".join(rng.choice("x---") for _ in range(n)),
        }
        m = bar(pat, time)
        sm = spell_hu(m)
        beats = m.time_sig.beats()
        bounds = {s for s, _ in beats} | {m.actual_length}
        for v, tokens in sm.voices.items():
            if not tokens:
                continue
            check_tokens(tokens, m)
            for t in tokens:
                if t.kind == "note" and not t.tuplet:
                    end = t.pos + t.dur
                    inside = [b for b in bounds if t.pos < b < end]
                    assert not inside, f"note crosses a beat: {t} in {pat}"
            open_levels = {}
            for t in tokens:
                for level, state in t.beams.items():
                    if state == "begin":
                        assert level not in open_levels
                        open_levels[level] = t
                    elif state == "end":
                        assert level in open_levels
                        del open_levels[level]
                    elif state == "continue":
                        assert level in open_levels
            assert not open_levels
            # Every hit appears exactly once.
            onsets = sorted((h.pos, h.inst) for t in tokens if t.kind == "note" and not t.tie_stop for h in t.hits)
            expected = sorted((h.pos, h.inst) for h in m.hits if (v == 2) == (h.inst in ("kick", "hihat_pedal")))
            assert onsets == expected
