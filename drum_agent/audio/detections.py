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

Since version 2, each stroke the detector passed on to notation carries "hit": the exact
time, strength, velocity, confidence and flags (flam, ghost, accent; "also": its flam's
grace strokes) that charting read, and the log keeps the near misses. That is enough to
chart the recording again with other hints without reading the audio
(audio/transcribe.py `rechart`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import SR

FORMAT = "drum-agent detections"
VERSION = 2  # 2: strokes passed to notation carry "hit"; near misses are kept (charts can be redone)
CHARTING_FIELDS = ("fate", "reason", "into", "bar", "pos", "notated_as")  # what charting writes on a stroke


@dataclass
class DetectionLog:
    detector: str = ""
    classes: list[str] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    strokes: list[dict[str, Any]] = field(default_factory=list)
    near_misses: list[list] = field(default_factory=list)  # [time, class, share of its threshold]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DetectionLog":
        """A stored log, ready to chart its strokes again: what charting wrote on the strokes it
        was given (their fate, bar and position) is cleared; what the detector decided stays."""
        if d.get("format") != FORMAT:
            raise ValueError("not a drum-agent detection log")
        if int(d.get("version", 0)) < 2:
            raise ValueError("this detection log was written before charts could be made again from it "
                             "(format version 1); transcribe the recording again")
        log = cls(detector=str(d.get("detector", "")), classes=list(d.get("classes", [])),
                  thresholds=dict(d.get("thresholds", {})), candidates=[dict(c) for c in d.get("candidates", [])],
                  near_misses=[list(x) for x in d.get("near_misses", [])])
        for s in d.get("strokes", []):
            s = dict(s)
            if "hit" in s:
                for k in CHARTING_FIELDS:
                    s.pop(k, None)
            log.strokes.append(s)
        return log

    def mark_detected(self, hits, near_misses=()) -> None:
        """Record what the detector passed on to notation (`Detection.hits`, after flams, cymbal
        smoothing and dynamics) at full precision, and the near misses that flag bars."""
        for h in hits:
            if 0 <= h.rid < len(self.strokes):
                hit: dict[str, Any] = {"time": float(h.time), "strength": float(h.strength),
                                       "velocity": int(h.velocity), "confidence": float(h.confidence)}
                for flag in ("flam", "ghost", "accent"):
                    if getattr(h, flag):
                        hit[flag] = True
                if h.also:
                    hit["also"] = [int(i) for i in h.also]
                self.strokes[h.rid]["hit"] = hit
        self.near_misses = [[round(float(t), 4), str(c), round(float(r), 3)] for t, c, r in near_misses]

    def detected_hits(self) -> list:
        """The strokes the detector passed on to notation, as DrumHits (see mark_detected)."""
        from .detect import DrumHit
        hits = []
        for s in self.strokes:
            h = s.get("hit")
            if h is not None:
                hits.append(DrumHit(float(h["time"]), str(s["inst"]), float(h["strength"]), int(h["velocity"]),
                                    float(h["confidence"]), flam=bool(h.get("flam")), ghost=bool(h.get("ghost")),
                                    accent=bool(h.get("accent")), rid=int(s["id"]),
                                    also=tuple(int(i) for i in h.get("also", ()))))
        return sorted(hits, key=lambda h: (h.time, h.inst))

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
                "near_misses": self.near_misses, "candidates": self.candidates, "strokes": self.strokes}


def union(*groups) -> tuple[int, ...]:
    """Stroke ids of several hits, once each, in order."""
    out: list[int] = []
    for g in groups:
        for sid in g or ():
            if sid not in out:
                out.append(sid)
    return tuple(out)
