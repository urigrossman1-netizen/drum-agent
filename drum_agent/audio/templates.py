"""Drum template classes and loading."""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Detector classes -> GM notes used to build templates (scripts/build_templates.py).
CLASS_NOTES: dict[str, list[int]] = {
    "kick": [36, 35],
    "snare": [38, 40],
    "hihat": [42],
    "hihat_open": [46],
    "ride": [51, 59],
    "crash": [49, 57],
    "tom1": [50, 48],
    "tom2": [47, 45],
    "floor_tom": [43, 41],
}

DATA = Path(__file__).resolve().parents[1] / "data" / "templates.npz"


def load_templates() -> tuple[np.ndarray, list[str]]:
    if not DATA.exists():
        raise FileNotFoundError(f"{DATA} missing; run scripts/build_templates.py")
    d = np.load(DATA)
    return d["W"].astype(np.float32), [str(x) for x in d["labels"]]
