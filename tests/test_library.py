"""The chart library: 40 PAS rudiments and 73 grooves and fills (library/), 113 charts.

Every chart compiles, follows the house rules for library charts (original
pattern studies, nothing printed that the chart doesn't need, playable by one
drummer, sticking on every rudiment bar) and, in the slow suite, engraves with
every cross-format check passing.
"""

import re
from pathlib import Path

import pytest

from drum_agent.charts import load_any
from drum_agent.playability import check

from conftest import needs_lilypond

ROOT = Path(__file__).resolve().parents[1]
RUDIMENTS = sorted((ROOT / "library" / "rudiments").glob("*.yaml"))
GROOVES = sorted((ROOT / "library" / "grooves").glob("*.yaml"))
ALL = RUDIMENTS + GROOVES


def test_library_has_113_charts():
    assert len(RUDIMENTS) == 40 and len(GROOVES) == 73


def test_file_names_and_titles_are_numbered_in_order():
    for prefix, files in (("r", RUDIMENTS), ("g", GROOVES)):
        for k, p in enumerate(files, 1):
            assert re.fullmatch(rf"{prefix}{k:02d}_[a-z0-9_]+\.yaml", p.name), p.name
            assert load_any(p).title.startswith(f"{prefix.upper()}{k:02d} "), p.name
    titles = [load_any(p).title for p in ALL]
    assert len(set(titles)) == len(titles)


@pytest.mark.parametrize("path", ALL, ids=[p.stem for p in ALL])
def test_chart_follows_library_rules(path):
    s = load_any(path)
    assert s.chart_type == "pattern_study" and s.status == "entered" and s.rights == "original"
    assert s.artist is None and s.transcriber is None
    assert s.measures[0].tempo is not None and s.measures[0].section
    assert 2 <= len(s.measures) <= 16
    assert check(s) == [], f"{path.name}: not playable as written"
    if path in RUDIMENTS:
        for i, m in enumerate(s.measures, 1):
            hand = [h for h in m.hits if h.inst not in ("kick", "kick2", "hihat_pedal", "hihat_splash")]
            assert not hand or any(h.sticking for h in hand), f"{path.name} bar {i}: no sticking"


@pytest.mark.slow
@needs_lilypond
@pytest.mark.parametrize("path", ALL, ids=[p.stem for p in ALL])
def test_chart_engraves_and_all_checks_pass(path, tmp_path):
    from drum_agent.pipeline import export_all
    report = export_all(load_any(path), tmp_path, path.stem)
    assert report.rendering_ok
    assert not [w for w in report.warnings if w.startswith("LilyPond")], report.warnings
