"""Targeted score corrections (drum_agent/edit.py): every edit is exact.

Each test snapshots the score as a dict, applies one edit, and compares the
result with the snapshot edited by hand, so an edit that touches anything it
was not asked to (another bar, another hit, a flag, the metadata) fails.
Bar numbers in edit specs are 1-based performance bars; positions are whole
notes from the start of the bar.
"""

import copy
import json
from fractions import Fraction as F

import pytest

from drum_agent import edit as E
from drum_agent.charts import compile_spec, load_any
from drum_agent.edit import EditError
from drum_agent.kit import KitError
from drum_agent.model import ScoreError

GROOVE = {"rd": "xxxxxxxx", "sn": "--X---g-", "bd": "x---x--x"}


def base_score():
    """Six bars of 4/4: a ride groove, two flagged bars, a crash/roll bar.

    Bar 3 looks like automatic output (low confidence, performed times) so
    edits can be checked for keeping or resetting those fields.
    """
    s = compile_spec({
        "title": "Edit Fixture",
        "tempo": 100,
        "chart_type": "full_transcription",
        "status": "unverified_auto",
        "patterns": {"groove": GROOVE},
        "sections": [
            {"label": "Verse", "bars": ["groove", "groove",
                                        {"pattern": "groove", "uncertain": True, "notes": ["kick?"]},
                                        "groove"]},
            {"label": "Chorus", "bars": [{"cr": "x-------", "sn": "--x---r~", "bd": "x---x---",
                                          "uncertain": True},
                                         "groove"]},
        ],
    })
    for k, h in enumerate(sorted(s.measures[2].hits, key=lambda h: (h.pos, h.inst))):
        h.confidence = 0.6
        h.velocity = 70
        h.time = 4.8 + float(h.pos) * 2.4
        h.offset_ms = 3.0 + k
    s.validate()
    return s


def snap(score):
    return copy.deepcopy(score.to_dict())


def hits(d, bar):
    """Hit dicts of a 1-based bar in a snapshot."""
    return d["measures"][bar - 1]["hits"]


def find(d, bar, pos, inst):
    return next(h for h in hits(d, bar) if h["pos"] == pos and h["inst"] == inst)


def hit(score, bar, pos, inst):
    m = score.measures[bar - 1]
    return next(h for h in m.hits if h.pos == F(pos) and h.inst == inst)


def canon(d):
    """Snapshot with each bar's hits in (position, instrument) order, as to_dict writes them."""
    d = copy.deepcopy(d)
    for m in d["measures"]:
        m["hits"].sort(key=lambda h: (F(h["pos"]), h["inst"]))
    return d


def same_except_bars(before, after, bars):
    """Everything outside the given 1-based bars is untouched."""
    b, a = copy.deepcopy(before), copy.deepcopy(after)
    for i in bars:
        b["measures"][i - 1] = a["measures"][i - 1] = None
    return a == b


# ---- parse_bars -------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    (None, range(0, 16)),
    ("", range(0, 16)),
    ("12", range(11, 12)),
    ("1", range(0, 1)),
    ("16", range(15, 16)),
    ("9-16", range(8, 16)),
    ("3-3", range(2, 3)),
    ("1-16", range(0, 16)),
])
def test_parse_bars(spec, expected):
    assert E.parse_bars(spec, 16) == expected


@pytest.mark.parametrize("spec", ["0", "17", "0-4", "5-3", "1-17", "16-17"])
def test_parse_bars_out_of_range(spec):
    with pytest.raises(EditError, match="outside 1-16"):
        E.parse_bars(spec, 16)


@pytest.mark.parametrize("spec", ["x", "a-b", "3-", "-3", "1..4"])
def test_parse_bars_garbage_is_an_error(spec):
    with pytest.raises(ValueError):
        E.parse_bars(spec, 16)


def test_edit_error_is_a_score_error():
    assert issubclass(EditError, ScoreError) and issubclass(EditError, ValueError)


# ---- relabel ----------------------------------------------------------------

def test_relabel_everywhere_counts_and_changes_only_that_instrument():
    s = base_score()
    before = snap(s)
    n = E.relabel(s, "ride=hihat")
    assert n == 5 * 8  # five groove bars of ride 8ths; the chorus bar has none
    expected = copy.deepcopy(before)
    for m in expected["measures"]:
        for h in m["hits"]:
            if h["inst"] == "ride":
                h["inst"] = "hihat"
    assert s.to_dict() == canon(expected)
    s.validate()


