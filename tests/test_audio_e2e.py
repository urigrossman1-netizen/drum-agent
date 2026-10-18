"""End to end from audio: chart -> synthesized recording -> transcription -> chart.

The charts are original and their content is known, so every transcription is
scored exactly (notation F: same bar, same position, same instrument). Floors
sit about 0.03 below the values measured when they were set, so they catch real
regressions without flaking. These run FluidSynth and the full pipeline: slow.
Synthesized audio is easier than real recordings; see docs/LIMITATIONS.md.
"""

from pathlib import Path

import pytest

from conftest import needs_fluidsynth, needs_lilypond
from drum_agent.audio.transcribe import TranscribeOptions, transcribe_file
from drum_agent.charts import load_any
from drum_agent.evaluate import notation_accuracy
from drum_agent.synth import synthesize

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.slow, needs_fluidsynth]

# (chart, GM kit, band accompaniment, humanize ms, notation F floor). Measured with the
# onset classifier: 02 1.000, 03 band 0.987, 06 band 0.974, 06 jazz 1.000, 10 0.987,
# 11 0.899, 11 band 0.902, 12 0.992, 13 0.974, Northbound band 0.978. (Case 11 on the
# Standard kit without a band is the one run below the template detector, 0.936: some
# kicks under floor-tom strokes are missed; docs/LIMITATIONS.md.)
CASES = [
    ("tests/cases/02_eighth_rock.yaml", 0, False, 0, 0.97),
    ("tests/cases/03_sixteenth_syncopation.yaml", 0, True, 0, 0.95),
    ("tests/cases/06_tom_fill_barline.yaml", 0, True, 0, 0.94),
    ("tests/cases/06_tom_fill_barline.yaml", 32, False, 0, 0.95),  # held-out jazz kit
    ("tests/cases/10_arrangement_tempo.yaml", 0, False, 0, 0.90),  # pickup, 12/8 bridge, tempo change
    ("tests/audio_cases/11_tom_grooves.yaml", 0, False, 0, 0.87),
    ("tests/audio_cases/11_tom_grooves.yaml", 0, True, 0, 0.85),
    ("tests/audio_cases/12_short_bars.yaml", 0, False, 0, 0.95),  # a 2/4 and a 3/4 bar
    ("tests/audio_cases/13_crash_accents.yaml", 0, False, 0, 0.95),  # no short bar may appear
]


def transcribe(tmp_path, chart, kit, band, humanize, **opts):
    ref = load_any(ROOT / chart)
    wav = tmp_path / "take.wav"
    synthesize(ref, wav, method="fluidsynth", kit_program=kit, accompaniment=band, humanize_ms=humanize, seed=3)
    est = transcribe_file(wav, TranscribeOptions(drums_only=not band, **opts))
    return ref, est


@pytest.mark.parametrize("chart,kit,band,humanize,floor", CASES,
                         ids=[f"{Path(c).stem[:12]}-kit{k}-{'band' if b else 'drums'}" for c, k, b, _, _ in CASES])
def test_transcription_matches_the_chart(tmp_path, chart, kit, band, humanize, floor):
    ref, est = transcribe(tmp_path, chart, kit, band, humanize)
    f = notation_accuracy(ref, est).f
    assert f >= floor, f"notation F {f:.3f} < {floor}"
    same = sum(str(a.time_sig) == str(b.time_sig) for a, b in zip(est.measures, ref.measures))
    assert same >= 0.9 * len(ref.measures)  # case 10's 12/8 boundary may be a bar off (documented)
    assert abs(len(est.measures) - len(ref.measures)) <= 1  # a silent final bar may be trimmed
    tempo = float(est.analysis["tempo_estimate"].split()[0])
    assert abs(tempo / ref.tempo_at(0) - 1) < 0.04
    assert est.status == "unverified_auto" and est.chart_type == "full_transcription"


def test_short_bars_are_found_and_flagged(tmp_path):
    ref, est = transcribe(tmp_path, "tests/audio_cases/12_short_bars.yaml", 0, False, 0)
    shorts = [(i, str(m.time_sig)) for i, m in enumerate(est.measures) if str(m.time_sig) in ("2/4", "3/4")]
    assert shorts == [(8, "2/4"), (17, "3/4")]
    assert all(est.measures[i].uncertain for i, _ in shorts)  # inserted bars ask for a listen


def test_a_meter_given_by_the_user_holds_throughout(tmp_path):
    # The same take as above: with --time-signature 4/4 no 2/4 or 3/4 bar is inserted.
    _, est = transcribe(tmp_path, "tests/audio_cases/12_short_bars.yaml", 0, False, 0, time_signature="4/4")
    assert {str(m.time_sig) for m in est.measures} == {"4/4"}


def test_crash_accents_do_not_create_a_short_bar(tmp_path):
    _, est = transcribe(tmp_path, "tests/audio_cases/13_crash_accents.yaml", 0, False, 0)
    assert {str(m.time_sig) for m in est.measures} == {"4/4"}
    assert any("barring kept" in n for n in est.analysis["notes"])  # the doubt is reported


def test_full_song_with_band(tmp_path):
    ref, est = transcribe(tmp_path, "examples/specs/03_full_song_northbound.yaml", 0, True, 0)
    assert notation_accuracy(ref, est).f >= 0.94
    assert str(est.measures[47].time_sig) == "2/4"


def test_tempo_hint_resolves_double_time(tmp_path):
    # With --bpm the tempo can't double, whatever the material.
    ref, est = transcribe(tmp_path, "tests/cases/07_ghost_accent_roll.yaml", 0, False, 0, bpm=92)
    assert len(est.measures) == len(ref.measures)
    assert notation_accuracy(ref, est).f >= 0.85


def test_rolls_dont_double_the_tempo(tmp_path):
    # Case 07 (ghosts, accents, flams, rolls; no backbeat) used to read at 184 BPM without a
    # hint: the rolls' 32nd strokes look like a 16th grid at double tempo. Roll and grace
    # strokes are no longer evidence for the beat grid (beats._texture_weights).
    ref, est = transcribe(tmp_path, "tests/cases/07_ghost_accent_roll.yaml", 0, False, 0)
    assert len(est.measures) == len(ref.measures)
    assert notation_accuracy(ref, est).f >= 0.85


def test_a_dense_band_take_doesnt_double_the_tempo(tmp_path):
    # Case 07 on the held-out jazz kit with a band, humanized: DP beats have twice as many
    # beats to bend at double tempo, and 184 BPM scored as well as 92. The near-tied octave
    # is decided by constant grids (beats._rescore_ties).
    ref, est = transcribe(tmp_path, "tests/cases/07_ghost_accent_roll.yaml", 32, True, 8)
    tempo = float(est.analysis["tempo_estimate"].split()[0])
    assert abs(tempo / ref.tempo_at(0) - 1) < 0.04


@needs_lilypond
def test_transcription_engraves_and_all_checks_pass(tmp_path):
    from drum_agent.pipeline import export_all
    _, est = transcribe(tmp_path, "tests/cases/10_arrangement_tempo.yaml", 32, True, 8)
    est.rights = "original"
    report = export_all(est, tmp_path / "out", "take")
    assert report.rendering_ok, [c.summary() for c in report.comparisons]
    text = (tmp_path / "out" / "take.report.md").read_text()
    assert "Automatic transcription, unverified" in text and "listen along" in text
