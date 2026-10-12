"""Failures must be explicit: no silent fallback, no fabricated chart."""

from fractions import Fraction as F

import pytest

from drum_agent.cli import main
from drum_agent.export.render import RenderError, render
from drum_agent.model import Hit, Measure, Score, ScoreError, TimeSig
from drum_agent.rights import RightsError, require_rights
from conftest import needs_lilypond


def make(hits, **kw):
    return Score([Measure(TimeSig(4, 4), hits, tempo=100)], **kw)


@pytest.mark.parametrize("hits,msg", [
    ([Hit(F(1), "snare")], "outside the bar"),
    ([Hit(F(0), "snare"), Hit(F(0), "snare")], "duplicate"),
    ([Hit(F(0), "triangle")], "unknown instrument"),
    ([Hit(F(0), "snare", accent=True, ghost=True)], "both accent and ghost"),
    ([Hit(F(3, 4), "snare", roll=F(1, 2))], "past the barline"),
    ([Hit(F(0), "hihat"), Hit(F(0), "hihat_open")], "conflicting hi-hat"),
])
def test_invalid_ir_is_rejected(hits, msg):
    with pytest.raises(ScoreError, match=msg):
        make(hits).validate()


def test_float_positions_are_rejected():
    with pytest.raises(ScoreError, match="exact"):
        Hit.from_dict({"pos": 0.25, "inst": "snare"})


def test_missing_lilypond_is_a_hard_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DRUM_AGENT_LILYPOND", "/nonexistent/lilypond")
    with pytest.raises(RenderError, match="does not exist"):
        render("\\version \"2.24.0\" { c'4 }", tmp_path, "x")


@needs_lilypond
def test_broken_lilypond_source_reports_log(tmp_path):
    with pytest.raises(RenderError) as exc:
        render('\\version "2.24.0"\n\\drums { snare4 snare4 nonsense4 }', tmp_path, "bad")
    assert "LilyPond" in str(exc.value) and exc.value.log


@needs_lilypond
def test_barcheck_failure_is_fatal(tmp_path):
    with pytest.raises(RenderError, match="barcheck"):
        render('\\version "2.24.0"\n\\drums { sn4 sn4 sn4 | sn4 }', tmp_path, "bc")


def test_rights_gate():
    with pytest.raises(RightsError, match="analyze"):
        require_rights(None, "song.mp3")
    require_rights("own", "song.mp3")


def test_cli_transcribe_without_rights_fails(tmp_path, capsys):
    rc = main(["transcribe", str(tmp_path / "x.wav"), "-o", str(tmp_path)])
    assert rc == 1
    assert "rights" in capsys.readouterr().err


@needs_lilypond
def test_relative_output_directory(tmp_path, monkeypatch):
    # LilyPond runs inside the output directory; a relative path must still work.
    monkeypatch.chdir(tmp_path)
    res = render('\\version "2.24.0"\n\\score { \\drums { sn4 sn4 sn4 sn4 } \\layout {} \\midi {} }',
                 "out/rel", "x")
    assert res.pdf.exists() and res.pdf.is_absolute()