def test_relabel_limited_to_bars():
    s = base_score()
    before = snap(s)
    n = E.relabel(s, "ride=hihat", "2-3")
    assert n == 16
    after = s.to_dict()
    assert same_except_bars(before, after, [2, 3])
    for bar in (2, 3):
        exp = [dict(h, inst="hihat") if h["inst"] == "ride" else h for h in hits(before, bar)]
        assert sorted(hits(after, bar), key=json.dumps) == sorted(exp, key=json.dumps)
    assert {h.inst for h in s.measures[0].hits} == {"ride", "snare", "kick"}
    assert {h.inst for h in s.measures[3].hits} == {"ride", "snare", "kick"}


def test_relabel_single_bar_keeps_flags_confidence_and_timing():
    s = base_score()
    before = snap(s)
    assert E.relabel(s, "sn=rimshot", "3") == 2
    expected = copy.deepcopy(before)
    for h in hits(expected, 3):
        if h["inst"] == "snare":
            h["inst"] = "rimshot"
    assert s.to_dict() == canon(expected)
    assert hit(s, 3, "1/4", "rimshot").accent and hit(s, 3, "3/4", "rimshot").ghost
    assert hit(s, 3, "1/4", "rimshot").confidence == 0.6


def test_relabel_accepts_aliases_and_reports_zero_when_absent():
    s, t = base_score(), base_score()
    assert E.relabel(s, "RD=hh") == E.relabel(t, "ride=hihat")
    assert s.to_dict() == t.to_dict()
    before = snap(s)
    assert E.relabel(s, "cowbell=tom1") == 0
    assert s.to_dict() == before


def test_relabel_onto_an_occupied_position_is_an_error():
    s = base_score()
    with pytest.raises(EditError, match=r"bar 1: snare already at 1/4"):
        E.relabel(s, "ride=snare", "1")


@pytest.mark.parametrize("mapping,exc,msg", [
    ("ride", EditError, "FROM=TO"),
    ("ride->hihat", EditError, "FROM=TO"),
    ("ride=gong", KitError, "unknown instrument"),
    ("gong=ride", KitError, "unknown instrument"),
])
def test_relabel_bad_mapping(mapping, exc, msg):
    s = base_score()
    before = snap(s)
    with pytest.raises(exc, match=msg):
        E.relabel(s, mapping)
    assert s.to_dict() == before


@pytest.mark.parametrize("bars", ["0", "7", "2-9", "4-2"])
def test_relabel_bar_range_outside_the_score(bars):
    s = base_score()
    before = snap(s)
    with pytest.raises(EditError, match="outside 1-6"):
        E.relabel(s, "ride=hihat", bars)
    assert s.to_dict() == before


# ---- delete -----------------------------------------------------------------

@pytest.mark.parametrize("spec", ["2:1/4:snare", "2:2/8:sn", "2:0.25:SD", "2:4/16:snare"])
def test_delete_removes_exactly_one_hit(spec):
    s = base_score()
    before = snap(s)
    E.delete(s, spec)
    expected = copy.deepcopy(before)
    hits(expected, 2).remove({"pos": "1/4", "inst": "snare", "accent": True})
    assert s.to_dict() == expected
    s.validate()


def test_delete_from_an_automatic_bar_leaves_neighbours_alone():
    s = base_score()
    before = snap(s)
    E.delete(s, "3:7/8:kick")
    expected = copy.deepcopy(before)
    hits(expected, 3).remove(find(before, 3, "7/8", "kick"))
    assert s.to_dict() == expected
    assert s.measures[2].uncertain  # deleting doesn't verify the bar


@pytest.mark.parametrize("spec,msg", [
    ("2:1/8:snare", r"no snare at 1/8 in bar 2"),
    ("2:1/4:kick", r"no kick at 1/4 in bar 2"),
    ("5:0:ride", r"no ride at 0 in bar 5"),
    ("0:0:kick", r"bar 0 does not exist \(1-6\)"),
    ("7:0:kick", r"bar 7 does not exist \(1-6\)"),
    ("-1:0:kick", r"bar -1 does not exist"),
    ("2:1/4", "must be BAR:POS:INST"),
    ("2", "must be BAR:POS:INST"),
])
def test_delete_errors(spec, msg):
    s = base_score()
    before = snap(s)
    with pytest.raises(EditError, match=msg):
        E.delete(s, spec)
    assert s.to_dict() == before


def test_delete_unknown_instrument_or_position():
    s = base_score()
    with pytest.raises(KitError, match="unknown instrument"):
        E.delete(s, "2:1/4:gong")
    with pytest.raises(ValueError):
        E.delete(s, "2:and:snare")
    with pytest.raises(ValueError):
        E.delete(s, "two:1/4:snare")


