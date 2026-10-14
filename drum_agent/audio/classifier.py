"""Onset classifier: which drums sound at each candidate onset.

The detector's front end finds candidate onsets with high recall (measured on
real recordings: 86-100% of every drum class). Deciding what sounded there is
the hard part, and hand-written rules over GM-soundfont templates didn't
transfer to real kits. This module does it with a small neural network (a
multi-layer perceptron) trained on synthesized performances from ~40 sampled
kits with randomized rooms, mixes and band accompaniment
(scripts/adt/train.py, docs/MODELS.md). Inference is plain numpy; the weights
are an .npz file (data, never code).

Features per candidate are level-invariant log-mel views: the attack frames,
the decay (up to ~200 ms, which separates open from closed hi-hat and crash
from ride), the percussive part (HPSS) of the attack, the new energy versus
just before the onset (what this stroke added on top of ringing cymbals),
plus loudness and the gaps to the neighbouring candidates.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

from .features import HOP, SR, band_centers

# DRUM_AGENT_ONSET_MODEL points at another weights file (used to evaluate a model before it ships).
MODEL_PATH = Path(os.environ.get("DRUM_AGENT_ONSET_MODEL")
                  or Path(__file__).resolve().parents[1] / "data" / "onset_classifier.npz")
CLASSES = ("kick", "snare", "cross_stick", "hihat", "hihat_open", "hihat_pedal", "ride", "ride_bell",
           "crash", "tom", "other")
FRAME = HOP / SR
EDGE = 40  # frames of padding so every window exists
ATTACK = (-1, 0, 1, 2, 3, 4, 5)
DECAY = ((6, 10), (10, 16), (16, 24), (24, 36))
PERC = (0, 1, 2, 3, 4)
FEATURE_DIM = 96 + 96 * len(ATTACK) + 48 * len(DECAY) + 48 * len(PERC) + 96 + 4
HANDS = ("snare", "cross_stick", "hihat", "hihat_open", "ride", "ride_bell", "crash", "tom")
# Same-family alternatives: a near-miss rival makes the chosen label less certain.
RIVALS = {"hihat": ("ride", "hihat_open", "crash"), "hihat_open": ("hihat", "crash", "ride"),
          "ride": ("hihat", "crash", "ride_bell"), "ride_bell": ("ride",), "crash": ("hihat_open", "ride"),
          "snare": ("tom", "cross_stick"), "cross_stick": ("snare",), "tom": ("snare", "kick"),
          "kick": ("tom",), "hihat_pedal": ("hihat",)}
# Frequency region in which each class's loudness is measured.
REGION = {"kick": (30, 150), "snare": (150, 5000), "cross_stick": (300, 5000), "tom": (60, 600),
          "hihat": (4000, 17000), "hihat_open": (4000, 17000), "hihat_pedal": (2000, 17000),
          "ride": (2500, 17000), "ride_bell": (1500, 17000), "crash": (2500, 17000)}


def model_available(path: Path = MODEL_PATH) -> bool:
    return path.exists()


class OnsetClassifier:
    def __init__(self, path: Path = MODEL_PATH):
        d = np.load(path, allow_pickle=False)
        self.classes = tuple(str(c) for c in d["classes"])
        n_layers = int(d["n_layers"])
        self.W = [d[f"W{i}"].astype(np.float32) for i in range(n_layers)]
        self.b = [d[f"b{i}"].astype(np.float32) for i in range(n_layers)]
        self.mu = d["mu"].astype(np.float32)
        self.sd = d["sd"].astype(np.float32)
        self.thresholds = d["thresholds"].astype(np.float32)
        self.version = str(d["version"]) if "version" in d else "?"
        if self.mu.shape[0] != FEATURE_DIM:
            raise ValueError(f"{path.name}: model expects {self.mu.shape[0]} features, this code makes {FEATURE_DIM}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        h = (X - self.mu) / self.sd
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            h = h @ W + b
            if i < len(self.W) - 1:
                np.maximum(h, 0, out=h)
        return 1.0 / (1.0 + np.exp(-np.clip(h, -30, 30)))


@lru_cache(maxsize=2)
def load_model(path: str = str(MODEL_PATH)) -> OnsetClassifier:
    return OnsetClassifier(Path(path))


def onset_features(M_full: np.ndarray, M_perc: np.ndarray, flux: np.ndarray, cand: np.ndarray) -> np.ndarray:
    """(n_candidates, FEATURE_DIM) float32 features; see the module docstring."""
    cand = np.asarray(cand, dtype=int)
    n = len(cand)
    if n == 0:
        return np.zeros((0, FEATURE_DIM), dtype=np.float32)
    g = max(float(np.percentile(M_full.sum(axis=0), 95)) / M_full.shape[0], 1e-9)
    L = np.log10(M_full / g + 1e-4).astype(np.float32)
    Lp = np.log10(M_perc / g + 1e-4).astype(np.float32)
    floor = np.float32(-4.0)
    L = np.pad(L, ((0, 0), (EDGE, EDGE)), constant_values=floor)
    Lp = np.pad(Lp, ((0, 0), (EDGE, EDGE)), constant_values=floor)
    L48 = 0.5 * (L[0::2] + L[1::2])
    Lp48 = 0.5 * (Lp[0::2] + Lp[1::2])
    idx = cand + EDGE
    pre = (L[:, idx - 4] + L[:, idx - 3] + L[:, idx - 2]).T / 3  # (n, 96)
    att = np.stack([L[:, idx + o].T for o in ATTACK], axis=1)  # (n, 7, 96)
    dec = np.stack([np.mean(np.stack([L48[:, idx + o].T for o in range(a, b)], axis=0), axis=0) for a, b in DECAY],
                   axis=1)  # (n, 4, 48)
    per = np.stack([Lp48[:, idx + o].T for o in PERC], axis=1)  # (n, 5, 48)
    peak = att[:, 1:5].max(axis=1)  # (n, 96): frames 0..3
    rise = peak - pre
    ref = peak.max(axis=1, keepdims=True)  # the stroke's own level
    fpad = np.pad(flux, (EDGE, EDGE))
    p99 = float(np.percentile(flux, 99)) + 1e-9
    fl = np.log1p(np.maximum(fpad[idx - 1], np.maximum(fpad[idx], fpad[idx + 1])) / p99)
    t = cand * FRAME
    gap_prev = np.diff(t, prepend=t[0] - 1.0)
    gap_next = np.diff(t, append=t[-1] + 1.0)
    ctx = np.stack([ref[:, 0], fl, np.log(np.clip(gap_prev, 0.005, 1.0)), np.log(np.clip(gap_next, 0.005, 1.0))],
                   axis=1)
    X = np.concatenate([pre - ref, (att - ref[:, None, :]).reshape(n, -1), (dec - ref[:, None, :1]).reshape(n, -1),
                        (per - ref[:, None, :1]).reshape(n, -1), rise, ctx], axis=1)
    return X.astype(np.float32)


def _region_energy(M: np.ndarray) -> dict[str, np.ndarray]:
    centers = band_centers()
    return {c: M[(centers >= lo) & (centers <= hi)].sum(axis=0) for c, (lo, hi) in REGION.items()}


def _rise(a: np.ndarray, t: int) -> float:
    T = len(a)
    hi = a[max(0, t - 1):min(T, t + 5)].max()
    lo = a[max(0, t - 6):max(1, t)].min()
    return float(max(0.0, hi - lo))


def _tom_pitch(y: np.ndarray, frame: int) -> float | None:
    """Fundamental of a tom stroke (Hz): spectral peak 50-500 Hz, 10-170 ms after the onset."""
    i0 = frame * HOP + int(0.01 * SR)
    seg = y[i0:i0 + int(0.16 * SR)]
    if len(seg) < 1024:
        return None
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=16384))
    freqs = np.fft.rfftfreq(16384, 1 / SR)
    band = (freqs >= 50) & (freqs <= 500)
    if not band.any() or spec[band].max() <= 0:
        return None
    return float(freqs[band][np.argmax(spec[band])])


def assign_toms(pitches: list[float | None]) -> list[str]:
    """Tom ids from pitches within one recording: clusters, highest = tom1."""
    vals = [np.log2(p) for p in pitches if p]
    if not vals:
        return ["tom1"] * len(pitches)
    order = sorted(vals)
    clusters: list[list[float]] = [[order[0]]]
    for v in order[1:]:
        if v - clusters[-1][-1] > 2 / 12:  # more than two semitones: another drum
            clusters.append([v])
        else:
            clusters[-1].append(v)
    # Tiny clusters (a stray reading) join their nearest neighbour; at most four toms.
    def merge_once() -> bool:
        if len(clusters) <= 1:
            return False
        sizes = [len(c) for c in clusters]
        small = [i for i, s in enumerate(sizes) if s < max(2, 0.05 * len(vals))]
        if not small and len(clusters) <= 4:
            return False
        i = small[0] if small else int(np.argmin([np.mean(clusters[j + 1]) - np.mean(clusters[j])
                                                  for j in range(len(clusters) - 1)]))
        j = i + 1 if i == 0 else i - 1 if i == len(clusters) - 1 else (
            i + 1 if np.mean(clusters[i + 1]) - np.mean(clusters[i]) < np.mean(clusters[i]) - np.mean(clusters[i - 1])
            else i - 1)
        clusters[min(i, j)] = sorted(clusters[i] + clusters[j])
        del clusters[max(i, j)]
        return True
    while merge_once():
        pass
    centers = [float(np.mean(c)) for c in clusters]  # low -> high
    k = len(centers)
    if k == 1:
        names_low_to_high = ["floor_tom" if 2 ** centers[0] < 105 else "tom1"]
    else:
        names = {2: ["floor_tom", "tom1"], 3: ["floor_tom", "tom2", "tom1"],
                 4: ["floor_tom2", "floor_tom", "tom2", "tom1"]}[k]
        names_low_to_high = names
    out = []
    for p in pitches:
        if not p:
            out.append(names_low_to_high[-1])
            continue
        v = np.log2(p)
        out.append(names_low_to_high[int(np.argmin([abs(v - c) for c in centers]))])
    return out


def classify_hits(fe, opts) -> tuple[list, dict]:
    """DrumHits for every candidate the classifier accepts (see detect.detect)."""
    from .detect import FLAM_DRUMS, PAD, DrumHit, _has_grace
    model = load_model()
    X = onset_features(fe.M_full, fe.M_perc, fe.flux, fe.cand)
    P = model.predict(X) if len(X) else np.zeros((0, len(model.classes)), dtype=np.float32)
    ci = {c: i for i, c in enumerate(model.classes)}
    sens = max(opts.sensitivity, 0.1)
    thr = np.clip(model.thresholds / sens, 0.03, 0.97)
    E = _region_energy(fe.M_perc)
    T = fe.M_perc.shape[1]
    raw: list[tuple[int, str, float, float, float]] = []  # (frame, class, p, margin, confidence)
    for k, t in enumerate(fe.cand):
        time = float(t * FRAME) - PAD
        if time < -0.02:
            continue
        p = P[k]
        acc = {c: float(p[ci[c]]) for c in model.classes if c != "other" and p[ci[c]] >= thr[ci[c]]}
        if not acc:
            continue
        margin = {c: acc[c] / thr[ci[c]] for c in acc}
        for a, b in (("hihat", "hihat_open"), ("ride", "ride_bell")):
            if a in acc and b in acc:
                acc.pop(a if margin[a] < margin[b] else b)
        if "hihat_pedal" in acc and ({"hihat", "hihat_open"} & set(acc)):
            acc.pop("hihat_pedal")  # a stick on the closed hat sounds the same instant
        if "hihat" in acc and "ride" in acc and min(margin["hihat"], margin["ride"]) < 1.6:
            acc.pop("hihat" if margin["hihat"] < margin["ride"] else "ride")  # rarely both at once
        hands = sorted((c for c in acc if c in HANDS), key=lambda c: -margin[c])
        for c in hands[2:]:
            acc.pop(c)
        for c, pc in acc.items():
            th = float(thr[ci[c]])
            conf = 0.5 + 0.5 * (pc - th) / max(1e-6, 1 - th)
            rival = [float(p[ci[r]]) / float(thr[ci[r]]) for r in RIVALS.get(c, ()) if r in ci and r not in acc]
            if rival:
                amb = min(1.0, max(rival))
                conf *= 1.0 - 0.6 * amb ** 2
            raw.append((int(t), c, pc, margin[c], float(np.clip(conf, 0.0, 1.0))))
    # Loudness relative to each class's typical stroke in this recording.
    rises = {}
    for t, c, *_ in raw:
        rises.setdefault(c, []).append(_rise(E[c], t))
    typical = {c: max(float(np.percentile(v, 90)), 0.1 * max(v), 1e-12) for c, v in rises.items()}
    tom_frames = [t for t, c, *_ in raw if c == "tom"]
    tom_names = assign_toms([_tom_pitch(fe.y, t) for t in tom_frames])
    tom_iter = iter(tom_names)
    hits = []
    for t, c, pc, m, conf in raw:
        inst = next(tom_iter) if c == "tom" else c
        strength = _rise(E[c], t) / typical[c]
        vel = int(np.clip(35 + 75 * min(strength, 1.5) / 1.5, 1, 127))
        rv = None
        if inst in ("hihat", "ride"):
            k = int(np.searchsorted(fe.cand, t))
            rv = (float(P[k, ci["ride"]] / thr[ci["ride"]]), float(P[k, ci["hihat"]] / thr[ci["hihat"]]))
        hits.append(DrumHit(float(t * FRAME) - PAD, inst, round(float(strength), 3), vel, round(conf, 3),
                            ride_vs_hat=rv))
    # Flams whose grace note is too close to be its own candidate.
    last: dict[str, int] = {}
    for h in sorted(hits, key=lambda h: h.time):
        if h.inst in FLAM_DRUMS:
            f = int(round((h.time + PAD) / FRAME))
            region = E["tom"] if h.inst.startswith(("tom", "floor")) else E["snare"]
            h.flam = _has_grace(region, f, last.get(h.inst, -10 ** 9), T)
            last[h.inst] = f
    return hits, {"detector": f"classifier {model.version}", "frames": int(T)}
