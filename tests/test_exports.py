"""Engrave every regression case and prove all formats encode the same music.

For each case in tests/cases/:
* LilyPond compiles with no warnings; the PDF exists, has pages, isn't blank;
* LilyPond's own MIDI (from the same .ly as the PDF) == the IR's events;
* the MusicXML validates against the MusicXML 4.0 XSD and == the IR's events;
* our MIDI == the IR's events (rolls expanded, flams/drags as graces);
* case-specific notation features appear in the sources.
"""

import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from conftest import CASES, needs_lilypond
from drum_agent.charts import compile_spec, load_any
from drum_agent.pipeline import ExportOptions, export_all

pytestmark = needs_lilypond


@pytest.fixture(scope="module")
def rendered(artifacts):
    out = {}
    for case in CASES:
        score = load_any(case)
        report = export_all(score, artifacts / "cases", case.stem, options=ExportOptions())
        out[case.stem] = (score, report)
    return out


@pytest.mark.parametrize("case", [c.stem for c in CASES])
def test_case_renders_cleanly_and_formats_agree(rendered, case):
    score, report = rendered[case]
    assert report.rendering_ok, [c.summary() for c in report.comparisons]
    lily_warnings = [w for w in report.warnings if w.startswith("LilyPond")]
    assert not lily_warnings, lily_warnings
    assert not report.musicxml_errors
    names = {c.name: c for c in report.comparisons}
    assert set(names) == {"engraved score (LilyPond MIDI)", "engraved score tempo map",
                          "MusicXML", "MusicXML articulations", "MusicXML meters",
                          "MIDI", "MIDI tempo map", "MIDI barlines"}
    assert names["MusicXML"].expected == len(score.event_list()) > 0


@pytest.mark.parametrize("case", [c.stem for c in CASES])
def test_pdf_pages_are_real_and_not_blank(rendered, case):
    import pdfplumber
    score, report = rendered[case]
    pdf = report.files["pdf"]
    with pdfplumber.open(pdf) as doc:
        assert len(doc.pages) >= 1
        text = doc.pages[0].extract_text() or ""
    assert score.title.split(":")[0] in text
    pngs = [v for k, v in report.files.items() if k.startswith("png")]
    assert len(pngs) >= 1
    for png in pngs:
        img = np.asarray(Image.open(png).convert("L"))
        ink = (img < 128).mean()
        assert 0.005 < ink < 0.25, f"{png.name}: ink coverage {ink:.3f} looks blank or corrupt"


def _xml(report):
    return ET.parse(report.files["musicxml"]).getroot()


def _ly(report):
    return report.files["ly"].read_text()


def test_case04_simultaneous_hits(rendered):
    score, report = rendered["04_simultaneous_hits"]
    root = _xml(report)
    chords = root.findall(".//note/chord")
    assert len(chords) >= 6
    ly = _ly(report)
    # Cymbals-up voicing: the crash stems up, snare and kick share the stems-down chord.
    up, down = ly.split("upMusic = ")[1].split("downMusic = ")
    assert "crash4" in up and "snare" not in up
    assert "<kick snare>4" in down
    heads = {n.text for n in root.iter("notehead")}
    assert {"x", "diamond"} <= heads  # cymbals and ride bell


def test_case05_open_and_closed_hihat(rendered):
    _, report = rendered["05_hihat_open_closed"]
    root = _xml(report)
    tech = [child.tag for t in root.iter("technical") for child in t]
    assert "open" in tech and "stopped" in tech and "half-muted" in tech
    ly = _ly(report)
    assert "hihatopen" in ly and "hihatclosed" in ly and "hihathalf" in ly
    assert "hihatpedal" in ly


def test_case06_fill_across_barline(rendered):
    score, report = rendered["06_tom_fill_barline"]
    toms = [h for _, m, h in score.iter_hits() if h.inst in ("tom1", "tom2", "floor_tom")]
    assert len(toms) == 11
    # The fill bar and the crash bar that follows are written out, never repeated.
    from drum_agent.layout import plan_layout
    plan = plan_layout(score)
    printed = {b.index: b for b in plan.bars}
    assert not printed[3].percent and not printed[4].percent


