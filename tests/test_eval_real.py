"""The real-recording benchmark's scoring (scripts/eval_real.py) on a case worked out by hand."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("eval_real", ROOT / "scripts" / "eval_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scores_confusions_misses_extras_timing_and_fast_passages(ev):
    ref = [(1.000, "KD"), (1.500, "SD"),                      # found on their own class
           (2.000, "HH"),                                     # written as a cymbal (30 ms off)
           (3.000, "TT"),                                     # nothing written: missed
           (4.000, "SD"), (4.080, "SD"), (4.160, "SD")]       # a fast passage (80 ms apart)
    est = [(1.004, "KD"), (1.540, "SD"),                      # the snare 40 ms late: a match at 50, not at 30
           (2.030, "CY"),
           (4.000, "SD"), (4.160, "SD"),                      # 2 of the 3 fast strokes
           (5.000, "KD")]                                     # nothing in the recording: extra
    res = ev.score_track(ref, est)
    assert (res["KD"]["tp"], res["KD"]["tp30"], res["KD"]["ref"], res["KD"]["est"]) == (1, 1, 1, 2)
    assert (res["SD"]["tp"], res["SD"]["tp30"]) == (3, 2) and res["SD"]["err_ms"] == pytest.approx(40, abs=0.01)
    assert (res["SD"]["ref_fast"], res["SD"]["tp_fast"]) == (3, 2)
    assert res["confusion"]["HH"] == {"CY": 1}
    assert res["confusion"]["TT"] == {"missed": 1}
    assert res["confusion"]["SD"] == {"missed": 1}  # the fast stroke nobody wrote
    assert res["extra"] == {"KD": 1, "SD": 0, "HH": 0, "TT": 0, "CY": 0}

    summary = ev.summarize({("t", "mix"): res})["mix"]
    assert summary["all 5"]["tp"] == 4 and summary["all 5"]["ref"] == 7 and summary["all 5"]["est"] == 6
    assert summary["SD"]["F30"] < summary["SD"]["F"] and summary["SD"]["R_fast"] == pytest.approx(2 / 3, abs=1e-3)
    text = ev.render({"mix": summary}, "toy")
    assert "fast-passage R" in text and "missed" in text and "extra KD 1" in text


def test_a_record_names_its_commit_or_says_why_not(ev, monkeypatch, tmp_path):
    import shutil
    import types

    args = types.SimpleNamespace(separate=False)
    if ev._git_exe() is not None and (ROOT / ".git").exists():
        meta = ev._meta(args, ["t"], 1.0)
        assert meta["commit"] and all(c in "0123456789abcdef" for c in meta["commit"])
        assert meta["uncommitted_changes"] in (True, False) and "commit_unknown" not in meta

    monkeypatch.setattr(shutil, "which", lambda name: None)  # no git on PATH, none installed
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path))
    assert ev._git_exe() is None
    meta = ev._meta(args, ["t"], 1.0)
    assert meta["commit"] is None and meta["uncommitted_changes"] is None
    assert meta["commit_unknown"] == "git not found"
