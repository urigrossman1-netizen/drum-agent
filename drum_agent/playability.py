"""Playability: strokes one drummer with two hands and two feet can't play.

An automatic transcription that asks for three hands at once, or an open
hi-hat stroke at the instant the foot closes it, has a detection error in
that bar. For audio the bars are flagged for a listen; for every chart the
report lists them.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .kit import DEFAULT_KIT, Kit
from .model import Score

LEFT_FOOT = ("hihat_pedal", "hihat_splash", "kick2")  # kick is the right foot
FASTEST_SINGLE_HAND_S = 0.030  # ~33 strokes per second: faster than one hand on one drum, outside rolls


@dataclass(frozen=True)
class Issue:
    bar: int  # 0-based index into score.measures
    pos: Fraction
    kind: str  # "hands", "feet", "hihat", "roll", "speed"
    message: str


def _hands_needed(insts: dict[str, object], kit: Kit) -> int:
    n = 0
    for inst, h in insts.items():
        if inst in kit and not kit.is_foot(inst):
            n += 2 if (getattr(h, "flam", False) or getattr(h, "drag", False)) else 1
    return n


def check(score: Score, kit: Kit = DEFAULT_KIT) -> list[Issue]:
    issues: list[Issue] = []
    starts = score.measure_start_seconds()
    last_stroke: dict[str, float] = {}
    for i, m in enumerate(score.measures):
        sec_per_whole = 4 * 60.0 / score.tempo_at(i)
        at: dict[Fraction, dict[str, object]] = {}
        for h in m.hits:
            at.setdefault(h.pos, {})[h.inst] = h
        rolls = [(h.pos, h.pos + h.roll, h.inst) for h in m.hits if h.roll is not None]
        for pos in sorted(at):
            insts = at[pos]
            hands = _hands_needed(insts, kit)
            if hands > 2:
                names = ", ".join(sorted(insts[x].inst + (" (flam)" if insts[x].flam else "")
                                         for x in insts if x in kit and not kit.is_foot(x)))
                issues.append(Issue(i, pos, "hands", f"{hands} hands needed at once ({names})"))
            left = [x for x in insts if x in LEFT_FOOT]
            if len(left) > 1:
                issues.append(Issue(i, pos, "feet", f"left foot plays {' and '.join(sorted(left))} at once"))
            if "hihat_pedal" in insts and ({"hihat_open", "hihat_half"} & set(insts)):
                issues.append(Issue(i, pos, "hihat", "open hi-hat struck as the foot closes it"))
            for r0, r1, rinst in rolls:
                if r0 < pos < r1:
                    others = [x for x in insts if x != rinst and x in kit and not kit.is_foot(x)]
                    if others:
                        issues.append(Issue(i, pos, "roll", f"{', '.join(sorted(others))} during the "
                                                            f"{rinst} roll (both hands are rolling)"))
            t = starts[i] + float(pos) * sec_per_whole
            for inst, h in insts.items():
                if inst not in kit or kit.is_foot(inst) or getattr(h, "roll", None) is not None:
                    continue
                prev = last_stroke.get(inst)
                if prev is not None and 0 < t - prev < FASTEST_SINGLE_HAND_S and not h.flam and not h.drag:
                    issues.append(Issue(i, pos, "speed", f"{inst} strokes {1000 * (t - prev):.0f} ms apart "
                                                         f"(faster than single strokes; a roll?)"))
                last_stroke[inst] = t
    return issues


def flag_bars(score: Score, issues: list[Issue]) -> int:
    """Mark bars with playability issues for review; returns how many bars were flagged."""
    flagged = set()
    for iss in issues:
        m = score.measures[iss.bar]
        note = f"not playable as written: {iss.message}"
        if note not in m.notes:
            m.notes.append(note)
        m.uncertain = True
        flagged.add(iss.bar)
    return len(flagged)


def describe(score: Score, issues: list[Issue], limit: int = 30) -> list[str]:
    out = []
    for iss in issues[:limit]:
        beat = _beat_text(score, iss.bar, iss.pos)
        out.append(f"score bar {iss.bar + 1}, {beat}: {iss.message}")
    if len(issues) > limit:
        out.append(f"... and {len(issues) - limit} more")
    return out


def _beat_text(score: Score, bar: int, pos: Fraction) -> str:
    ts = score.measures[bar].time_sig
    for k, (start, length) in enumerate(ts.beats()):
        if start <= pos < start + length:
            off = pos - start
            return f"beat {k + 1}" + ("" if off == 0 else f" + {off}")
    return f"position {pos}"