def test_case07_articulations(rendered):
    _, report = rendered["07_ghost_accent_roll"]
    root = _xml(report)
    assert root.findall(".//notehead[@parentheses='yes']")
    assert root.findall(".//articulations/accent")
    assert root.findall(".//grace[@slash='yes']")
    assert root.findall(".//ornaments/tremolo")
    assert root.findall(".//tie[@type='start']")
    ly = _ly(report)
    assert "\\parenthesize" in ly and "\\acciaccatura" in ly and ":32" in ly and "~" in ly
    assert "snare2:32" in ly  # half-bar roll as one half note
    assert "snare2.:32" in ly  # three-beat roll from the downbeat: one dotted half
    assert "snare4:32~" in ly  # a roll across the middle of the bar stays tied


def test_case08_tuplets_and_rests(rendered):
    _, report = rendered["08_rests_subdivisions"]
    ly = _ly(report)
    assert "\\tuplet 3/2" in ly and "\\tuplet 6/4" in ly
    root = _xml(report)
    actual = {tm.findtext("actual-notes") for tm in root.iter("time-modification")}
    assert {"3", "6"} <= actual
    assert root.findall(".//rest[@measure='yes']")
    assert "32nd" in {t.text for t in root.iter("type")}
    # A beamed tuplet shows the number alone; a quarter and an 8th under a "3" keep the bracket.
    assert {t.get("bracket") for t in root.iter("tuplet") if t.get("type") == "start"} == {"yes", "no"}
    assert [m.text for m in root.iter("multiple-rest")] == ["4"]  # the tacet section
    assert "R1*4/1" in ly
    glob = ly.split("globalMusic = {")[1].split("\n}")[0]
    assert "\\grace { s8 }" in glob and "\\grace { s16 s16 }" in glob  # downbeat flam and drag


def test_case14_triplet_half_beats(rendered):
    # Three 16th-note triplets and an 8th: a "3" over half the beat plus a plain 8th, one
    # beam per beat (not a "6" ending on a dotted 8th); six even sextuplets stay a "6".
    _, report = rendered["14_triplet_half_beats"]
    ly = _ly(report)
    assert "\\tuplet 3/2 { snare16[ kick16 kick16 } kick8]" in ly
    # No cymbal over the ratamacues: their numbers go above the notes, out of the sticking
    # line; the groove's triplet under the hi-hat keeps the number below. The drag comes before
    # the tuplet: inside it, it would bring the bracket back over the beamed group.
    assert ("\\tag #'graces \\appoggiatura { snare16[ snare16] } \\tweak direction #UP \\tuplet 3/2 "
            "{ <kick snare>16[") in ly
    assert "\\tuplet 3/2 { \\tag #'graces" not in ly
    assert "kick4 \\tuplet 3/2 { snare16[ kick16 kick16 } kick8]" in ly
    assert "snare16 snare16 } snare8->]" in ly  # the ratamacue's accented 8th, outside the bracket
    assert "\\tuplet 6/4 { <kick snare>16[" in ly and "snare8.]" not in ly
    # The pickup from the half beat is a "3" too, with no rest over it for the cymbal voice.
    up = ly.split("upMusic = ")[1].split("downMusic = ")[0]
    down = ly.split("downMusic = ")[1]
    assert "\\partial 8" in ly and up.split("\\autoBeamOff")[1].split("|")[0].strip() == "s1*1/8"
    assert down.split("\\autoBeamOff")[1].split("|")[0].strip().endswith("\\tuplet 3/2 { snare16[ snare16 snare16] }")
    root = _xml(report)
    mods = {(tm.findtext("actual-notes"), tm.findtext("normal-notes")) for tm in root.iter("time-modification")}
    assert ("3", "2") in mods and ("6", "4") in mods
    pickup = root.find(".//measure")
    assert {n.findtext("voice") for n in pickup.iter("note")} == {"2"}
    assert [n.findtext("time-modification/actual-notes") for n in pickup.iter("note")] == ["3"] * 3
    # Every tuplet here is beamed: no brackets in the MusicXML either, as in the PDF.
    assert {t.get("bracket") for t in root.iter("tuplet") if t.get("type") == "start"} == {"no"}


def test_case15_march_roll_over_kick(rendered):
    # No cymbal anywhere: one voice, stems up, accents above. The roll bars alone are in two
    # voices (the roll up, the drums down), in the PDF and the MusicXML alike.
    _, report = rendered["15_march_roll_over_kick"]
    ly = _ly(report)
    one = "\\oneVoice \\stemUp \\override Script.direction = #UP"
    up = ly.split("upMusic = ")[1].split("downMusic = ")[0]
    down = ly.split("downMusic = ")[1].split("\n}\n")[0]
    assert down.split("\\autoBeamOff")[1].strip().startswith(one)
    assert down.count("\\voiceTwo kick8[ kick8] <kick snare>4-> " + one + " |") == 2
    assert up.count("snare4:32 r4 |") == 2 and "kick" not in up and "R1" not in up
    root = _xml(report)
    for m in root.iter("measure"):
        notes = m.findall("note")
        voices = {n.findtext("voice") for n in notes}
        stems = {n.findtext("stem") for n in notes if n.find("rest") is None and n.find("grace") is None}
        if any(n.find("notations/ornaments/tremolo") is not None for n in notes):
            assert voices == {"1", "2"}
            assert stems == {"up", "down"}
        else:  # the tacet bar's rest included
            assert voices == {"2"} and stems <= {"up"}


