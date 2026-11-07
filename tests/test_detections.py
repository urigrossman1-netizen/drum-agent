"""Keeping every prediction: the detection log (audio/detections.py), each note's link to the
strokes it came from (Hit.raw), notes a person changed (Hit.edited), and the original kept
through edits."""

import json
from fractions import Fraction

import numpy as np
import pytest

from drum_agent.charts import compile_spec
from drum_agent.edit import mark_edits
from drum_agent.model import Hit, Measure, Score, ScoreError, TimeSig
from drum_agent.quantize import BarDef, Onset, quantize

GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
FILL = {"hh": "x-x-x---", "sn": "--x-xxxx", "bd": "x---x---"}


def spec(bars=4, tempo=100):
    return compile_spec({"title": "Log Test", "tempo": tempo, "rights": "original",
                         "sections": [{"label": "A", "bars": [GROOVE] * (bars - 1) + [FILL]}]})


# ---- the model ----------------------------------------------------------------------

def test_raw_and_edited_round_trip_and_old_charts_still_load():
    h = Hit(pos=Fraction(1, 4), inst="snare", raw=(7, 9), edited=True)
    d = h.to_dict()
    assert d["raw"] == [7, 9] and d["edited"] is True
    assert Hit.from_dict(d) == h
    plain = Hit.from_dict({"pos": "1/4", "inst": "snare"})  # a chart from before provenance
    assert plain.raw is None and plain.edited is False and "raw" not in plain.to_dict()
    for bad in (["1"], [-1], [True], "3"):
        with pytest.raises(ScoreError):
            Hit.from_dict({"pos": "0", "inst": "kick", "raw": bad})


def test_the_detection_log_is_never_part_of_score_json():
    s = spec()
    s.detections = {"format": "drum-agent detections", "strokes": []}
    assert "detections" not in json.dumps(s.to_dict())


# ---- the quantizer says what happened to every onset that isn't its own note --------

def test_quantize_traces_merges_off_grid_onsets_and_hihat_conflicts():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    bars = [BarDef(0, TimeSig.parse("4/4"), 4)]
    onsets = [Onset(0.0, "kick", velocity=80, ids=(1,)), Onset(0.004, "kick", velocity=100, ids=(2,)),
              Onset(-1.0, "snare", ids=(3,)),  # before the first beat (later ones fold into the last beat)
              Onset(0.25, "hihat", confidence=0.9, ids=(4,)), Onset(0.25, "hihat_open", confidence=0.5, ids=(5,))]
    res = quantize(onsets, beats, bars)
    hits = {h.inst: h for h in res.measures[0].hits}
    assert hits["kick"].raw == (2,)  # the louder detection is the note
    assert hits["hihat"].raw == (4,) and "hihat_open" not in hits
    assert sorted(res.trace) == sorted([((1,), "merged", (2,)), ((3,), "off_grid", ()),
                                        ((5,), "hihat_conflict", (4,))])


# ---- a real transcription keeps every stroke ------------------------------------------

@pytest.fixture(scope="module")
def take(tmp_path_factory):
    from drum_agent.audio.transcribe import load_audio
    from drum_agent.synth import synthesize
    wav = synthesize(spec(bars=4), tmp_path_factory.mktemp("log") / "take.wav", method="numpy")
    return load_audio(wav)


@pytest.mark.parametrize("detector", ["classifier", "nmf"])
def test_every_detected_stroke_is_accounted_for(take, detector):
    from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio
    score = transcribe_audio(take, TranscribeOptions(separate="off", detector=detector), title="t")
    log = score.detections
    assert log["format"] == "drum-agent detections" and log["version"] == 2 and log["sample_rate"] == 44100
    strokes = {s["id"]: s for s in log["strokes"]}
    assert strokes and all(s["fate"] != "unaccounted" for s in strokes.values())
    assert sum(log["summary"]["fates"].values()) == len(strokes)
    hits = [h for m in score.measures for h in m.hits]
    assert hits and all(h.raw for h in hits)  # every note names the strokes it came from
    for bar, m in enumerate(score.measures, start=1):
        for h in m.hits:
            for sid in h.raw:
                assert strokes[sid]["bar"] == bar and strokes[sid]["notated_as"] == h.inst
    for s in strokes.values():
        assert abs(s["sample"] - max(0.0, s["time"]) * 44100) <= 3  # the time is rounded to 0.1 ms
        if s["fate"] in ("merged", "dropped"):
            assert s["reason"] and "bar" not in s
        if "cand" in s:  # what the candidate was accepted as (before any cymbal smoothing)
            assert s.get("relabelled_from", s["inst"]) in log["candidates"][s["cand"]]["accepted"]
    assert score.analysis["dropped_hits"] == log["summary"]["fates"].get("dropped", 0)
    assert score.analysis["merged_hits"] == log["summary"]["fates"].get("merged", 0)
    if detector == "classifier":  # the network's probabilities for every candidate it looked at
        assert all(set(c["probs"]) == set(log["classes"]) for c in log["candidates"])
        assert log["thresholds"] and log["detector"].startswith("classifier")


