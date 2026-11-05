"""A second opinion for the onset classifier (classifier.Evidence) and the transcriber's check of
separated drums against the band mix they came from (transcribe.BAND_MIX_CHECK)."""

import pytest

from drum_agent.audio.classifier import Evidence, model_available
from drum_agent.charts import compile_spec

pytestmark = pytest.mark.skipif(not model_available(), reason="the onset classifier's weights are not installed")

GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}


@pytest.fixture(scope="module")
def take(tmp_path_factory):
    from drum_agent.audio.transcribe import load_audio
    from drum_agent.synth import synthesize
    spec = compile_spec({"title": "Evidence", "tempo": 100, "rights": "original",
                         "sections": [{"label": "A", "bars": [GROOVE] * 4}]})
    return load_audio(synthesize(spec, tmp_path_factory.mktemp("ev") / "take.wav", method="numpy"))


def test_evidence_compares_drum_families_within_its_window():
    ev = Evidence([(1.0, "hihat_open"), (2.0, "floor_tom"), (3.0, "ride")],
                  agree={"TT": 0.5}, alone={"HH": 2.0}, window=0.03)
    assert ev.heard("HH", 1.02) and not ev.heard("HH", 1.04)  # an open hat is a hi-hat stroke
    assert ev.heard("TT", 2.0) and ev.heard("CY", 2.99) and not ev.heard("KD", 1.0)
    assert ev.factor("hihat", 1.01) == 1.0  # heard: no "agree" factor for HH given
    assert ev.factor("hihat_pedal", 1.5) == 2.0  # not heard: the "alone" factor
    assert ev.factor("tom", 2.01) == 0.5 and ev.factor("tom", 5.0) == 1.0
    assert ev.factor("other", 1.0) == 1.0 and ev.factor("kick", 1.0) == 1.0


def _strokes(det):
    return sorted((round(h.time, 3), h.inst) for h in det.hits)


def test_thresholds_move_only_where_the_other_model_is_silent(take):
    from drum_agent.audio.detect import DetectOptions, detect
    opts = DetectOptions(drums_only=True, method="classifier")
    base = detect(take, opts)
    hats = [h for h in base.hits if h.inst.startswith("hihat")]
    assert hats and any(h.inst == "kick" for h in base.hits)

    # The other model heard every stroke we did: nothing changes.
    agreeing = Evidence([(h.time, h.inst) for h in base.hits], source="twin", alone={"HH": 2.0, "KD": 2.0})
    assert _strokes(detect(take, opts, evidence=agreeing)) == _strokes(base)

    # It heard nothing: hi-hats need twice their threshold, the other drums are untouched.
    silent = detect(take, opts, evidence=Evidence([], source="deaf", alone={"HH": 2.0}))
    assert [s for s in _strokes(silent) if not s[1].startswith("hihat")] == \
           [s for s in _strokes(base) if not s[1].startswith("hihat")]
    assert len([h for h in silent.hits if h.inst.startswith("hihat")]) <= len(hats)
    assert silent.log.detector.endswith("+ deaf")
    moved = [c["thresholds"] for c in silent.log.candidates if "thresholds" in c]
    assert moved and all(set(m) <= {"hihat", "hihat_open", "hihat_pedal"} for m in moved)


def test_a_stroke_only_the_other_model_heard_can_be_added(take):
    from drum_agent.audio.detect import DetectOptions, detect
    opts = DetectOptions(drums_only=True, method="classifier")
    base = detect(take, opts)
    weighed = sorted(c["time"] for c in base.log.candidates if "gate" not in c)
    # Halfway between two candidates a quarter-second apart: no candidate of ours is near.
    t = next(a + (b - a) / 2 for a, b in zip(weighed, weighed[1:]) if b - a > 0.25)
    ev = Evidence([(t, "kick")], source="other", add=frozenset({"KD"}))
    det = detect(take, opts, evidence=ev)
    added = [h for h in det.hits if h.inst == "kick" and abs(h.time - t) < 1e-3]
    assert len(added) == 1 and len(det.hits) == len(base.hits) + 1
    cand = next(c for c in det.log.candidates if c.get("source") == "other")
    assert "probs" not in cand and cand["accepted"] == ["kick"]
    # Not added where a candidate of ours was weighed (the classifier said no there, or yes).
    near = Evidence([(weighed[0] + 0.01, "crash")], source="other", add=frozenset({"CY"}))
    assert len(detect(take, opts, evidence=near).hits) == len(base.hits)


def test_separated_drums_are_checked_against_the_band_mix(take, monkeypatch):
    from drum_agent.audio import separate
    from drum_agent.audio import transcribe as tx
    seen = []
    real_detect = tx.detect

    def spy(y, options=None, evidence=None):
        seen.append((options.drums_only, evidence))
        return real_detect(y, options, evidence=evidence)

    monkeypatch.setattr(separate, "available", lambda: True)
    monkeypatch.setattr(separate, "separate_drums", lambda y, sr: y)  # "separated": the same audio
    monkeypatch.setattr(tx, "detect", spy)
    score = tx.transcribe_audio(take, tx.TranscribeOptions(separate="auto"), title="t")
    assert score.analysis["separation"] == separate.MODEL
    (mix_only, none), (stem_only, ev) = seen  # the band mix first, then the separated drums
    assert mix_only is False and none is None and stem_only is True
    assert isinstance(ev, Evidence) and ev.source == "band mix" and ev.alone == tx.BAND_MIX_CHECK
    assert "band mix" in score.detections["detector"]

    seen.clear()  # no separation: no band mix to check against
    tx.transcribe_audio(take, tx.TranscribeOptions(separate="off"), title="t")
    assert [e for _, e in seen] == [None]
    seen.clear()  # the NMF detector takes no evidence
    tx.transcribe_audio(take, tx.TranscribeOptions(separate="auto", detector="nmf"), title="t")
    assert [e for _, e in seen] == [None]
