"""Targeted corrections to an IR score (the human-in-the-loop step).

Every edit names exact bars and positions, so a correction can't silently
change anything else. Bar numbers are 1-based *performance* bars (the order
in score.json, not printed numbers after repeat compression); a pickup bar
is bar 1.

Hit references use "BAR:POS:INST", e.g. "12:3/8:kick" (POS in whole notes from
the start of the bar: 0 = beat 1, 1/4 = beat 2, 3/8 = "and" of 2 in 4/4).
"""

from __future__ import annotations

from fractions import Fraction

from .kit import DEFAULT_KIT, Kit
from .model import Hit, Score, ScoreError, frac


class EditError(ScoreError):
    pass


FLAGS = ("accent", "ghost", "flam", "drag", "choke")


def parse_bars(spec: str | None, n: int) -> range:
    """"9-16", "12", or None (all bars) -> 0-based range."""
    if not spec:
        return range(n)
    if "-" in spec:
        a, b = spec.split("-", 1)
        lo, hi = int(a), int(b)
    else:
        lo = hi = int(spec)
    if not (1 <= lo <= hi <= n):
        raise EditError(f"bar range {spec!r} is outside 1-{n}")
    return range(lo - 1, hi)


def _ref(spec: str, score: Score, kit: Kit) -> tuple[int, Fraction, str, list[str]]:
    parts = spec.split(":")
    if len(parts) < 3:
        raise EditError(f"hit reference {spec!r} must be BAR:POS:INST[:flag,...]")
    try:
        bar = int(parts[0]) - 1
    except ValueError:
        raise EditError(f"hit reference {spec!r}: BAR must be a number") from None
    if not 0 <= bar < len(score.measures):
        raise EditError(f"bar {parts[0]} does not exist (1-{len(score.measures)})")
    pos = frac(parts[1])
    inst = kit.resolve(parts[2])
    flags = [f.strip() for f in parts[3].split(",")] if len(parts) > 3 and parts[3] else []
    bad = [f for f in flags if f not in FLAGS and not f.startswith("roll=")]
    if bad:
        raise EditError(f"unknown flags {bad}; use {FLAGS} or roll=1/4")
    return bar, pos, inst, flags


def relabel(score: Score, mapping: str, bars: str | None = None, kit: Kit = DEFAULT_KIT) -> int:
    """"ride=hihat" in the given bars. Returns the number of hits changed.

    All collisions are checked first, so a failing relabel changes nothing.
    """
    if "=" not in mapping:
        raise EditError("relabel needs FROM=TO, e.g. ride=hihat")
    src, dst = (kit.resolve(x) for x in mapping.split("=", 1))
    targets = []
    for i in parse_bars(bars, len(score.measures)):
        m = score.measures[i]
        taken = {h.pos for h in m.hits if h.inst == dst}
        for h in m.hits:
            if h.inst == src:
                if h.pos in taken:
                    raise EditError(f"bar {i + 1}: {dst} already at {h.pos}; delete one first")
                targets.append(h)
    for h in targets:
        h.inst = dst
        h.edited = True
    return len(targets)


def delete(score: Score, spec: str, kit: Kit = DEFAULT_KIT) -> None:
    bar, pos, inst, _ = _ref(spec, score, kit)
    m = score.measures[bar]
    for h in m.hits:
        if h.pos == pos and h.inst == inst:
            m.hits.remove(h)
            return
    raise EditError(f"no {inst} at {pos} in bar {bar + 1}")


def add(score: Score, spec: str, kit: Kit = DEFAULT_KIT) -> None:
    bar, pos, inst, flags = _ref(spec, score, kit)
    m = score.measures[bar]
    if any(h.pos == pos and h.inst == inst for h in m.hits):
        raise EditError(f"bar {bar + 1} already has {inst} at {pos}")
    h = Hit(pos=pos, inst=inst)
    _apply_flags(h, flags)
    m.hits.append(h)


def set_flags(score: Score, spec: str, kit: Kit = DEFAULT_KIT) -> None:
    """"12:1/4:snare:accent" sets flags (and clears the others) on an existing hit."""
    bar, pos, inst, flags = _ref(spec, score, kit)
    for h in score.measures[bar].hits:
        if h.pos == pos and h.inst == inst:
            for f in FLAGS:
                setattr(h, f, False)
            h.roll = None
            _apply_flags(h, flags)
            return
    raise EditError(f"no {inst} at {pos} in bar {bar + 1}")