def test_export_writes_the_detection_log_beside_the_chart(take, tmp_path):
    from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio
    from drum_agent.pipeline import ExportOptions, export_all
    score = transcribe_audio(take, TranscribeOptions(separate="off"), title="t")
    report = export_all(score, tmp_path, "song", options=ExportOptions(formats=("json",), verify=False))
    written = json.loads((tmp_path / "song.detections.json").read_text(encoding="utf-8"))
    assert report.files["detections"] == tmp_path / "song.detections.json"
    assert written["summary"] == score.detections["summary"]
    again = Score.load(tmp_path / "song.json")
    assert [h.raw for m in again.measures for h in m.hits] == [h.raw for m in score.measures for h in m.hits]


def test_a_failed_separation_falls_back_to_the_mix(take, monkeypatch):
    from drum_agent.audio import separate
    from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio

    def broken(y, sr):
        raise RuntimeError("no model here")
    monkeypatch.setattr(separate, "available", lambda: True)
    monkeypatch.setattr(separate, "separate_drums", broken)
    score = transcribe_audio(take, TranscribeOptions(separate="auto"), title="t")
    assert score.analysis["separation"] is None
    assert any("Separating the drums from the band failed" in n for n in score.analysis["notes"])
    with pytest.raises(RuntimeError, match="no model here"):  # "on" asked for it: an error
        transcribe_audio(take, TranscribeOptions(separate="on"), title="t")


# ---- edits are marked, the original is kept --------------------------------------------

def _bar(*hits):
    return Score(measures=[Measure(time_sig=TimeSig.parse("4/4"), hits=list(hits), tempo=100)])


def test_mark_edits_marks_changes_and_keeps_the_link_to_the_strokes():
    before = _bar(Hit(pos=Fraction(0), inst="kick", raw=(1,)), Hit(pos=Fraction(1, 4), inst="snare", raw=(2,)),
                  Hit(pos=Fraction(0), inst="hihat", raw=(3,)), Hit(pos=Fraction(1, 2), inst="kick", raw=(4,)))
    # What an editor sends back: no provenance fields at all.
    after = _bar(Hit(pos=Fraction(0), inst="kick"), Hit(pos=Fraction(1, 4), inst="snare", accent=True),
                 Hit(pos=Fraction(0), inst="ride"), Hit(pos=Fraction(1, 2), inst="kick"),
                 Hit(pos=Fraction(3, 4), inst="tom1"))
    assert mark_edits(after, before) == 3
    got = {(h.pos, h.inst): h for h in after.measures[0].hits}
    assert (got[(Fraction(0), "kick")].edited, got[(Fraction(0), "kick")].raw) == (False, (1,))
    assert (got[(Fraction(1, 2), "kick")].edited, got[(Fraction(1, 2), "kick")].raw) == (False, (4,))
    assert (got[(Fraction(1, 4), "snare")].edited, got[(Fraction(1, 4), "snare")].raw) == (True, (2,))
    assert (got[(Fraction(0), "ride")].edited, got[(Fraction(0), "ride")].raw) == (True, (3,))  # was the hi-hat
    assert (got[(Fraction(3, 4), "tom1")].edited, got[(Fraction(3, 4), "tom1")].raw) == (True, None)
    again = _bar(*[Hit(pos=h.pos, inst=h.inst, accent=h.accent) for h in after.measures[0].hits])
    assert mark_edits(again, after) == 0 and all(h.edited for h in again.measures[0].hits
                                                 if h.inst in ("snare", "ride", "tom1"))  # stays marked


def test_cli_edit_in_place_keeps_the_original_once_and_marks_the_note(tmp_path, capsys):
    from drum_agent.cli import main
    p = tmp_path / "song.json"
    spec(bars=2).save(p)
    first = p.read_text(encoding="utf-8")
    assert main(["edit", str(p), "--add", "1:1/8:snare:ghost"]) == 0
    keep = tmp_path / "song.original.json"
    assert keep.read_text(encoding="utf-8") == first
    added = [h for h in Score.load(p).measures[0].hits if h.inst == "snare" and h.pos == Fraction(1, 8)]
    assert added and added[0].edited and added[0].ghost
    assert main(["edit", str(p), "--relabel", "hihat=ride"]) == 0
    assert keep.read_text(encoding="utf-8") == first  # the first original stays
    assert all(h.edited for h in Score.load(p).measures[0].hits if h.inst == "ride")
    assert "kept the unedited score" in capsys.readouterr().out


# ---- the tempo hint's unit in compound meters --------------------------------------------

def test_bpm_hint_is_quarter_notes_in_compound_meters_too():
    """6/8 at quarter = 120: dotted-quarter beats at 80 per minute. The hint is in quarter
    notes (the CLI's unit); the tracker follows dotted quarters (it was forced to 120 of them,
    and the chart came out at 180)."""
    from drum_agent.audio.beats import estimate_grid
    from drum_agent.audio.detect import DrumHit
    from drum_agent.audio.features import HOP, SR
    eighth, bars = 0.25, 16
    hits = []
    for b in range(bars):
        t0 = b * 6 * eighth
        hits.append(DrumHit(t0 + 0.1, "kick", 1.0, 100, 0.9))
        hits.append(DrumHit(t0 + 0.1 + 3 * eighth, "snare", 1.0, 100, 0.9))
        hits += [DrumHit(t0 + 0.1 + k * eighth, "hihat", 0.6, 70, 0.9) for k in range(6)]
    duration = bars * 6 * eighth + 0.5
    grid = estimate_grid(hits, np.zeros(int(duration * SR / HOP) + 1, dtype=np.float32), duration,
                         bpm_hint=120, time_signature="6/8")
    assert grid.time_sig == "6/8" and abs(grid.tempo - 120) < 6
