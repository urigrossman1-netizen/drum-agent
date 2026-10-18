"""Engrave every regression case and prove all formats encode the same music.

For each case in tests/cases/:
* LilyPond compiles with no warnings; the PDF exists, has pages, isn't blank;
* LilyPond's own MIDI (from the same .ly as the PDF) == the IR's events;
* the MusicXML validates against the MusicXML 4.0 XSD and == the IR's events;
* our MIDI == the IR's events (rolls expanded, flams/drags as graces);
* case-specific notation features appear in the sources.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

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
    # voices, the hands up and the feet down, in the PDF and the MusicXML alike: the accented
    # snare after the roll keeps its stem and accent above, with no rest over it.
    _, report = rendered["15_march_roll_over_kick"]
    ly = _ly(report)
    one = "\\oneVoice \\stemUp \\override Script.direction = #UP"
    up = ly.split("upMusic = ")[1].split("downMusic = ")[0]
    down = ly.split("downMusic = ")[1].split("\n}\n")[0]
    assert down.split("\\autoBeamOff")[1].strip().startswith(one)
    assert down.count("\\voiceTwo kick8[ kick8] kick4 " + one + " |") == 2
    assert up.count("snare4:32 snare4-> |") == 2 and "kick" not in up and "R1" not in up
    root = _xml(report)
    for m in root.iter("measure"):
        notes = m.findall("note")
        voices = {n.findtext("voice") for n in notes}
        stems = {n.findtext("stem") for n in notes if n.find("rest") is None and n.find("grace") is None}
        if any(n.find("notations/ornaments/tremolo") is not None for n in notes):
            assert voices == {"1", "2"}
            assert stems == {"up", "down"}
            down = [n for n in notes if n.findtext("voice") == "2" and n.find("rest") is None]
            assert {n.find("instrument").get("id") for n in down} == {"P1-kick"}
            assert not [n for n in notes if n.findtext("voice") == "1" and n.find("rest") is not None]
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
    page[400:420, 100:850] = 0  # a line cut off at the page edge: how far it runs is unknown
    Image.fromarray(page).save(tmp_path / "clipped.png")
    assert _overflow_mm([tmp_path / "clipped.png"], "letter") == float("inf")
    # A title wider than the page is cut off at both edges, but it is text, not a staff:
    # letters and word spaces break its ink into short runs.
    title = np.full((1100, 850), 255, dtype=np.uint8)
    for x in range(0, 850, 24):
        title[50:80, x:x + 18] = 0
    title[200:220, 100:780] = 0
    Image.fromarray(title).save(tmp_path / "title.png")
    assert _overflow_mm([tmp_path / "title.png"], "letter") == 0.0


def _dense_bars(n: int) -> dict:
    """Ghost 16ths with a sticking letter under every note, each bar a different kick."""
    return {"title": "Dense", "sections": [{"bars": [
        {"hh": "x-x-x-x-x-x-x-x-", "sn": "gggXgggggggXgggg", "bd": "x" + "-" * k + "x" + "-" * (14 - k),
         "sticking": "RL" * 8} for k in range(n)]}]}


def test_dense_line_is_replanned_until_it_fits(tmp_path, monkeypatch):
    # At 8 bars per line all four bars share one line and run off the page; 6 plans the
    # same line, so the re-plan has to keep going (and skip that plan) to two per line.
    import drum_agent.export.render as render_mod
    from drum_agent.pipeline import OVERFLOW_MM, _overflow_mm
    dirs, real = [], render_mod.render
    monkeypatch.setattr(render_mod, "render", lambda ly, d, stem, **kw: dirs.append(Path(d)) or real(ly, d, stem, **kw))
    report = export_all(compile_spec(_dense_bars(4)), tmp_path, "dense", options=ExportOptions(bars_per_line=8))
    assert not [w for w in report.warnings if w.startswith("Layout")], report.warnings
    assert any("(they ran off the right edge of the page)" in n for n in report.notes), report.notes
    assert _overflow_mm([p for k, p in report.files.items() if k.startswith("png")], "letter") <= OVERFLOW_MM
    assert report.files["ly"].read_text().count("\\break") == 1
    # The first render, one trial in a scratch directory, the accepted plan.
    assert [d.resolve() == tmp_path.resolve() for d in dirs] == [True, False, True]


def test_header_text_wider_than_the_page_is_no_line_overflow(tmp_path, monkeypatch):
    # A long title runs off both page edges and a long copyright line into the margins,
    # but every line of music fits: no re-plan (one render), no layout warning.
    import drum_agent.export.render as render_mod
    dirs, real = [], render_mod.render
    monkeypatch.setattr(render_mod, "render", lambda ly, d, stem, **kw: dirs.append(Path(d)) or real(ly, d, stem, **kw))
    score = compile_spec({"title": "Everybody Wants to Rule the World (Extended Twelve-Inch Remix, 1985)",
                          "sections": [{"bars": [{"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---",
                                                  "bd": "x-------x-x-----"}] * 8}]})
    score.copyright = ("(c) 1985 Example Music Publishing Ltd. All rights reserved. "
                       "Chart made for personal study only, not for distribution.")
    report = export_all(score, tmp_path, "title", options=ExportOptions(formats=("pdf",)))
    assert len(dirs) == 1
    assert not [w for w in report.warnings if w.startswith("Layout")], report.warnings
    assert not [n for n in report.notes if "bars per line" in n], report.notes


def test_failed_overflow_trial_keeps_the_original(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import drum_agent.export.render as render_mod
    from drum_agent.kit import DEFAULT_KIT
    from drum_agent.layout import plan_layout
    from drum_agent.pipeline import ExportReport, _fix_overflow
    page = np.full((1100, 850), 255, dtype=np.uint8)
    page[300:320, 100:] = 0  # ink cut off at the page edge
    Image.fromarray(page).save(tmp_path / "dense.png")

    def fail(ly, out_dir, stem, **kw):
        assert Path(out_dir).resolve() != tmp_path.resolve(), "a trial wrote over the real output"
        raise render_mod.RenderError("trial failed")
    monkeypatch.setattr(render_mod, "render", fail)
    score, opts, report = compile_spec(_dense_bars(4)), ExportOptions(bars_per_line=8), ExportReport()
    plan, res = plan_layout(score, bars_per_line=8), SimpleNamespace(pngs=[tmp_path / "dense.png"])
    assert _fix_overflow(score, DEFAULT_KIT, plan, opts, res, tmp_path, "dense", report) == (plan, res)
    assert not report.notes
    assert len(report.warnings) == 1
    assert report.warnings[0].startswith("Layout: a line runs off the right edge of the page; pass --bars-per-line")


def test_lines_cut_off_at_every_plan_keep_the_fewest_bars_per_line(tmp_path, monkeypatch):
    # A staff size too big for the page cuts every plan off at the edge, even one bar per
    # line. How far each runs can't be measured, but shorter lines lose less of the music,
    # and the warning ("even at one bar per line") must describe the chart actually written.
    from types import SimpleNamespace

    import drum_agent.export.render as render_mod
    from drum_agent.kit import DEFAULT_KIT
    from drum_agent.layout import plan_layout
    from drum_agent.pipeline import ExportReport, _fix_overflow
    page = np.full((1100, 850), 255, dtype=np.uint8)
    page[300:320, 100:] = 0  # ink cut off at the page edge
    Image.fromarray(page).save(tmp_path / "dense.png")
    dirs = []

    def clipped(ly, out_dir, stem, **kw):
        dirs.append(Path(out_dir).resolve())
        return SimpleNamespace(pngs=[tmp_path / "dense.png"], ly=ly)
    monkeypatch.setattr(render_mod, "render", clipped)
    score, opts, report = compile_spec(_dense_bars(4)), ExportOptions(bars_per_line=8), ExportReport()
    plan, res = plan_layout(score, bars_per_line=8), SimpleNamespace(pngs=[tmp_path / "dense.png"])
    plan, res = _fix_overflow(score, DEFAULT_KIT, plan, opts, res, tmp_path, "dense", report)
    assert all(b.line_break for b in plan.bars)
    assert res.ly.count("\\break") == 3
    # Two trials (two per line, then one) in scratch directories, then the kept plan.
    assert len(dirs) == 3 and dirs[-1] == tmp_path.resolve() and tmp_path.resolve() not in dirs[:-1]
    assert report.notes == ["Fewer bars per line: the planned lines were too dense to fit "
                            "(they ran off the right edge of the page)."]
    assert report.warnings == ["Layout: a line runs off the right edge of the page even at one bar per line; "
                               "pass a smaller --staff-size"]
