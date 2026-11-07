"""Section boundaries from the transcribed bars (pattern-based, not semantic).

A new section starts where the groove changes for at least two bars (main
cymbal switches between hi-hat and ride, or the kick/snare pattern changes),
typically marked by a crash on the downbeat after a fill. Sections get
rehearsal letters (A, B, C ...), as in professional charts. A section whose
bars match an earlier one's takes its letter again, numbered (A, B, A2, B2, C):
the form shows, and every mark stays unique. Names like Verse/Chorus need
lyrics or a human, so they're applied with --sections.

A fill is a busy bar (toms, or a run of snare strokes) that isn't the section's
usual bar; it gets a "Fill" cue above the staff.
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


# A section repeats an earlier one when its bars match that section's bars this well (a bar's
# kick, snare and time-keeping cymbal on a 16th grid; measured on transcriptions, where a
# repeated groove matches at 0.8-1.0 and a different one below 0.5).
SAME_SECTION = 0.7
FILL_UNLIKE = 0.5  # a busy bar this unlike the section's usual bar (Jaccard) is a fill
FAMILY = {"kick": "kick", "kick2": "kick", "snare": "snare", "rimshot": "snare", "cross_stick": "snare",
          "hihat": "hihat", "hihat_open": "hihat", "hihat_half": "hihat", "ride": "ride", "ride_bell": "ride"}


def _bar_pattern(m: Measure) -> frozenset:
    grid = Fraction(1, 16)
    return frozenset((round(h.pos / grid), FAMILY[h.inst]) for h in m.hits if h.inst in FAMILY)


def _limbs(m: Measure) -> frozenset:
    """Kick, snare and toms on a 16th grid: what a fill changes (the time-keeping cymbal may go on)."""
    grid = Fraction(1, 16)
    return frozenset((round(h.pos / grid), "tom" if h.inst in TOMS else FAMILY[h.inst])
                     for h in m.hits if h.inst in TOMS or FAMILY.get(h.inst) in ("kick", "snare"))


def mark_fills(measures: list[Measure], bounds: list[int]) -> list[int]:
    """Indices of fill bars, each given a "Fill" cue (an existing cue is kept): busy (_is_fill)
    and unlike the usual bar of its section, so a busy groove played throughout is no fill."""
    fills = []
    for k, b in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else len(measures)
        span = measures[b:end]
        counts = Counter(_limbs(m) for m in span if m.hits)
        usual = counts.most_common(1)[0][0] if counts else None
        for i, m in enumerate(span, start=b):
            if not _is_fill(m):
                continue
            if len(span) > 1 and usual is not None and _jaccard(_limbs(m), usual) >= FILL_UNLIKE:
                continue  # the section's own groove
            fills.append(i)
            if not m.cue:
                m.cue = "Fill"
    return fills


def _signature(span: list[Measure]) -> Counter:
    """A section's bar patterns, fills left out."""
    return Counter(_bar_pattern(m) for m in span if m.hits and not _is_fill(m))


def _similarity(a: Counter, b: Counter) -> float:
    """How well each section's bars are found in the other's (the weaker direction)."""
    if not a or not b:
        return 0.0

    def into(x: Counter, y: Counter) -> float:
        return sum(n * max(_jaccard(p, q) for q in y) for p, n in x.items()) / sum(x.values())
    return min(into(a, b), into(b, a))


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
        # The cymbal of the groove before: a fill into a new section often has none, and
        # comparing with that bar would hide the change.
        before = next((cym[j] for j in range(b - 1, bounds[-1] - 1, -1) if cym[j] is not None and not fills[j]),
                      cym[b - 1])
        changed_cym = cym[b] is not None and before is not None and cym[b] != before \
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
    """Set Measure.section (A, B, A2 ...), give fill bars a "Fill" cue, and return a roadmap."""
    bounds = find_sections(measures)
    fills = set(mark_fills(measures, bounds))
    roadmap = []
    seen: list[tuple[str, Counter, int]] = []  # (letter, signature, bars) of each new section
    times: Counter = Counter()
    for k, b in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else len(measures)
        span = measures[b:end]
        sig = _signature(span)
        alike = [(_similarity(sig, s), letter) for letter, s, n in seen if 0.5 <= len(span) / n <= 2]
        best, like = max(alike, default=(0.0, None))
        if like is not None and best >= SAME_SECTION:
            times[like] += 1
            label = f"{like}{times[like]}"
        else:
            like = None
            label = chr(ord("A") + len(seen)) if len(seen) < 26 else f"S{len(seen) + 1}"
            seen.append((label, sig, len(span)))
            times[label] = 1
        measures[b].section = label
        entry = {
            "label": label,
            "first_bar": b + 1,
            "bars": end - b,
            "main_cymbal": Counter(c for c in (_main_cymbal(m) for m in span) if c).most_common(1)[0][0]
            if any(_main_cymbal(m) for m in span) else None,
            "fills": sum(1 for i in range(b, end) if i in fills),
            "start_time": span[0].start_time,
        }
        if like is not None:
            entry.update(repeat_of=like, similarity=round(best, 2))
        roadmap.append(entry)
    return roadmap
