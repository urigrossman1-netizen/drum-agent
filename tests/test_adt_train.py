"""scripts/adt/train.py ensemble: the combined file loads, and nothing is replaced unless asked."""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from drum_agent.audio.classifier import CLASSES, FEATURE_DIM, OnsetClassifier

ROOT = Path(__file__).resolve().parents[1]


def net_file(path, seed, hidden=3, n_features=FEATURE_DIM):
    """A small random network in the layout `train.py train` writes."""
    rng = np.random.default_rng(seed)
    sizes = [n_features, hidden, len(CLASSES)]
    payload = {"classes": np.array(CLASSES), "n_layers": np.array(2), "version": np.array(str(seed)),
               "mu": rng.standard_normal(n_features).astype(np.float32),
               "sd": rng.uniform(0.5, 2, n_features).astype(np.float32),
               "thresholds": rng.uniform(0.3, 0.8, len(CLASSES)).astype(np.float32)}
    for i, (m, n) in enumerate(zip(sizes, sizes[1:])):
        payload[f"W{i}"] = (rng.standard_normal((m, n)) * 0.05).astype(np.float32)
        payload[f"b{i}"] = rng.standard_normal(n).astype(np.float32)
    np.savez_compressed(path, **payload)
    return path


def ensemble(tmp_path, *args):
    # DRUM_AGENT_ONSET_MODEL keeps even a default output away from the shipped weights.
    env = dict(os.environ, DRUM_AGENT_ONSET_MODEL=str(tmp_path / "shipped.npz"))
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "adt" / "train.py"), "ensemble", *map(str, args)],
                          cwd=tmp_path, env=env, capture_output=True, text=True)


def test_an_ensemble_input_contributes_all_its_networks(tmp_path):
    a, b, c = (net_file(tmp_path / f"{k}.npz", seed) for seed, k in enumerate("abc"))
    assert ensemble(tmp_path, a, b, "--out", tmp_path / "ab.npz").returncode == 0
    r = ensemble(tmp_path, tmp_path / "ab.npz", c, "--out", tmp_path / "abc.npz")
    assert r.returncode == 0, r.stderr
    abc = OnsetClassifier(tmp_path / "abc.npz")
    singles = [OnsetClassifier(p) for p in (a, b, c)]
    assert len(abc.nets) == 3
    X = np.random.default_rng(9).standard_normal((5, FEATURE_DIM)).astype(np.float32)
    assert np.allclose(abc.predict(X), np.mean([s.predict(X) for s in singles], axis=0), atol=1e-6)
    assert np.allclose(abc.thresholds, np.mean([s.thresholds for s in singles], axis=0))
    # Readable like any file written there (the temporary it was renamed from is owner-only).
    assert (tmp_path / "abc.npz").stat().st_mode & 0o777 == a.stat().st_mode & 0o777


def test_out_is_required_and_a_bad_model_replaces_nothing(tmp_path):
    a = net_file(tmp_path / "a.npz", 0)
    bad = net_file(tmp_path / "bad.npz", 1, n_features=FEATURE_DIM - 4)  # features from other code
    r = ensemble(tmp_path, a, a)
    assert r.returncode != 0 and "--out" in r.stderr
    assert not (tmp_path / "shipped.npz").exists()
    keep = tmp_path / "keep.npz"
    keep.write_bytes(b"previous model")
    r = ensemble(tmp_path, a, bad, "--out", keep)
    assert r.returncode != 0 and "unchanged" in r.stderr
    assert keep.read_bytes() == b"previous model"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.npz", "bad.npz", "keep.npz"]  # no temporary left