def test_case09_meters(rendered):
    _, report = rendered["09_odd_meters"]
    root = _xml(report)
    sigs = [(t.findtext("beats"), t.findtext("beat-type")) for t in root.iter("time")]
    assert sigs == [("3", "4"), ("7", "8"), ("5", "4"), ("6", "8"), ("12", "8"), ("5", "8"), ("3", "8"), ("2", "4")]
    ly = _ly(report)
    assert "\\time 2,2,3 7/8" in ly and "\\time 2,3 5/8" in ly
    assert "\\tempo 4. = 72" in ly
    assert "hihat8[ hihat8 hihat8]" in ly  # 3/8 is beamed as one group


def test_case10_arrangement(rendered):
    score, report = rendered["10_arrangement_tempo"]
    root = _xml(report)
    first = root.find(".//measure")
    assert first.get("implicit") == "yes" and first.get("number") == "0"  # pickup
    tempos = [s.get("tempo") for s in root.iter("sound") if s.get("tempo")]
    assert tempos == ["108", "105", "100"]  # 4.=70 in 12/8 is 105 quarter notes per minute
    assert root.findall(".//repeat[@direction='backward'][@times='2']")
    assert root.findall(".//measure-repeat[@type='start']")
    rehearsals = [r.text for r in root.iter("rehearsal")]
    assert rehearsals == ["Pickup", "Intro", "Verse 1", "Chorus", "Bridge", "Outro"]
    ly = _ly(report)
    assert "\\partial 4" in ly and "\\repeat volta 2" in ly and "\\repeat percent" in ly
    assert len(score.measures) == 30  # pickup + 4 + 8 + 8 + 4 + 5


@needs_lilypond
def test_irregular_meter_bar_with_a_silent_voice(tmp_path):
    # A whole-bar rest in 7/8 has no single note value; it must still engrave.
    score = compile_spec({"title": "7/8 silent feet", "sections": [{"time": "7/8", "beat_groups": "2+2+3",
                                                                    "bars": [{"rd": "x-x-x-x"}, {"bd": "x---x--"}]}]})
    report = export_all(score, tmp_path, "s78")
    assert report.rendering_ok


def test_one_voice_chart_has_no_rests_for_the_empty_voice():
    # A snare-only rudiment: one voice, stems up, accents above; no column of rests
    # for the (empty) cymbal voice.
    from drum_agent.export.lilypond import to_lilypond
    snare = compile_spec({"sections": [{"bars": [{"sn": "Xxxx|Xxxx|Xxxx|Xxxx", "sticking": "RLRR|LRLL|RLRR|LRLL"}]}]})
    ly = to_lilypond(snare)
    up = ly.split("upMusic = ")[1].split("downMusic = ")[0]
    down = ly.split("downMusic = ")[1].split("\n}\n")[0]
    assert "\\oneVoice \\stemUp" in down and "Script.direction = #UP" in down
    assert " r" not in up and "R1" not in up
    groove = compile_spec({"sections": [{"bars": [{"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x---x---"}]}]})
    assert "\\oneVoice" not in to_lilypond(groove)


def test_line_overflow_is_measured_on_the_page(tmp_path):
    import numpy as np
    from PIL import Image
    from drum_agent.pipeline import _overflow_mm
    page = np.full((1100, 850), 255, dtype=np.uint8)  # letter at 100 dpi: 850 px wide
    page[200:220, 100:780] = 0  # ink up to 780 px = 198.1 mm (margin starts at 201.9 mm)
    Image.fromarray(page).save(tmp_path / "fits.png")
    page[300:320, 100:830] = 0  # a line running to 830 px = 210.8 mm
    Image.fromarray(page).save(tmp_path / "over.png")
    assert _overflow_mm([tmp_path / "fits.png"], "letter") == 0.0
    assert 8 < _overflow_mm([tmp_path / "over.png"], "letter") < 10