# ---- add --------------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    ("2:3/8:snare", {"pos": "3/8", "inst": "snare"}),
    ("2:3/8:sn:ghost", {"pos": "3/8", "inst": "snare", "ghost": True}),
    ("2:3/8:snare:accent", {"pos": "3/8", "inst": "snare", "accent": True}),
    ("2:3/8:snare:flam", {"pos": "3/8", "inst": "snare", "flam": True}),
    ("2:3/8:snare:drag", {"pos": "3/8", "inst": "snare", "drag": True}),
    ("2:3/8:snare:accent,flam", {"pos": "3/8", "inst": "snare", "accent": True, "flam": True}),
    ("2:3/8:snare: accent , drag ", {"pos": "3/8", "inst": "snare", "accent": True, "drag": True}),
    ("2:3/8:snare:", {"pos": "3/8", "inst": "snare"}),
    ("2:0:crash:choke", {"pos": "0", "inst": "crash", "choke": True}),
    ("2:1/2:snare:roll=1/4", {"pos": "1/2", "inst": "snare", "roll": "1/4"}),
    ("2:1/2:snare:roll=1/8,accent", {"pos": "1/2", "inst": "snare", "accent": True, "roll": "1/8"}),
    ("2:5/16:tom1", {"pos": "5/16", "inst": "tom1"}),
    ("2:6/16:t2", {"pos": "3/8", "inst": "tom2"}),
    ("2:1/12:snare:ghost", {"pos": "1/12", "inst": "snare", "ghost": True}),
])
def test_add_puts_exactly_one_hit(spec, expected):
    s = base_score()
    before = snap(s)
    E.add(s, spec)
    exp = copy.deepcopy(before)
    hits(exp, 2).append(expected)
    assert s.to_dict() == canon(exp)
    s.validate()


def test_add_stores_exact_fractions_and_full_confidence():
    s = base_score()
    E.add(s, "3:3/8:snare:ghost")
    h = hit(s, 3, "3/8", "snare")
    assert isinstance(h.pos, F) and h.pos == F(3, 8)
    assert h.confidence == 1.0  # a human put it there
    assert h.time is None and h.offset_ms is None
    E.add(s, "3:1/2:snare:roll=1/4")
    assert hit(s, 3, "1/2", "snare").roll == F(1, 4)
    # The automatic hits around the new ones keep their confidence.
    added = {(F(3, 8), "snare"), (F(1, 2), "snare")}
    assert all(h.confidence == 0.6 for h in s.measures[2].hits if h.key() not in added)


@pytest.mark.parametrize("spec,msg", [
    ("2:1/4:snare", r"bar 2 already has snare at 1/4"),
    ("2:1/4:sd:ghost", r"bar 2 already has snare at 1/4"),
    ("2:3/8:snare:loud", r"unknown flags \['loud'\]"),
    ("2:3/8:snare:ghost,rim", r"unknown flags \['rim'\]"),
    ("2:3/8:snare:velocity", r"unknown flags"),
    ("0:0:snare", "bar 0 does not exist"),
    ("7:0:snare", "bar 7 does not exist"),
    ("2:3/8", "must be BAR:POS:INST"),
])
def test_add_errors(spec, msg):
    s = base_score()
    before = snap(s)
    with pytest.raises(EditError, match=msg):
        E.add(s, spec)
    assert s.to_dict() == before


@pytest.mark.parametrize("spec,msg", [
    ("2:1:snare", "outside the bar"),
    ("2:3/8:snare:accent,ghost", "both accent and ghost"),
    ("2:7/8:snare:roll=1/4", "past the barline"),
    ("1:0:hihat_open", "conflicting hi-hat"),
])
def test_add_that_breaks_the_score_is_caught_by_validate(spec, msg):
    s = base_score()
    if "hihat" in spec:
        E.relabel(s, "ride=hihat", "1")
    E.add(s, spec)
    with pytest.raises(ScoreError, match=msg):
        s.validate()


# ---- set_flags --------------------------------------------------------------

def test_set_flags_replaces_flags_on_one_hit():
    s = base_score()
    before = snap(s)
    E.set_flags(s, "2:3/4:snare:accent")  # was a ghost note
    exp = copy.deepcopy(before)
    h = find(exp, 2, "3/4", "snare")
    del h["ghost"]
    h["accent"] = True
    assert s.to_dict() == exp
    s.validate()


def test_set_flags_without_flags_clears_everything_including_rolls():
    s = base_score()
    before = snap(s)
    E.set_flags(s, "5:3/4:snare")
    E.set_flags(s, "1:1/4:sn:")
    exp = copy.deepcopy(before)
    del find(exp, 5, "3/4", "snare")["roll"]
    del find(exp, 1, "1/4", "snare")["accent"]
    assert s.to_dict() == exp


