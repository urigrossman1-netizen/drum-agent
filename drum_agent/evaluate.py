"""Transcription accuracy: compare detected strokes with a reference.

Onset-level metrics (per instrument class) use optimal bipartite matching
within a time tolerance (mir_eval.util.match_events), the standard in drum
transcription research. Notation-level metrics compare (bar, position,
instrument) after quantization and need the meter, downbeat and grid to be
right as well, so they are stricter.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .model import Score

# Reference/estimate instruments are compared at this level.
EVAL_CLASS = {
    "kick": "kick", "kick2": "kick",
    "snare": "snare", "rimshot": "snare", "cross_stick": "cross_stick",
    "hihat": "hihat", "hihat_open": "hihat_open", "hihat_half": "hihat_open",
    "hihat_pedal": "hihat_pedal", "hihat_splash": "hihat_pedal",
    "ride": "ride", "ride_bell": "ride",
    "crash": "crash", "crash2": "crash", "china": "crash", "splash": "crash",
    "tom1": "tom1", "tom2": "tom2", "floor_tom": "floor_tom", "floor_tom2": "floor_tom",
    "cowbell": "cowbell",
}
# Coarser families: errors inside a family (open vs closed hat, tom 1 vs 2) are milder.
FAMILY = {"kick": "kick", "snare": "snare", "cross_stick": "snare", "hihat": "hihat", "hihat_open": "hihat",
          "hihat_pedal": "hihat", "ride": "cymbal", "crash": "cymbal", "tom1": "toms", "tom2": "toms",
          "floor_tom": "toms", "cowbell": "other"}


@dataclass
class ClassScore:
    ref: int
    est: int
    tp: int

    @property
    def precision(self) -> float:
        return self.tp / self.est if self.est else (1.0 if not self.ref else 0.0)

    @property
    def recall(self) -> float:
        return self.tp / self.ref if self.ref else (1.0 if not self.est else 0.0)

    @property
    def f(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class EvalResult:
    per_class: dict[str, ClassScore]
    per_family: dict[str, ClassScore]
    overall: ClassScore
    tolerance: float
    offsets_ms: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tolerance_s": self.tolerance,
            "overall": {"P": round(self.overall.precision, 3), "R": round(self.overall.recall, 3), "F": round(self.overall.f, 3),
                        "ref": self.overall.ref, "est": self.overall.est},
            "per_class": {c: {"P": round(s.precision, 3), "R": round(s.recall, 3), "F": round(s.f, 3), "ref": s.ref, "est": s.est}
                          for c, s in sorted(self.per_class.items())},
            "per_family": {c: {"F": round(s.f, 3), "ref": s.ref, "est": s.est} for c, s in sorted(self.per_family.items())},
            "median_offset_ms": round(float(np.median(self.offsets_ms)), 1) if self.offsets_ms else None,
        }


def score_events(score: Score, use_performed: bool = True, audible: bool = False) -> list[tuple[float, str]]:
    """(seconds, instrument) for every stroke; performed times when known.

    audible=True expands rolls into 32nd strokes and adds flam/drag grace
    strokes (as rendered by export/midi.py), i.e. what a detector can hear.
    """
    starts = score.measure_start_seconds()
    out = []
    for i, _, h in score.iter_hits():
        sec_per_whole = 4 * 60 / score.tempo_at(i)
        if use_performed and h.time is not None:
            t = h.time
        else:
            t = starts[i] + float(h.pos) * sec_per_whole
        out.append((t, h.inst))
        if audible:
            if h.roll is not None:
                k = 1
                while k * Fraction(1, 32) < h.roll:
                    out.append((t + float(k * Fraction(1, 32)) * sec_per_whole, h.inst))
                    k += 1
            if h.drag:
                out.append((t - 2 * sec_per_whole / 64, h.inst))
                out.append((t - sec_per_whole / 64, h.inst))
            # A flam's grace stroke is merged into the main stroke by the detector.
    return sorted(out)


def _match(ref: list[float], est: list[float], tol: float) -> list[tuple[int, int]]:
    import mir_eval
    if not ref or not est:
        return []
    return mir_eval.util.match_events(np.array(ref), np.array(est), tol)


def evaluate_events(ref: list[tuple[float, str]], est: list[tuple[float, str]], tolerance: float = 0.05) -> EvalResult:
    def group(events, mapping):
        g = defaultdict(list)
        for t, inst in events:
            g[mapping(inst)].append(t)
        return g

    def run(mapping) -> dict[str, ClassScore]:
        gr, ge = group(ref, mapping), group(est, mapping)
        out = {}
        for c in set(gr) | set(ge):
            r, e = sorted(gr.get(c, [])), sorted(ge.get(c, []))
            m = _match(r, e, tolerance)
            out[c] = ClassScore(len(r), len(e), len(m))
        return out

    per_class = run(lambda i: EVAL_CLASS.get(i, i))
    per_family = run(lambda i: FAMILY.get(EVAL_CLASS.get(i, i), "other"))
    overall = ClassScore(sum(s.ref for s in per_class.values()), sum(s.est for s in per_class.values()),
                         sum(s.tp for s in per_class.values()))
    # Timing offsets of matched strokes (all classes pooled).
    offsets = []
    gr, ge = group(ref, lambda i: EVAL_CLASS.get(i, i)), group(est, lambda i: EVAL_CLASS.get(i, i))
    for c in gr:
        r, e = sorted(gr[c]), sorted(ge.get(c, []))
        for i, j in _match(r, e, tolerance):
            offsets.append((e[j] - r[i]) * 1000)
    return EvalResult(per_class, per_family, overall, tolerance, offsets)


def evaluate_scores(ref: Score, est: Score, tolerance: float = 0.05) -> EvalResult:
    return evaluate_events(score_events(ref, use_performed=False), score_events(est), tolerance)


def notation_accuracy(ref: Score, est: Score) -> ClassScore:
    """Exact (bar, position, instrument class) agreement after quantization."""
    def keys(s: Score):
        return {(i, h.pos, EVAL_CLASS.get(h.inst, h.inst)) for i, _, h in s.iter_hits()}
    r, e = keys(ref), keys(est)
    return ClassScore(len(r), len(e), len(r & e))


def format_eval(res: EvalResult) -> str:
    d = res.as_dict()
    lines = [f"Onset accuracy (tolerance {int(res.tolerance * 1000)} ms): "
             f"F={d['overall']['F']:.3f} P={d['overall']['P']:.3f} R={d['overall']['R']:.3f} "
             f"(ref {d['overall']['ref']}, est {d['overall']['est']})"]
    for c, s in d["per_class"].items():
        lines.append(f"  {c:12s} F={s['F']:.3f} P={s['P']:.3f} R={s['R']:.3f}  ref={s['ref']:4d} est={s['est']:4d}")
    lines.append("  families: " + ", ".join(f"{c} {s['F']:.2f}" for c, s in d["per_family"].items()))
    if d["median_offset_ms"] is not None:
        lines.append(f"  median timing offset {d['median_offset_ms']} ms")
    return "\n".join(lines)
