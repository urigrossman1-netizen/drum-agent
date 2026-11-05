"""The detection log: what the detector heard, and what became of each stroke.

The chart (`model.Score`) holds the notes as notated: quantized, with the rules applied
and, later, a person's corrections. This log keeps the machine's own evidence beside it,
written as `<stem>.detections.json`. Nothing the detector heard is lost when a stroke is
merged into a slot, dropped by a rule, folded into a roll or flam, or edited away. Each
notated `Hit` names the strokes it came from in `Hit.raw` (stroke ids from this log).

    candidates  every onset candidate the detector looked at:
                {"id", "time", "sample", "probs": {class: p} (the onset classifier only),
                 "accepted": [classes], "rejected": {class: reason}, "gate": reason it was skipped}
    strokes     every stroke the detector accepted:
                {"id", "cand", "inst", "time", "sample", "strength", "velocity", "confidence",
                 "fate", "reason", "bar", "pos", "relabelled_from"}

A stroke's fate is "notated" (its bar and position given), "flam_grace" (written as the
grace note of the flam it belongs to), "merged" (a second detection of a stroke already in
that slot), or "dropped" with a reason. Times are seconds in the input recording; samples
are at 44.1 kHz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import SR

FORMAT = "drum-agent detections"
VERSION = 1


@dataclass
class DetectionLog:
    detector: str = ""
    classes: list[str] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    strokes: list[dict[str, Any]] = field(default_factory=list)

    def candidate(self, time: float, probs: dict[str, float] | None = None, gate: str | None = None,
                  source: str | None = None) -> int:
        """A candidate onset; `source` names another model when only that model heard it."""
        cid = len(self.candidates)
        c: dict[str, Any] = {"id": cid, "time": round(float(time), 4), "sample": max(0, int(round(time * SR)))}
        if probs is not None:
            c["probs"] = {k: round(float(v), 3) for k, v in probs.items()}
        if gate:
            c["gate"] = gate
        if source:
            c["source"] = source
        self.candidates.append(c)
        return cid

    def reject(self, cid: int, cls: str, reason: str) -> None:
        self.candidates[cid].setdefault("rejected", {})[cls] = reason

    def stroke(self, time: float, inst: str, strength: float, velocity: int, confidence: float,
               cand: int | None = None) -> int:
        sid = len(self.strokes)
        s: dict[str, Any] = {"id": sid, "inst": inst, "time": round(float(time), 4),
                             "sample": max(0, int(round(time * SR))), "strength": round(float(strength), 3),
                             "velocity": int(velocity), "confidence": round(float(confidence), 3)}
        if cand is not None:
            s["cand"] = cand
            self.candidates[cand].setdefault("accepted", []).append(inst)
        self.strokes.append(s)
        return sid

    def fate(self, sid: int, fate: str, reason: str | None = None, into: tuple[int, ...] | None = None) -> None:
        if not 0 <= sid < len(self.strokes):
            return
        s = self.strokes[sid]
        s["fate"] = fate
        if reason:
            s["reason"] = reason
        if into:
            s["into"] = list(into)

    def relabel(self, sid: int, inst: str) -> None:
        if 0 <= sid < len(self.strokes) and self.strokes[sid]["inst"] != inst:
            s = self.strokes[sid]
            s.setdefault("relabelled_from", s["inst"])
            s["inst"] = inst

    def finish(self, measures, **meta: Any) -> dict[str, Any]:
        """The log as JSON-ready data, with each notated stroke's bar (1-based score bar) and
        position. A stroke with no recorded fate that no Hit names is "unaccounted" (a bug:
        tests/test_detections.py requires there are none)."""
        from ..model import frac_str
        for bar, m in enumerate(measures, start=1):
            for h in m.hits:
                for sid in h.raw or ():
                    if 0 <= sid < len(self.strokes):
                        s = self.strokes[sid]
                        s.setdefault("fate", "notated")
                        s["bar"], s["pos"], s["notated_as"] = bar, frac_str(h.pos), h.inst
        counts: dict[str, int] = {}
        for s in self.strokes:
            s.setdefault("fate", "unaccounted")
            counts[s["fate"]] = counts.get(s["fate"], 0) + 1
        return {"format": FORMAT, "version": VERSION, "sample_rate": SR, "detector": self.detector,
                "classes": list(self.classes), "thresholds": {k: round(float(v), 3) for k, v in self.thresholds.items()},
                **meta, "summary": {"candidates": len(self.candidates), "strokes": len(self.strokes),
                                    "fates": dict(sorted(counts.items()))},
                "candidates": self.candidates, "strokes": self.strokes}


def union(*groups) -> tuple[int, ...]:
    """Stroke ids of several hits, once each, in order."""
    out: list[int] = []
    for g in groups:
        for sid in g or ():
            if sid not in out:
                out.append(sid)
    return tuple(out)