@pytest.mark.parametrize("flags,expect", [
    ("ghost", {"ghost": True}),
    ("flam", {"flam": True}),
    ("drag", {"drag": True}),
    ("choke", {"choke": True}),
    ("accent,flam", {"accent": True, "flam": True}),
    ("roll=1/8", {"roll": F(1, 8)}),
    ("roll=1/4,accent", {"roll": F(1, 4), "accent": True}),
])
def test_set_flags_each_flag(flags, expect):
    s = base_score()
    E.set_flags(s, f"4:1/4:snare:{flags}")
    h = hit(s, 4, "1/4", "snare")
    for name in ("accent", "ghost", "flam", "drag", "choke"):
        assert getattr(h, name) == expect.get(name, False), name
    assert h.roll == expect.get("roll")
    s.validate()


def test_set_flags_keeps_timing_and_velocity_but_marks_human_confidence():
    s = base_score()
    old = copy.copy(hit(s, 3, "3/4", "snare"))
    E.set_flags(s, "3:3/4:snare:accent")
    h = hit(s, 3, "3/4", "snare")
    assert (h.velocity, h.time, h.offset_ms) == (old.velocity, old.time, old.offset_ms)
    assert h.accent and not h.ghost
    assert h.confidence == 1.0
    others = [x for x in s.measures[2].hits if x is not h]
    assert all(x.confidence == 0.6 for x in others)


@pytest.mark.parametrize("spec,exc,msg", [
    ("2:3/8:snare:accent", EditError, r"no snare at 3/8 in bar 2"),
    ("2:1/4:tom1:accent", EditError, r"no tom1 at 1/4 in bar 2"),
    ("2:1/4:snare:rimshot", EditError, "unknown flags"),
    ("9:1/4:snare:accent", EditError, "bar 9 does not exist"),
    ("2:1/4:gong:accent", KitError, "unknown instrument"),
])
def test_set_flags_errors(spec, exc, msg):
    s = base_score()
    before = snap(s)
    with pytest.raises(exc, match=msg):
        E.set_flags(s, spec)
    assert s.to_dict() == before


# ---- set_sections -----------------------------------------------------------

def test_set_sections_replaces_all_labels():
    s = base_score()
    before = snap(s)
    E.set_sections(s, "Intro:1, Verse 1:3,Chorus: 5")
    assert [m.section for m in s.measures] == ["Intro", None, "Verse 1", None, "Chorus", None]
    exp = copy.deepcopy(before)
    for m in exp["measures"]:
        m.pop("section", None)
    exp["measures"][0]["section"] = "Intro"
    exp["measures"][2]["section"] = "Verse 1"
    exp["measures"][4]["section"] = "Chorus"
    assert s.to_dict() == exp


def test_set_sections_label_may_contain_a_colon():
    s = base_score()
    E.set_sections(s, "Part: A:2")
    assert [m.section for m in s.measures] == [None, "Part: A", None, None, None, None]


@pytest.mark.parametrize("spec", ["Intro:0", "Intro:7", ":3", "  :3", "Intro:1,Outro:9"])
def test_set_sections_bad_entries(spec):
    with pytest.raises(EditError, match="bad section entry"):
        E.set_sections(base_score(), spec)


@pytest.mark.parametrize("spec", ["Intro", "Intro:one"])
def test_set_sections_entry_without_a_bar_number_is_an_edit_error(spec):
    # Same documented format ("label:first bar"), so the same clear EditError
    # naming the entry -- not a bare int() ValueError.
    with pytest.raises(EditError, match="bad section entry"):
        E.set_sections(base_score(), spec)


# ---- set_tempo --------------------------------------------------------------

def test_set_tempo_marks_one_bar():
    s = base_score()
    before = snap(s)
    E.set_tempo(s, "4:132")
    exp = copy.deepcopy(before)
    exp["measures"][3]["tempo"] = 132.0
    assert s.to_dict() == exp
    assert [s.tempo_at(i) for i in range(6)] == [100, 100, 100, 132, 132, 132]
    E.set_tempo(s, "1:96.5")
    assert s.measures[0].tempo == 96.5 and s.initial_tempo == 96.5
    s.validate()


@pytest.mark.parametrize("spec", ["0:120", "7:120", "-2:120"])
def test_set_tempo_bar_out_of_range(spec):
    s = base_score()
    before = snap(s)
    with pytest.raises(EditError, match="does not exist"):
        E.set_tempo(s, spec)
    assert s.to_dict() == before


