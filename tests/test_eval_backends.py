"""scripts/eval_backends.py without any model: output peak-picking and the class maps."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def eb():
    spec = importlib.util.spec_from_file_location("eval_backends", ROOT / "scripts" / "eval_backends.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_oaf_onsets_are_one_stroke_per_run_above_threshold_at_its_peak(eb):
    probs = np.zeros((1, 300, 8), dtype=np.float32)
    probs[0, 100:104, 0] = [0.6, 0.9, 0.7, 0.55]  # one kick, peak at frame 101
    probs[0, 200, 0] = 0.95  # another
    probs[0, 150:152, 1] = [0.2, 0.4]  # a snare below threshold: nothing
    probs[0, 50, 3] = 1.0  # the closed hi-hat output is not used (always 0 in this conversion)

    class Session:
        def run(self, names, feeds):
            assert feeds["waveform"].shape == (1, 4410) and feeds["waveform"].dtype == np.float32
            return [probs]

    strokes = eb.oaf_strokes(np.full(4410, 2.0), Session())  # clipped to [-1, 1] on the way in
    assert strokes == [pytest.approx((1.01 + eb.OAF_OFFSET, "kick")), pytest.approx((2.0 + eb.OAF_OFFSET, "kick"))]


def test_every_mapped_class_is_one_the_classifier_and_mdb_know(eb):
    from drum_agent.audio.classifier import CLASSES, FAMILY
    for cls in list(eb.OAF_CHANNELS.values()) + list(eb.ADT_PITCHES.values()):
        assert cls in CLASSES and FAMILY[cls] == eb.MDB_OF[cls]
    assert {eb.ADT_PITCHES[p] for p in (42, 43, 44)} <= {"hihat", "hihat_pedal", "hihat_open"}
    for name, m in eb.MODELS.items():  # pinned: a revision, and a checksum for every weights file
        assert len(m["rev"]) == 40 and any(sha for sha in m["files"].values())
        assert eb.model_dir(name).parts[-1] == m["rev"]
