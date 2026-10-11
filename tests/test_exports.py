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
from drum_agent.charts import load_any
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
    assert set(names) == {"engraved score (LilyPond MIDI)", "MusicXML", "MIDI"}
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
    assert "<snare crash>4" in ly or "<crash snare>4" in ly or "<snare crash>" in ly
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


def test_case08_tuplets_and_rests(rendered):
    _, report = rendered["08_rests_subdivisions"]
    ly = _ly(report)
    assert "\\tuplet 3/2" in ly and "\\tuplet 6/4" in ly
    root = _xml(report)
    actual = {tm.findtext("actual-notes") for tm in root.iter("time-modification")}
    assert {"3", "6"} <= actual
    assert root.findall(".//rest[@measure='yes']")
    assert "32nd" in {t.text for t in root.iter("type")}


def test_case09_meters(rendered):
    _, report = rendered["09_odd_meters"]
    root = _xml(report)
    sigs = [(t.findtext("beats"), t.findtext("beat-type")) for t in root.iter("time")]
    assert sigs == [("3", "4"), ("7", "8"), ("5", "4"), ("6", "8"), ("12", "8"), ("5", "8"), ("2", "4")]
    ly = _ly(report)
    assert "\\time 2,2,3 7/8" in ly and "\\time 2,3 5/8" in ly
    assert "\\tempo 4. = 72" in ly


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
