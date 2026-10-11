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


def _weight(m: Measure) -> float:
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
    if m.time_sig.bar_length > 1:  # long bars (5/4, 7/4, 12/8 ...)
        w *= float(m.time_sig.bar_length)
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
            found = None
            for k in (8, 4, 2):
                if p + 2 * k > len(idxs):
                    continue
                phrase = idxs[p:p + k]
                if all(_same(ms[phrase[0]], ms[x]) for x in phrase):
                    continue  # one bar repeated: simile marks read better
                if any(ms[x].uncertain for x in phrase):
                    continue
                r = 1
                while p + (r + 1) * k <= len(idxs):
                    copy = idxs[p + r * k:p + (r + 1) * k]
                    if all(_same(ms[a], ms[b]) and _clean_copy(ms[b]) for a, b in zip(phrase, copy)):
                        r += 1
                    else:
                        break
                if r >= 2:
                    found = (k, r)
                    break
            if found:
                k, r = found
                units.append(("volta", idxs[p:p + k], r, _units(score, idxs[p:p + k], "percent")))
                p += k * r
                continue
        if mode in ("auto", "percent"):
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


def plan_layout(score: Score, repeats: str = "auto", bars_per_line: float = 4.0) -> LayoutPlan:
    if repeats not in REPEAT_MODES:
        raise ValueError(f"repeats must be one of {REPEAT_MODES}")
    weights = [_weight(m) for m in score.measures]
    bars: list[PrintedBar] = []
    capacity = bars_per_line

    line_weight = 0.0

    def place(pb: PrintedBar, w: float, force_break: bool = False) -> None:
        nonlocal line_weight
        if force_break or (bars and line_weight + w > capacity + 1e-9):
            pb.line_break = True
            line_weight = 0.0
        if not bars:
            pb.line_break = True
        bars.append(pb)
        line_weight += w

    def place_percent_run(start_idx: int, run: int, first_break: bool) -> None:
        # Written bar followed by simile marks; a new line restarts with the written bar.
        nonlocal line_weight
        k = 0
        while k < run:
            pb = PrintedBar(start_idx + k)
            place(pb, weights[start_idx + k], force_break=first_break and k == 0)
            group = [pb]
            k += 1
            while k < run and line_weight + 0.75 <= capacity + 1e-9:
                q = PrintedBar(start_idx + k, percent=True)
                bars.append(q)
                line_weight += 0.75
                group.append(q)
                k += 1
            if len(group) > 1:
                pb.percent_run = len(group)

    for sec in _sections(score):
        first = True
        for unit in _units(score, sec, repeats):
            kind = unit[0]
            if kind == "written":
                place(PrintedBar(unit[1]), weights[unit[1]], force_break=first)
            elif kind == "percent":
                place_percent_run(unit[1], unit[2], first)
            else:  # volta
                _, phrase, times, inner = unit
                start = len(bars)
                force = first or line_weight > 0
                for j, iu in enumerate(inner):
                    if iu[0] == "written":
                        place(PrintedBar(iu[1]), weights[iu[1]], force_break=force and j == 0)
                    else:
                        place_percent_run(iu[1], iu[2], force and j == 0)
                bars[start].volta_start = True
                bars[start].volta_times = times
                bars[-1].volta_end = True
                bars[-1].volta_times = times
                line_weight = capacity  # the next unit starts a new line after a repeat
            first = False

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
