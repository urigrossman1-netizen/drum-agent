"""Layout plan: exact-repeat compression and system (line) breaks.

The plan is computed once and used by both the LilyPond and MusicXML writers.
Repeats are used only for bars that are *identical* after quantization (same
hits, articulations, meter), with no tempo change, section label or
uncertainty flag on the repeated copies. Fills and variations are always
written out. `expand()` unrolls a plan back into performance order and is
checked against the score, so a plan can never drop or duplicate a bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Measure, Score
from .rhythm import spell_measure

REPEAT_MODES = ("auto", "percent", "none")


@dataclass
class PrintedBar:
    index: int  # measure index in the score (performance order)
    percent: bool = False  # printed as a one-bar simile mark repeating the previous bar
    percent_run: int = 0  # on a written bar that starts a simile run: total bars in the run
    rest_run: int = 0  # on the first bar of a multi-bar rest: total bars in the rest
    in_rest: bool = False  # a later bar of a multi-bar rest (not printed on its own)
    line_break: bool = False  # start a new system here
    volta_start: bool = False
    volta_end: bool = False
    volta_times: int = 0


@dataclass
class LayoutPlan:
    bars: list[PrintedBar]
    bars_per_line: float
    printed_numbers: dict[int, int] = field(default_factory=dict)  # measure index -> printed bar number

    def expand(self) -> list[int]:
        """Measure indices in performance order implied by the plan."""
        out: list[int] = []
        i = 0
        bars = self.bars
        while i < len(bars):
            if bars[i].volta_start:
                j = i
                while not bars[j].volta_end:
                    j += 1
                phrase = bars[i:j + 1]
                times = bars[i].volta_times
                first = [b.index for b in phrase]
                out += first
                span = len(first)
                # Later passes repeat the same bars; their measure indices follow.
                for t in range(1, times):
                    out += [b + t * span for b in first]
                i = j + 1
            else:
                out.append(bars[i].index)
                i += 1
        return out


def _clean_copy(m: Measure) -> bool:
    return m.tempo is None and m.tempo_text is None and m.section is None and not m.uncertain


def _same(a: Measure, b: Measure) -> bool:
    return a.musical_signature() == b.musical_signature()


def _empty(m: Measure) -> bool:
    return not m.hits and not m.is_pickup and not m.uncertain


def _rest_run(ms: list[Measure], idxs: list[int], p: int) -> int:
    """Consecutive empty bars from idxs[p] that read as one multi-bar rest: same meter,
    no tempo, feel or section mark after the first."""
    first = ms[idxs[p]]
    if not _empty(first):
        return 0
    run = 1
    while (p + run < len(idxs) and _empty(ms[idxs[p + run]]) and _clean_copy(ms[idxs[p + run]])
           and same_meter(first, ms[idxs[p + run]])):
        run += 1
    return run


def _weight(m: Measure) -> float:
    """Horizontal space a bar needs, in units of a plain 4/4 groove bar."""
    sm = spell_measure(m)
    n = max(len(sm.voices[1]), len(sm.voices[2]))
    tuplets = any(t.tuplet for v in sm.voices.values() for t in v)
    w = 1.0
    if n > 16:
        w = 1.5
    if n > 24:
        w = 2.0
    if tuplets and n > 10:
        w = max(w, 1.4)
    # Parenthesized ghost notes are wider than plain heads, and a sticking letter
    # under every 16th needs its own room: four such bars overflow a line.
    ghosts = sum(1 for h in m.hits if h.ghost)
    letters = sum(1 for h in m.hits if h.sticking)
    w = max(w, (n + 0.5 * ghosts) / 16, letters / 13)
    length = float(m.actual_length)
    if length > 1:  # long bars (5/4, 12/8 ...)
        w *= length
    elif n <= 8:  # short, sparse bars (pickups, 2/4, 3/4) need less room
        w *= max(0.4, length)
    return w


def _sections(score: Score) -> list[list[int]]:
    out: list[list[int]] = []
    for i, m in enumerate(score.measures):
        if i == 0 or m.section:
            out.append([])
        out[-1].append(i)
    return out


def _units(score: Score, idxs: list[int], mode: str) -> list[tuple]:
    ms = score.measures
    units: list[tuple] = []
    p = 0
    while p < len(idxs):
        if mode == "auto":
            # The phrase that saves the most written bars; on a tie the shorter one
            # (|: A B :| x8, not |: A B A B A B A B :| x2).
            found = None
            for k in (2, 4, 8):
                if p + 2 * k > len(idxs):
                    continue
                phrase = idxs[p:p + k]
                if all(_same(ms[phrase[0]], ms[x]) for x in phrase):
                    continue  # one bar repeated: simile marks read better
                if any(ms[x].uncertain for x in phrase):
                    continue
                # Every pass replays the phrase's marks. A tempo, feel or section mark
                # after its first bar would be re-applied on each pass although the
                # music (the IR) changes only once, so such a phrase is written out.
                if any(ms[x].tempo is not None or ms[x].tempo_text or ms[x].section for x in phrase[1:]):
                    continue
                r = 1
                while p + (r + 1) * k <= len(idxs):
                    copy = idxs[p + r * k:p + (r + 1) * k]
                    if all(_same(ms[a], ms[b]) and _clean_copy(ms[b]) for a, b in zip(phrase, copy)):
                        r += 1
                    else:
                        break
                if r >= 2 and (found is None or k * (r - 1) > found[0] * (found[1] - 1)):
                    found = (k, r)
            if found:
                k, r = found
                units.append(("volta", idxs[p:p + k], r, _units(score, idxs[p:p + k], "percent")))
                p += k * r
                continue
        if mode in ("auto", "percent"):
            rest = _rest_run(ms, idxs, p)
            if rest >= 2:  # tacet bars: one multi-bar rest, not a bar rest and simile marks
                units.append(("rest", idxs[p], rest))
                p += rest
                continue
            run = 1
            while (p + run < len(idxs) and _same(ms[idxs[p]], ms[idxs[p + run]])
                   and _clean_copy(ms[idxs[p + run]]) and not ms[idxs[p]].uncertain):
                run += 1
            if run >= 2:
                units.append(("percent", idxs[p], run))
                p += run
                continue
        units.append(("written", idxs[p]))
        p += 1
    return units


PERCENT_WEIGHT = 0.75
SHORT_LINE = 0.4  # a line filled below this fraction may be continued by the next section
OVERFULL = 1.25  # a short section may join the end of a previous line up to this fraction


@dataclass
class _Atom:
    index: int
    percent: bool
    weight: float  # as written (percent atoms use PERCENT_WEIGHT unless they start a line)
    written_weight: float
    boundary: str = ""  # "section" | "volta" | "after_volta" before this atom
    volta_start: bool = False
    volta_end: bool = False
    volta_times: int = 0
    rest_run: int = 0
    in_rest: bool = False  # inside a multi-bar rest: no width, never starts a line
    counted: bool = True  # a bar the reader counts on the line (not a pickup, not inside a rest)


def _atoms(score: Score, repeats: str, weights: list[float]) -> list[_Atom]:
    atoms: list[_Atom] = []

    def add_unit(unit: tuple, boundary: str) -> None:
        if unit[0] == "written":
            atoms.append(_Atom(unit[1], False, weights[unit[1]], weights[unit[1]], boundary))
        elif unit[0] == "rest":
            start, run = unit[1], unit[2]
            atoms.append(_Atom(start, False, weights[start], weights[start], boundary, rest_run=run))
            for k in range(1, run):
                atoms.append(_Atom(start + k, False, 0.0, 0.0, in_rest=True))
        else:  # percent run
            start, run = unit[1], unit[2]
            atoms.append(_Atom(start, False, weights[start], weights[start], boundary))
            for k in range(1, run):
                atoms.append(_Atom(start + k, True, PERCENT_WEIGHT, weights[start + k]))

    pending = "section"
    for sec in _sections(score):
        pending = "section"
        for unit in _units(score, sec, repeats):
            if unit[0] == "volta":
                _, phrase, times, inner = unit
                first = len(atoms)
                for j, iu in enumerate(inner):
                    add_unit(iu, pending if j == 0 and pending == "section" else ("volta" if j == 0 else ""))
                atoms[first].volta_start = True
                atoms[first].volta_times = times
                atoms[-1].volta_end = True
                atoms[-1].volta_times = times
                pending = "after_volta"
            else:
                add_unit(unit, pending)
                pending = ""
    return atoms


def _line_weight(line: list[_Atom]) -> float:
    if not line:
        return 0.0
    first = line[0].written_weight if line[0].percent else line[0].weight
    return first + sum(a.weight for a in line[1:])


def _bar_count(line: list[_Atom]) -> int:
    return sum(a.counted for a in line)


def _balance(atoms: list[_Atom], capacity: float, first_room: float,
             max_bars: int, first_bars: int) -> list[int]:
    """Break points (indices where a new line starts) minimizing squared slack.

    `first_room` is the space left on the line this paragraph starts on
    (less than capacity when a short previous line is continued), and `first_bars`
    the number of bars that line can still take. Light bars (2/4, 3/4, sparse 6/8)
    weigh less than a 4/4 bar, but a line never holds more than `max_bars` of them.
    """
    n = len(atoms)
    INF = float("inf")
    best = [INF] * (n + 1)
    prev = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        if j < n and atoms[j].in_rest:
            continue  # a line can't end inside a multi-bar rest
        count = 0
        for i in range(j - 1, -1, -1):
            count += atoms[i].counted
            if atoms[i].in_rest:
                continue
            room = first_room if i == 0 else capacity
            w = _line_weight(atoms[i:j])
            if (w > room + 1e-9 or count > (first_bars if i == 0 else max_bars)) and j - i > 1:
                break
            slack = max(0.0, room - w)
            # Breaking before a simile mark rewrites it as a full bar: small penalty.
            penalty = 0.5 if (i > 0 and atoms[i].percent) else 0.0
            cost = best[i] + slack * slack + penalty
            if cost < best[j]:
                best[j] = cost
                prev[j] = i
    breaks = []
    j = n
    while j > 0:
        breaks.append(prev[j])
        j = prev[j]
    return sorted(set(breaks))


def plan_layout(score: Score, repeats: str = "auto", bars_per_line: float = 4.0) -> LayoutPlan:
    if repeats not in REPEAT_MODES:
        raise ValueError(f"repeats must be one of {REPEAT_MODES}")
    weights = [_weight(m) for m in score.measures]
    capacity = bars_per_line
    max_bars = max(1, int(bars_per_line + 1e-9))
    atoms = _atoms(score, repeats, weights)
    for a in atoms:
        a.counted = not a.in_rest and not score.measures[a.index].is_pickup

    # Paragraphs: runs of atoms between hard boundaries.
    paragraphs: list[list[_Atom]] = []
    for a in atoms:
        if not paragraphs or a.boundary:
            paragraphs.append([])
        paragraphs[-1].append(a)

    line_starts: set[int] = set()  # atom positions (global) that start a line
    pos = 0
    carry = 0.0  # weight on the current (last) line
    last_line: list[_Atom] = []  # atoms on the current (last) line
    after_repeat = False
    for pi, para in enumerate(paragraphs):
        boundary = para[0].boundary
        room = capacity - carry
        can_share = (pos > 0 and boundary in ("section", "volta") and carry < SHORT_LINE * capacity)
        append = False
        if boundary == "section" and pos > 0:
            # Each section starts a new system, except (a) after a lone pickup, (b) when the
            # whole short section fits on the rest of a short line, or (c) a short section
            # that would otherwise sit alone on a stretched system joins the end of the
            # previous line when that line has room for it.
            whole = (pi + 1 == len(paragraphs) or paragraphs[pi + 1][0].boundary == "section")
            weight = _line_weight(para)
            short = whole and not para[-1].volta_end and weight < SHORT_LINE * capacity
            pickup_only = all(score.measures[a.index].is_pickup for a in last_line)
            fits = (whole and not para[-1].volta_end and weight <= room + 1e-9
                    and _bar_count(last_line) + _bar_count(para) <= max_bars)
            nxt = paragraphs[pi + 1] if pi + 1 < len(paragraphs) else None
            next_joins = (nxt is not None and nxt[0].boundary == "section"
                          and (pi + 2 == len(paragraphs) or paragraphs[pi + 2][0].boundary == "section")
                          and not nxt[-1].volta_end and weight + _line_weight(nxt) <= capacity + 1e-9
                          and _bar_count(para) + _bar_count(nxt) <= max_bars)
            # ...at most one bar more than a full line.
            append = (short and not next_joins and not after_repeat
                      and carry + weight <= OVERFULL * capacity + 1e-9
                      and _bar_count(last_line) + _bar_count(para) <= max_bars + 1)
            can_share = (can_share and (pickup_only or fits)) or append
            if append:
                room = OVERFULL * capacity - carry
        bar_room = (max_bars + 1 if append else max_bars) - _bar_count(last_line)
        if can_share:
            breaks = _balance(para, capacity, room, max_bars, bar_room)
            breaks = [b for b in breaks if b > 0]
        else:
            breaks = _balance(para, capacity, capacity, max_bars, max_bars)
        for b in breaks:
            line_starts.add(pos + b)
        if pos == 0 or not can_share:
            line_starts.add(pos)
        # Weight on the last line of this paragraph.
        last_start = max(b for b in [0] + breaks)
        tail = para[last_start:]
        carry = _line_weight(tail) + (carry if (can_share and last_start == 0) else 0.0)
        last_line = (last_line if (can_share and last_start == 0) else []) + tail
        after_repeat = para[-1].volta_end
        if after_repeat:
            carry = capacity  # always start a new line after a repeated phrase
        pos += len(para)

    bars: list[PrintedBar] = []
    for k, a in enumerate(atoms):
        pb = PrintedBar(a.index, percent=a.percent and k not in line_starts,
                        line_break=k in line_starts, volta_start=a.volta_start,
                        volta_end=a.volta_end, volta_times=a.volta_times,
                        rest_run=a.rest_run, in_rest=a.in_rest)
        if a.in_rest and pb.line_break:
            raise AssertionError("line break inside a multi-bar rest")
        bars.append(pb)
    # Simile runs: a written bar followed by percent bars on the same line.
    for k, pb in enumerate(bars):
        if pb.percent:
            continue
        run = 1
        while k + run < len(bars) and bars[k + run].percent:
            run += 1
        if run > 1:
            pb.percent_run = run
    # A simile run may not cross a volta boundary (the plan never builds one, but check).
    for k, pb in enumerate(bars):
        if pb.percent and pb.volta_start:
            raise AssertionError("simile mark at the start of a repeat")

    plan = LayoutPlan(bars, bars_per_line)
    _number(plan, score)
    expanded = plan.expand()
    if expanded != list(range(len(score.measures))):
        raise AssertionError(f"layout plan does not reproduce the score: {expanded}")
    return plan


def _number(plan: LayoutPlan, score: Score) -> None:
    """Printed bar numbers (LilyPond numbers printed bars; a volta phrase is printed once)."""
    number = 0 if score.measures and score.measures[0].is_pickup else 1
    i = 0
    bars = plan.bars
    while i < len(bars):
        pb = bars[i]
        plan.printed_numbers[pb.index] = number
        if pb.volta_start:
            j = i
            while not bars[j].volta_end:
                j += 1
            span = j - i + 1
            for k in range(i, j + 1):
                plan.printed_numbers[bars[k].index] = number + (k - i)
                for t in range(1, bars[i].volta_times):
                    plan.printed_numbers[bars[k].index + t * span] = number + (k - i)
            number += span
            i = j + 1
            continue
        number += 1
        i += 1


def same_meter(a: Measure, b: Measure) -> bool:
    return str(a.time_sig) == str(b.time_sig) and a.time_sig.groups() == b.time_sig.groups()


def volta_restates_meter(score: Score, plan: LayoutPlan, i: int) -> bool:
    """A repeat whose phrase ends in another meter restates the meter at its start,
    so the second pass doesn't inherit the meter of the phrase's last bar."""
    bars = plan.bars
    for j in range(i, len(bars)):
        if bars[j].volta_end:
            return not same_meter(score.measures[bars[i].index], score.measures[bars[j].index])
    return False
