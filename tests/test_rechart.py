"""Charting a transcription again from its detection log, with other hints (transcribe.rechart,
`drum-agent rechart`): the same strokes, no audio read, nothing detected again."""

import json

import pytest

from drum_agent.charts import compile_spec

GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
FILL = {"hh": "x-x-x---", "sn": "--x-xxxx", "bd": "x---x---"}


@pytest.fixture(scope="module")
def first(tmp_path_factory):
    from drum_agent.audio.transcribe import TranscribeOptions, load_audio, transcribe_audio
    from drum_agent.synth import synthesize
    spec = compile_spec({"title": "Rechart", "tempo": 100, "rights": "original",
                         "sections": [{"label": "A", "bars": [GROOVE] * 3 + [FILL]}]})
    y = load_audio(synthesize(spec, tmp_path_factory.mktemp("rc") / "take.wav", method="numpy"))
    return transcribe_audio(y, TranscribeOptions(separate="off"), title="Rechart")


def _notes(score):
    return [(str(m.time_sig), [(str(h.pos), h.inst, h.flam, h.ghost, h.accent) for h in m.hits])
            for m in score.measures]


def _tempo(score) -> float:
    return float(score.analysis["tempo_estimate"].split()[0])


def test_the_log_keeps_what_notation_was_given(first):
    log = first.detections
    assert log["version"] == 2 and log["frames"] > 0 and isinstance(log["near_misses"], list)
    given = [s for s in log["strokes"] if "hit" in s]
    assert given and all({"time", "strength", "velocity", "confidence"} <= set(s["hit"]) for s in given)
    notated = {sid for m in first.measures for h in m.hits for sid in h.raw}
    assert notated <= {s["id"] for s in given} | {i for s in given for i in s["hit"].get("also", [])}


def test_the_same_hints_give_the_same_chart(first):
    from drum_agent.audio.transcribe import TranscribeOptions, rechart
    again = rechart(json.loads(json.dumps(first.detections)), TranscribeOptions(), title="Rechart")
    assert _notes(again) == _notes(first) and _tempo(again) == _tempo(first)
    assert [h.raw for m in again.measures for h in m.hits] == [h.raw for m in first.measures for h in m.hits]
    assert again.detections["summary"] == first.detections["summary"]
    assert any(n.startswith("Charted again from the strokes detected before") for n in again.analysis["notes"])


def test_other_hints_chart_the_same_strokes_again(first):
    from drum_agent.audio.transcribe import TranscribeOptions, rechart
    waltz = rechart(first.detections, TranscribeOptions(time_signature="3/4"), title="Rechart")
    assert {str(m.time_sig) for m in waltz.measures} == {"3/4"} and len(waltz.measures) > len(first.measures)
    assert "unaccounted" not in waltz.detections["summary"]["fates"]
    assert any("3/4" in n for n in waltz.analysis["notes"])
    slow = rechart(first.detections, TranscribeOptions(bpm=50), title="Rechart")
    assert abs(_tempo(slow) - 50) < 3 and abs(_tempo(first) - 100) < 3
    notes = lambda s: sum(len(m.hits) for m in s.measures)  # noqa: E731
    assert abs(notes(slow) - notes(first)) <= 0.1 * notes(first)


def test_a_log_from_before_version_2_is_refused(first):
    from drum_agent.audio.transcribe import TranscribeOptions, rechart
    old = {**first.detections, "version": 1}
    with pytest.raises(ValueError, match="version 1"):
        rechart(old, TranscribeOptions())
    with pytest.raises(ValueError, match="not a drum-agent detection log"):
        rechart({"format": "something else"}, TranscribeOptions())


def test_cli_rechart_writes_a_new_chart_and_keeps_the_basis(first, tmp_path, capsys):
    from drum_agent.cli import main
    from drum_agent.model import Score
    first.rights, first.artist = "original", "The Band"
    first.save(tmp_path / "song.json")
    (tmp_path / "song.detections.json").write_text(json.dumps(first.detections), encoding="utf-8")
    assert main(["rechart", str(tmp_path / "song.json"), "--time-signature", "3/4", "-o", str(tmp_path),
                 "--formats", "json"]) == 0
    redone = Score.load(tmp_path / "song-rechart.json")
    assert redone.rights == "original" and redone.artist == "The Band" and redone.title == "Rechart"
    assert {str(m.time_sig) for m in redone.measures} == {"3/4"}
    assert json.loads((tmp_path / "song-rechart.detections.json").read_text(encoding="utf-8"))["version"] == 2
    (tmp_path / "song.detections.json").unlink()
    with pytest.raises(SystemExit, match="detections.json not found"):
        main(["rechart", str(tmp_path / "song.json"), "-o", str(tmp_path), "--formats", "json"])
