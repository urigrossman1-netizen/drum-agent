"""Rhythm spelling: exact hit positions -> notated tokens.

This module turns one bar's hits for one voice into a list of `Token`s
(notes, chords, rests) with written values, dots, tuplets, ties and beam
levels. Every exporter reads these tokens, so the LilyPond and MusicXML output
cannot disagree about rhythm or beaming.

Rules are in docs/NOTATION_SPEC.md §4. In short:
* each beat gets the simplest grid that holds its onsets (tuplets if needed);
* a note lasts until the next onset in its voice or the end of the beat;
* rests follow the metrical hierarchy (bar > half bar > beat > subdivision);
* beams group by beat (8ths in 4/4 may pair up by half bar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .kit import DEFAULT_KIT, Kit
from .model import Hit, Measure, TimeSig, is_power_of_two_fraction


class SpellingError(ValueError):
    """The bar contains a rhythm this engraver cannot write correctly."""


@dataclass
class Token:
    kind: str  # "note" | "rest" | "measure_rest"
    pos: Fraction  # sounding start within the bar (pickup bars start at 0)
    dur: Fraction  # sounding duration
    value: Fraction  # written undotted value (1/4, 1/8, ...)
    dots: int = 0
    tuplet: tuple[int, int] | None = None  # (actual, normal), e.g. (3, 2)
    tuplet_start: bool = False
    tuplet_stop: bool = False
    hits: list[Hit] = field(default_factory=list)
    beams: dict[int, str] = field(default_factory=dict)  # level -> begin/continue/end/forward hook/backward hook
    tie_start: bool = False
    tie_stop: bool = False
    segment: int = -1  # index of the beat segment this token belongs to

    @property
    def written(self) -> Fraction:
        return self.value * (2 - Fraction(1, 2 ** self.dots))

    @property
    def beam_levels(self) -> int:
        """Number of beams/flags for the written value (8th = 1, 16th = 2...)."""
        n, levels = self.value, 0
        while n < Fraction(1, 4):
            n *= 2
            levels += 1
        return levels

    @property
    def is_roll(self) -> bool:
        return any(h.roll is not None for h in self.hits)

    def __repr__(self) -> str:  # compact, for test failure messages
        name = "+".join(h.inst for h in self.hits) if self.hits else self.kind
        tup = f" {self.tuplet[0]}:{self.tuplet[1]}" if self.tuplet else ""
        return f"<{name} @{self.pos} 1/{1 / self.value}{'.' * self.dots}{tup}>"


@dataclass
class Segment:
    start: Fraction  # bar coordinates (a pickup bar uses the full-bar coordinates)
    length: Fraction
    n: int  # slots in the segment
    tuplet: tuple[int, int] | None
    written_slot: Fraction  # written value of one slot
    cap_half: bool  # notes may not cross the half segment unless on a coarser slot

    def slot_of(self, pos: Fraction) -> int:
        s = (pos - self.start) / self.length * self.n
        if s.denominator != 1:
            raise SpellingError(f"position {pos} is not on the {self.n}-grid of the beat at {self.start}")
        return int(s)

    def pos_of(self, slot: int) -> Fraction:
        return self.start + self.length * Fraction(slot, self.n)


def representable(written: Fraction) -> tuple[Fraction, int] | None:
    """Return (value, dots) if `written` can be a single (optionally dotted) note."""
    if is_power_of_two_fraction(written):
        return written, 0
    base = written * Fraction(2, 3)
    if is_power_of_two_fraction(base) and base <= 1:
        return base, 1
    return None


def _is_binary(length: Fraction) -> bool:
    return is_power_of_two_fraction(length)


def _is_ternary(length: Fraction) -> bool:
    return is_power_of_two_fraction(length / 3)


# Candidate grids per beat, simplest first: (slots, tuplet ratio or None).
_BINARY_GRIDS = [(1, None), (2, None), (4, None), (3, (3, 2)), (8, None), (6, (3, 2)), (12, (3, 2))]
_TERNARY_GRIDS = [(1, None), (3, None), (6, None), (2, (2, 3)), (4, (2, 3)), (12, None)]


def _make_segment(start: Fraction, length: Fraction, n: int, tuplet: tuple[int, int] | None) -> Segment:
    slot = length / n
    written = slot * Fraction(tuplet[0], tuplet[1]) if tuplet else slot
    return Segment(start, length, n, tuplet, written, cap_half=(n == 8 and tuplet is None))


def _fits(points: list[Fraction], start: Fraction, length: Fraction, n: int) -> bool:
    return all(((p - start) / length * n).denominator == 1 for p in points)


def choose_segment(start: Fraction, length: Fraction, points: list[Fraction]) -> Segment:
    if _is_binary(length):
        grids = _BINARY_GRIDS
    elif _is_ternary(length):
        grids = _TERNARY_GRIDS
    else:
        raise SpellingError(f"unsupported beat length {length}")
    for n, tup in grids:
        if _fits(points, start, length, n):
            return _make_segment(start, length, n, tup)
    detail = ", ".join(str(p - start) for p in points)
    raise SpellingError(
        f"onsets at {detail} (whole notes after the beat at {start}) need a grid finer than "
        f"32nds/sextuplets; quantize them first"
    )


def plan_segments(ts: TimeSig, points: list[Fraction], offset: Fraction) -> list[Segment]:
    """Choose one segment per beat, merging beat pairs into quarter-note triplets."""
    beats = [(s, l) for s, l in ts.beats() if s + l > offset]
    segs: list[Segment] = []
    i = 0
    halves = ts.half_bar_spans()
    while i < len(beats):
        start, length = beats[i]
        # Quarter-note triplet over a half bar of two binary beats.
        if (halves and i + 1 < len(beats) and _is_binary(length) and start >= offset
                and any(h[0] == start and h[1] == 2 * length for h in halves)):
            span = 2 * length
            pts = [p for p in points if start <= p < start + span]
            if (pts and _fits(pts, start, span, 3) and not _fits(pts, start, span, 2)
                    and not _fits(pts, start, span, 4)):
                segs.append(_make_segment(start, span, 3, (3, 2)))
                i += 2
                continue
        pts = [p for p in points if start <= p < start + length]
        if start < offset:
            pts.append(offset)
        segs.append(choose_segment(start, length, pts))
        i += 1
    return segs


def _largest_note(m: int, seg: Segment) -> int:
    """Largest slot count <= m whose written value is a single (dotted) note."""
    for k in range(m, 0, -1):
        if representable(k * seg.written_slot):
            return k
    raise SpellingError("no representable value")  # unreachable: k=1 always fits


def _rest_tokens(seg: Segment, a: int, b: int, seg_index: int) -> list[Token]:
    """Rests covering slots [a, b) aligned to the subdivision hierarchy."""
    out: list[Token] = []
    p = a
    while p < b:
        best = 1
        k = 1
        while p + k <= b:
            w = k * seg.written_slot
            if is_power_of_two_fraction(w) and p % k == 0:
                best = k
            k *= 2
        value = best * seg.written_slot
        out.append(Token("rest", seg.pos_of(p), seg.length * Fraction(best, seg.n), value,
                         tuplet=seg.tuplet, segment=seg_index))
        p += best
    return out


def _note_end_cap(seg: Segment, slot: int) -> int:
    """Latest slot a note starting at `slot` may extend to.

    On a 32nd grid, a note that starts off the 16th grid may not cross the
    middle of the beat (it would hide the 8th subdivision). Coarser grids allow
    the standard 16th syncopations (e.g. 16th-8th-16th).
    """
    if not seg.cap_half:
        return seg.n
    half = seg.n // 2
    if slot % 2 == 1 and slot < half:
        return half
    return seg.n


def spell_voice(measure: Measure, hits: list[Hit]) -> list[Token]:
    """Spell one voice of one bar."""
    ts = measure.time_sig
    bar = ts.bar_length
    length = measure.actual_length
    offset = bar - length  # pickup bars are the tail of a full bar

    if not hits:
        if offset:
            seg_tokens = _rest_fill(ts, offset)
            return _shift(seg_tokens, -offset)
        return [Token("measure_rest", Fraction(0), length, length, segment=-1)]

    chords: dict[Fraction, list[Hit]] = {}
    for h in hits:
        chords.setdefault(h.pos + offset, []).append(h)
    for pos in chords:
        chords[pos].sort(key=lambda h: (DEFAULT_KIT[h.inst].position if h.inst in DEFAULT_KIT else 0))

    # Rolls: end points must be on the grid too; nothing else may start inside a roll.
    roll_end: dict[Fraction, Fraction] = {}
    for pos, chord in chords.items():
        rolls = {h.roll for h in chord if h.roll is not None}
        if len(rolls) > 1:
            raise SpellingError(f"chord at {pos - offset} has rolls of different lengths")
        if rolls:
            roll_end[pos] = pos + rolls.pop()
    positions = sorted(chords)
    for pos, end in roll_end.items():
        inside = [p for p in positions if pos < p < end]
        if inside:
            raise SpellingError(f"roll at {pos - offset} overlaps a stroke at {inside[0] - offset} in the same voice")

    points = positions + [e for e in roll_end.values() if e < bar]
    segments = plan_segments(ts, points, offset)

    tokens: list[Token] = []
    carry: tuple[list[Hit], Fraction] | None = None  # roll continuing from a previous segment
    for si, seg in enumerate(segments):
        seg_end = seg.start + seg.length
        cursor = seg.slot_of(max(seg.start, offset)) if seg.start < offset else 0
        if carry is not None:
            chord, end = carry
            stop = min(end, seg_end)
            k = seg.slot_of(stop)
            tokens += _roll_pieces(seg, si, cursor, k, chord, first_tied=True, continues=end > seg_end)
            cursor = k
            carry = (chord, end) if end > seg_end else None
        seg_points = [p for p in positions if seg.start <= p < seg_end]
        for idx, pos in enumerate(seg_points):
            slot = seg.slot_of(pos)
            if slot > cursor:
                tokens += _rest_tokens(seg, cursor, slot, si)
            chord = chords[pos]
            if pos in roll_end:
                end = roll_end[pos]
                stop = min(end, seg_end)
                k = seg.slot_of(stop)
                tokens += _roll_pieces(seg, si, slot, k, chord, first_tied=False, continues=end > seg_end)
                cursor = k
                if end > seg_end:
                    carry = (chord, end)
                continue
            nxt = seg.slot_of(seg_points[idx + 1]) if idx + 1 < len(seg_points) else seg.n
            end_slot = min(nxt, _note_end_cap(seg, slot))
            m = _largest_note(end_slot - slot, seg)
            value, dots = representable(m * seg.written_slot)  # type: ignore[misc]
            tokens.append(Token("note", pos, seg.length * Fraction(m, seg.n), value, dots,
                                tuplet=seg.tuplet, hits=list(chord), segment=si))
            cursor = slot + m
        if cursor < seg.n:
            if cursor == 0 and not seg_points:
                # Entire beat empty: one rest of the beat's value (dotted in compound time).
                rv = representable(seg.length)
                if rv is None:
                    raise SpellingError(f"cannot write a rest for beat length {seg.length}")
                tokens.append(Token("rest", seg.start, seg.length, rv[0], rv[1], segment=si))
            else:
                tokens += _rest_tokens(seg, cursor, seg.n, si)
    if carry is not None:
        raise SpellingError("roll extends past the end of the bar")

    _mark_tuplets(tokens, segments)
    tokens = _merge_beat_rests(tokens, ts, segments, offset)
    assign_beams(tokens, segments, ts)
    return _shift(tokens, -offset) if offset else tokens


def _roll_pieces(seg: Segment, si: int, a: int, b: int, chord: list[Hit], first_tied: bool,
                 continues: bool) -> list[Token]:
    """A roll from slot a to b in one segment, split into tied representable pieces."""
    out: list[Token] = []
    p = a
    while p < b:
        k = _largest_note(b - p, seg)
        value, dots = representable(k * seg.written_slot)  # type: ignore[misc]
        out.append(Token("note", seg.pos_of(p), seg.length * Fraction(k, seg.n), value, dots,
                         tuplet=seg.tuplet, hits=list(chord), segment=si))
        p += k
    for i, t in enumerate(out):
        t.tie_stop = first_tied or i > 0
        t.tie_start = continues or i < len(out) - 1
    return out


def _rest_fill(ts: TimeSig, offset: Fraction) -> list[Token]:
    """Rests for an empty pickup bar."""
    tokens: list[Token] = []
    for si, seg in enumerate(plan_segments(ts, [], offset)):
        a = seg.slot_of(offset) if seg.start < offset else 0
        if a == 0:
            rv = representable(seg.length)
            tokens.append(Token("rest", seg.start, seg.length, rv[0], rv[1], segment=si))  # type: ignore[index]
        else:
            tokens += _rest_tokens(seg, a, seg.n, si)
    return tokens


def _shift(tokens: list[Token], delta: Fraction) -> list[Token]:
    for t in tokens:
        t.pos += delta
    return tokens


def _mark_tuplets(tokens: list[Token], segments: list[Segment]) -> None:
    for si, seg in enumerate(segments):
        if not seg.tuplet:
            continue
        group = [t for t in tokens if t.segment == si]
        if group:
            group[0].tuplet_start = True
            group[-1].tuplet_stop = True


def _merge_beat_rests(tokens: list[Token], ts: TimeSig, segments: list[Segment],
                      offset: Fraction) -> list[Token]:
    """Merge whole-beat rests into half-bar rests where the meter allows."""
    halves = ts.half_bar_spans()
    if not halves or offset:
        return tokens
    for start, length in halves:
        segs = [i for i, s in enumerate(segments) if start <= s.start < start + length]
        if len(segs) != 2:
            continue
        group = [t for t in tokens if t.segment in segs]
        if len(group) == 2 and all(t.kind == "rest" and t.dur == segments[t.segment].length for t in group):
            rv = representable(length)
            if rv is None:
                continue
            merged = Token("rest", start, length, rv[0], rv[1], segment=segs[0])
            idx = tokens.index(group[0])
            tokens = tokens[:idx] + [merged] + tokens[idx + 2:]
    return tokens


# ---------------------------------------------------------------------------
# Beaming
# ---------------------------------------------------------------------------

def _plain_eighths(group: list[Token]) -> bool:
    return (len(group) == 2 and all(t.kind == "note" and t.value == Fraction(1, 8) and t.dots == 0
                                    and t.tuplet is None and not t.tie_start and not t.tie_stop
                                    for t in group))


def assign_beams(tokens: list[Token], segments: list[Segment], ts: TimeSig) -> None:
    groups: list[list[Token]] = []
    for si in range(len(segments)):
        g = [t for t in tokens if t.segment == si]
        if g:
            groups.append(g)
    # 4/4: pair two beats of plain 8ths in the same half bar into one beam of four.
    if ts.num == 4 and ts.den == 4:
        merged: list[list[Token]] = []
        i = 0
        while i < len(groups):
            g = groups[i]
            if (i + 1 < len(groups) and _plain_eighths(g) and _plain_eighths(groups[i + 1])
                    and g[0].pos in (Fraction(0), Fraction(1, 2))
                    and groups[i + 1][0].pos == g[0].pos + Fraction(1, 4)):
                merged.append(g + groups[i + 1])
                i += 2
            else:
                merged.append(g)
                i += 1
        groups = merged

    for g in groups:
        run: list[Token] = []
        for t in g + [None]:  # type: ignore[list-item]
            if t is not None and t.kind in ("note", "rest") and t.value <= Fraction(1, 8):
                run.append(t)
                continue
            _beam_run(run)
            run = []


def _beam_run(run: list[Token]) -> None:
    # Trim rests at the edges; beams start and end on notes.
    while run and run[0].kind != "note":
        run = run[1:]
    while run and run[-1].kind != "note":
        run = run[:-1]
    if sum(1 for t in run if t.kind == "note") < 2:
        return
    for i, t in enumerate(run):
        t.beams[1] = "begin" if i == 0 else ("end" if i == len(run) - 1 else "continue")
    max_level = max(t.beam_levels for t in run if t.kind == "note")
    for level in range(2, max_level + 1):
        i = 0
        while i < len(run):
            if run[i].kind == "note" and run[i].beam_levels >= level:
                j = i
                while j + 1 < len(run) and run[j + 1].kind == "note" and run[j + 1].beam_levels >= level:
                    j += 1
                if j > i:
                    for k in range(i, j + 1):
                        run[k].beams[level] = "begin" if k == i else ("end" if k == j else "continue")
                else:
                    t = run[i]
                    if i == 0:
                        t.beams[level] = "forward hook"
                    elif i == len(run) - 1:
                        t.beams[level] = "backward hook"
                    else:
                        index = (t.pos - run[0].pos) / t.dur
                        t.beams[level] = "backward hook" if index.numerator % 2 else "forward hook"
                i = j + 1
            else:
                i += 1


# ---------------------------------------------------------------------------
# Whole bars
# ---------------------------------------------------------------------------

@dataclass
class SpelledMeasure:
    voices: dict[int, list[Token]]  # 1 = hands (up), 2 = feet (down)
    shared_rest: bool  # both voices empty: print one rest only (in voice 1)


def spell_measure(measure: Measure, kit: Kit = DEFAULT_KIT) -> SpelledMeasure:
    by_voice: dict[int, list[Hit]] = {1: [], 2: []}
    for h in measure.hits:
        by_voice[kit[h.inst].voice].append(h)
    if not by_voice[1] and not by_voice[2]:
        rest = spell_voice(measure, [])
        return SpelledMeasure({1: rest, 2: []}, shared_rest=True)
    return SpelledMeasure({v: spell_voice(measure, hs) for v, hs in by_voice.items()}, shared_rest=False)


def check_tokens(tokens: list[Token], measure: Measure) -> None:
    """Assert the tokens tile the bar exactly (used by exporters and tests)."""
    total = sum((t.dur for t in tokens), Fraction(0))
    if tokens and total != measure.actual_length:
        raise SpellingError(f"spelled durations add up to {total}, bar is {measure.actual_length}: {tokens}")
    pos = Fraction(0)
    for t in tokens:
        if t.pos != pos:
            raise SpellingError(f"gap/overlap at {pos}: {tokens}")
        pos += t.dur