def _apply_flags(h: Hit, flags: list[str]) -> None:
    for f in flags:
        if f.startswith("roll="):
            h.roll = frac(f.split("=", 1)[1])
        else:
            setattr(h, f, True)
    h.confidence = 1.0  # a human put it here
    h.edited = True


# What a person changes when they edit a note (not its timing evidence or confidence).
MUSICAL_FIELDS = ("velocity", "accent", "ghost", "flam", "drag", "roll", "choke", "sticking")


def mark_edits(score: Score, before: Score) -> int:
    """Mark the notes a person added or changed (Hit.edited), comparing an edited score with
    the version it was made from, bar by bar. Unchanged notes keep their link to the
    detector's strokes (Hit.raw) even when the editor didn't carry it, and a note put on another
    instrument at the same position keeps the strokes of the note it replaced. Notes already
    marked stay marked. Returns how many notes were newly marked."""
    marked = 0
    for i, m in enumerate(score.measures):
        old = {h.key(): h for h in before.measures[i].hits} if i < len(before.measures) else {}
        keys = {h.key() for h in m.hits}
        replaced: dict = {}
        for k, h in old.items():
            if k not in keys:
                replaced.setdefault(k[0], []).append(h)
        for h in sorted(m.hits, key=lambda h: (h.pos, h.inst)):
            prev = old.get(h.key())
            if prev is not None:
                if not h.raw and prev.raw:
                    h.raw = prev.raw
                changed = any(getattr(h, f) != getattr(prev, f) for f in MUSICAL_FIELDS)
                if (changed or prev.edited) and not h.edited:
                    h.edited = True
                    marked += changed
            else:
                if not h.edited:
                    h.edited = True
                    marked += 1
                gone = replaced.get(h.pos)
                if gone and not h.raw:
                    h.raw = gone.pop(0).raw
    return marked


def parse_sections(spec: str, n_bars: int) -> dict[int, str]:
    """"Intro:1,Verse 1:5,Chorus:13" -> {0: "Intro", 4: "Verse 1", 12: "Chorus"} (0-based bars)."""
    out: dict[int, str] = {}
    for part in spec.split(","):
        label, _, bar = part.rpartition(":")
        try:
            idx = int(bar) - 1
        except ValueError:
            idx = -1
        if not label.strip() or not 0 <= idx < n_bars:
            raise EditError(f"bad section entry {part!r}: use LABEL:BAR with BAR in 1-{n_bars}, "
                            f"e.g. \"Intro:1,Verse:5\"")
        out[idx] = label.strip()
    return out


def set_sections(score: Score, spec: str) -> None:
    """"Intro:1,Verse 1:5,Chorus:13" (label:first bar). Replaces all labels."""
    labels = parse_sections(spec, len(score.measures))  # validate everything first
    for i, m in enumerate(score.measures):
        m.section = labels.get(i)


def set_tempo(score: Score, spec: str) -> None:
    """"BAR:BPM" (quarter notes per minute), e.g. "1:96" or "29:100"."""
    bar, _, bpm = spec.partition(":")
    try:
        idx, value = int(bar) - 1, float(bpm)
    except ValueError:
        raise EditError(f"bad tempo {spec!r}: use BAR:BPM, e.g. 29:100") from None
    if not 0 <= idx < len(score.measures):
        raise EditError(f"bar {bar} does not exist")
    if not 20 <= value <= 400:
        raise EditError(f"tempo {value:g} is outside 20-400 quarter notes per minute")
    score.measures[idx].tempo = value


def mark_verified(score: Score, bars: str | None) -> int:
    """Clear review flags on bars a human has checked by ear."""
    count = 0
    for i in parse_bars(bars, len(score.measures)):
        m = score.measures[i]
        if m.uncertain:
            m.uncertain = False
            m.notes.append("verified by ear")
            count += 1
        for h in m.hits:
            h.confidence = max(h.confidence, 0.9)
    if not any(m.uncertain for m in score.measures) and bars is None:
        score.status = "verified"
    return count
