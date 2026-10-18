"""Stroke detection on short controlled signals."""

from fractions import Fraction as F

import numpy as np
import pytest
import soundfile as sf

from conftest import needs_fluidsynth
from drum_agent.audio.beats import estimate_grid
from drum_agent.audio.detect import DetectOptions, detect
from drum_agent.audio.features import SR
from drum_agent.charts import compile_spec
from drum_agent.model import Hit, Measure, Score, TimeSig
from drum_agent.synth import synthesize


def test_silence_and_faint_noise_give_no_strokes():
    assert detect(np.zeros(3 * SR, dtype=np.float32), DetectOptions(drums_only=True)).hits == []
    noise = (np.random.default_rng(1).standard_normal(3 * SR) * 1e-4).astype(np.float32)
    assert detect(noise, DetectOptions(drums_only=True)).hits == []


def render(tmp_path, score: Score) -> np.ndarray:
    wav = tmp_path / "x.wav"
    synthesize(score, wav, method="fluidsynth", kit_program=0, accompaniment=False, seed=1)
    y, _ = sf.read(wav)
    return (y.mean(axis=1) if y.ndim > 1 else y).astype(np.float32)


@needs_fluidsynth
def test_every_kit_piece_is_found_in_a_musical_context(tmp_path):
    # Calibration is relative to the recording, so pieces are tested in a short
    # chart (an isolated stroke in silence is not representative; see LIMITATIONS).
    from drum_agent.evaluate import evaluate_events, score_events
    score = compile_spec({"tempo": 100, "sections": [{"bars": [
        {"cr": "x-------", "hh": "--x-x-x-", "sn": "--x---x-", "bd": "x---x---"},
        {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"},
        {"rd": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"},
        {"t1": "xx------", "t2": "--xx----", "ft": "----xx--", "sn": "------xx", "bd": "x-------"},
        {"cr": "x-------", "bd": "x-------"}]}]})
    hits = detect(render(tmp_path, score), DetectOptions(drums_only=True)).hits
    result = evaluate_events(score_events(score, use_performed=False, audible=True),
                             [(h.time, h.inst) for h in hits], 0.05).as_dict()
    for inst in ("kick", "snare", "hihat", "ride", "crash", "tom1", "tom2", "floor_tom"):
        assert result["per_class"][inst]["R"] >= 0.99, (inst, result["per_class"][inst])
    assert result["overall"]["P"] >= 0.95, result["overall"]


@needs_fluidsynth
def test_snare_flam_is_one_flammed_stroke(tmp_path):
    # In a groove (an isolated stroke in silence is out of context, see above), at a tempo
    # where the rendered grace sits 37 ms early, as a played flam does: each flam is one
    # flammed snare stroke, its grace note no stroke of its own and no crash.
    score = compile_spec({"tempo": 100, "sections": [{"bars": [
        {"hh": "x-x-x-x-", "sn": "--x---f-", "bd": "x---x---"},
        {"hh": "x-x-x-x-", "sn": "--f---x-", "bd": "x---x---"}]}]})
    hits = detect(render(tmp_path, score), DetectOptions(drums_only=True)).hits
    snares = [h for h in hits if h.inst == "snare"]
    assert [h.flam for h in snares] == [False, True, True, False]
    assert not [h for h in hits if h.inst == "crash"]


@needs_fluidsynth
def test_a_stroke_ringing_out_is_not_a_new_stroke(tmp_path):
    # A lone snare in silence rings for a while; the ring's small onsets are not strokes.
    score = compile_spec({"tempo": 60, "sections": [{"bars": [{"sn": "-x--"}, {"sn": "----"}]}]})
    hits = detect(render(tmp_path, score), DetectOptions(drums_only=True)).hits
    assert len([h for h in hits if h.inst == "snare"]) == 1


@needs_fluidsynth
def test_steady_groove_gives_the_tempo(tmp_path):
    groove = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
    score = compile_spec({"tempo": 104, "sections": [{"bars": [groove] * 8}]})
    det = detect(render(tmp_path, score), DetectOptions(drums_only=True))
    grid = estimate_grid(det.hits, det.onset_env, det.duration, None, None, None, None)
    assert abs(grid.tempo / 104 - 1) < 0.02
    assert grid.time_sig == "4/4"


@needs_fluidsynth
@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")
def test_m4a_input_is_decoded_with_ffmpeg(tmp_path):
    # libsndfile can't read AAC; load_audio falls back to ffmpeg (librosa no longer does).
    import subprocess
    from drum_agent.audio.transcribe import load_audio
    score = compile_spec({"tempo": 100, "sections": [{"bars": [{"sn": "x-x-"}]}]})
    wav = tmp_path / "x.wav"
    synthesize(score, wav, method="fluidsynth", kit_program=0, accompaniment=False, seed=1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", str(tmp_path / "x.m4a")], check=True)
    assert abs(len(load_audio(tmp_path / "x.m4a")) - len(load_audio(wav))) < SR // 10
    (tmp_path / "bad.m4a").write_text("not audio")
    with pytest.raises(ValueError, match="bad.m4a"):
        load_audio(tmp_path / "bad.m4a")