@pytest.mark.parametrize("spec", ["2:fast", "x:120", "2:"])
def test_set_tempo_garbage(spec):
    with pytest.raises(ValueError):
        E.set_tempo(base_score(), spec)


def test_set_tempo_outside_the_valid_range_is_rejected():
    # Rejected at the edit itself (EditError is a ScoreError), before it can reach the score.
    s = base_score()
    before = snap(s)
    with pytest.raises(ScoreError, match="outside 20-400"):
        E.set_tempo(s, "2:1000")
    assert snap(s) == before


# ---- mark_verified ----------------------------------------------------------

def test_mark_verified_all_bars_clears_flags_and_sets_status():
    s = base_score()
    before = snap(s)
    assert E.mark_verified(s, None) == 2
    assert s.status == "verified"
    assert not any(m.uncertain for m in s.measures)
    assert s.measures[2].notes == ["kick?", "verified by ear"]
    assert s.measures[4].notes == ["verified by ear"]
    assert all(h.confidence == 0.9 for h in s.measures[2].hits)  # raised to 0.9 ...
    assert all(h.confidence == 1.0 for i in (0, 1, 3, 4, 5) for h in s.measures[i].hits)  # ... never lowered
    exp = copy.deepcopy(before)
    exp["status"] = "verified"
    for bar in (3, 5):
        m = exp["measures"][bar - 1]
        del m["uncertain"]
        m["notes"] = m.get("notes", []) + ["verified by ear"]
    for h in hits(exp, 3):
        h["confidence"] = 0.9
    assert s.to_dict() == exp


def test_mark_verified_bar_range_keeps_status():
    s = base_score()
    before = snap(s)
    assert E.mark_verified(s, "3") == 1
    assert s.status == "unverified_auto"
    assert [m.uncertain for m in s.measures] == [False, False, False, False, True, False]
    assert same_except_bars(before, s.to_dict(), [3])


def test_mark_verified_range_covering_every_flag_still_keeps_status():
    # Only a whole-score verification (no bar range) changes the status.
    s = base_score()
    assert E.mark_verified(s, "1-6") == 2
    assert not any(m.uncertain for m in s.measures)
    assert s.status == "unverified_auto"


def test_mark_verified_range_without_flags_still_raises_confidence():
    s = base_score()
    assert E.mark_verified(s, "1-2") == 0
    assert s.measures[2].uncertain and s.measures[4].uncertain
    assert all(h.confidence == 0.6 for h in s.measures[2].hits)  # outside the range
    assert E.mark_verified(s, "3-4") == 1
    assert all(h.confidence == 0.9 for h in s.measures[2].hits)


def test_mark_verified_twice_is_idempotent():
    s = base_score()
    E.mark_verified(s, None)
    once = snap(s)
    assert E.mark_verified(s, None) == 0
    assert s.to_dict() == once


def test_mark_verified_on_a_clean_score():
    s = base_score()
    for m in s.measures:
        m.uncertain = False
    assert E.mark_verified(s, None) == 0
    assert s.status == "verified"
    assert [m.notes for m in s.measures] == [[], [], ["kick?"], [], [], []]


@pytest.mark.parametrize("bars", ["0", "7", "5-2"])
def test_mark_verified_bad_range(bars):
    s = base_score()
    before = snap(s)
    with pytest.raises(EditError, match="outside 1-6"):
        E.mark_verified(s, bars)
    assert s.to_dict() == before


# ---- whole workflow ---------------------------------------------------------

def test_edited_score_validates_and_round_trips(tmp_path):
    s = base_score()
    assert E.relabel(s, "ride=hihat", "1-4") == 32
    E.delete(s, "3:7/8:kick")
    E.add(s, "3:3/8:kick")
    E.add(s, "4:7/8:snare:flam")
    E.add(s, "4:15/16:snare:ghost")
    E.set_flags(s, "5:3/4:snare:roll=1/8")
    E.add(s, "6:0:crash:choke")
    E.set_sections(s, "Groove:1,Out:5")
    E.set_tempo(s, "5:104")
    E.mark_verified(s, None)
    assert s.validate() == []
    path = tmp_path / "edited.json"
    s.save(path)
    again = load_any(path)
    assert again.to_dict() == s.to_dict()
    assert again.status == "verified"
    assert hit(again, 5, "3/4", "snare").roll == F(1, 8)
    assert hit(again, 4, "15/16", "snare").ghost
    assert [m.section for m in again.measures] == ["Groove", None, None, None, "Out", None]
    assert [m.tempo for m in again.measures] == [100, None, None, None, 104, None]
