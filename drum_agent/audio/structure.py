"""Section boundaries from the transcribed bars (pattern-based, not semantic).

A new section starts where the groove changes for at least two bars (main
cymbal switches between hi-hat and ride, or the kick/snare pattern changes),
typically marked by a crash on the downbeat after a fill. Sections get
sequential rehearsal letters (A, B, C ...), as in professional charts; names
like Verse/Chorus need lyrics or a human, so they're applied with --sections.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction

from ..model import Measure

TOMS = {"tom1", "tom2", "floor_tom", "floor_tom2"}
CYM = {"hihat": "hihat", "hihat_open": "hihat", "hihat_half": "hihat", "ride": "ride", "ride_bell": "ride"}


def _main_cymbal(m: Measure) -> str | None:
    c = Counter(CYM[h.inst] for h in m.hits if h.inst in CYM)
    return c.most_common(1)[0][0] if c else None


def _groove(m: Measure) -> frozenset:
    grid = Fraction(1, 16)
    return frozenset((round(h.pos / grid), h.inst) for h in m.hits if h.inst in ("kick", "snare"))


def _is_fill(m: Measure) -> bool:
    toms = sum(1 for h in m.hits if h.inst in TOMS)
    snares = sum(1 for h in m.hits if h.inst == "snare")
    return toms >= 3 or snares >= 6


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def find_sections(measures: list[Measure], min_len: int = 4) -> list[int]:
    """Indices of bars that start a section (always includes the first full bar)."""
    n = len(measures)
    start = 1 if n and measures[0].is_pickup else 0
    if n - start <= 0:
        return [0]
    cym = [_main_cymbal(m) for m in measures]
    grooves = [_groove(m) for m in measures]
    fills = [_is_fill(m) for m in measures]
    crash1 = [any(h.inst in ("crash", "crash2", "china") and h.pos == 0 for h in m.hits) for m in measures]
    bounds = [start]
    for b in range(start + 1, n):
        if b - bounds[-1] < min_len:
            continue
        changed_cym = cym[b] is not None and cym[b - 1] is not None and cym[b] != cym[b - 1] \
            and (b + 1 >= n or cym[b + 1] == cym[b])
        prev = [g for g, f in zip(grooves[max(bounds[-1], b - 4):b], fills[max(bounds[-1], b - 4):b]) if not f]
        nxt = [g for g, f in zip(grooves[b:b + 4], fills[b:b + 4]) if not f]
        groove_change = bool(prev and nxt) and max(_jaccard(p, q) for p in prev for q in nxt) < 0.5
        meter_change = str(measures[b].time_sig) != str(measures[b - 1].time_sig)
        # A crash after a fill marks a phrase; a section also needs the groove to change.
        marked = crash1[b] or fills[b - 1]
        if meter_change or measures[b].tempo is not None or ((changed_cym or groove_change) and marked) \
                or (changed_cym and groove_change):
            bounds.append(b)
    return bounds


def label_sections(measures: list[Measure]) -> list[dict]:
    """Set Measure.section to A, B, C ... and return a roadmap."""
    bounds = find_sections(measures)
    roadmap = []
    for k, b in enumerate(bounds):
        letter = chr(ord("A") + k) if k < 26 else f"S{k + 1}"
        measures[b].section = letter
        end = bounds[k + 1] if k + 1 < len(bounds) else len(measures)
        span = measures[b:end]
        roadmap.append({
            "label": letter,
            "first_bar": b + 1,
            "bars": end - b,
            "main_cymbal": Counter(c for c in (_main_cymbal(m) for m in span) if c).most_common(1)[0][0]
            if any(_main_cymbal(m) for m in span) else None,
            "fills": sum(1 for m in span if _is_fill(m)),
            "start_time": span[0].start_time,
        })
    return roadmap
