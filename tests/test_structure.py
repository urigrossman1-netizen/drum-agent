"""Sections and fills from the bars (audio/structure.py): repeated sections take their letter
again (A, B, A2), and a busy bar unlike its section's groove is marked as a fill."""

from pathlib import Path

from drum_agent.audio.structure import label_sections
from drum_agent.charts import compile_spec, load_any

ROOT = Path(__file__).resolve().parents[1]
VERSE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
VERSE_IN = {"cr": "x-------", "hh": "--x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
CHORUS = {"rd": "x-x-x-x-", "sn": "--x---x-", "bd": "x--xx---"}
CHORUS_IN = {"cr": "x-------", "rd": "--x-x-x-", "sn": "--x---x-", "bd": "x--xx---"}
BRIDGE = {"hh": "xxxxxxxx", "sn": "----x---", "bd": "x-x-x-x-"}
BRIDGE_IN = {"cr": "x-------", "hh": "-xxxxxxx", "sn": "----x---", "bd": "x-x-x-x-"}
TOMS = {"sn": "xxxx----", "t1": "----xx--", "ft": "------xx", "bd": "x---x---"}  # a fill around the toms


def _bars(spec_sections):
    score = compile_spec({"title": "Form", "tempo": 110, "rights": "original", "sections": spec_sections})
    for m in score.measures:  # start from the bars alone, as a transcription does
        m.section, m.cue = None, None
    return score.measures


def test_repeated_sections_take_their_letter_again():
    verse = [VERSE_IN, VERSE, VERSE, TOMS]
    chorus = [CHORUS_IN, CHORUS, CHORUS, TOMS]
    bars = _bars([{"label": "x", "bars": verse + chorus + verse + chorus + [BRIDGE_IN, BRIDGE, BRIDGE, BRIDGE]}])
    roadmap = label_sections(bars)
    assert [(r["label"], r["first_bar"]) for r in roadmap] == [("A", 1), ("B", 5), ("A2", 9), ("B2", 13), ("C", 17)]
    assert [m.section for m in bars if m.section] == ["A", "B", "A2", "B2", "C"]
    a2 = roadmap[2]
    assert a2["repeat_of"] == "A" and a2["similarity"] >= 0.7 and "repeat_of" not in roadmap[4]
    assert [i for i, m in enumerate(bars) if m.cue == "Fill"] == [3, 7, 11, 15]  # the tom fills only
    assert [r["fills"] for r in roadmap] == [1, 1, 1, 1, 0]


def test_the_library_fill_charts_mark_exactly_their_fills():
    g64 = load_any(ROOT / "library" / "grooves" / "g64_sixteenth_tom_fill.yaml")
    for m in g64.measures:
        m.section, m.cue = None, None
    label_sections(g64.measures)
    # [groove, groove, groove, fill, crash, groove, half_fill, crash]
    assert [i for i, m in enumerate(g64.measures) if m.cue == "Fill"] == [3, 6]


def test_a_busy_groove_played_throughout_is_no_fill():
    funk = {"hh": "x-x-x-x-x-x-x-x-", "sn": "--x-xx-xx-x-xx-x", "bd": "x--x--x---x-----"}  # 8 snares a bar
    bars = _bars([{"label": "x", "bars": [funk] * 6}])
    label_sections(bars)
    assert not any(m.cue for m in bars)
    other = {"hh": "x-x-x-x-x-x-x-x-", "sn": "xxxxxxxx--------", "bd": "x-------x-------"}  # a snare run
    bars = _bars([{"label": "x", "bars": [funk] * 3 + [other] + [funk] * 2}])
    label_sections(bars)
    assert [i for i, m in enumerate(bars) if m.cue == "Fill"] == [3]


def test_a_cue_already_there_is_kept():
    bars = _bars([{"label": "x", "bars": [VERSE_IN, VERSE, VERSE, TOMS]}])
    bars[3].cue = "Band out"
    label_sections(bars)
    assert bars[3].cue == "Band out"
