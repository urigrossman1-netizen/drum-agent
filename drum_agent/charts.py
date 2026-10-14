"""Chart spec: a compact YAML/JSON authoring format that compiles to the IR.

Used for hand-written performance charts, corrections and test fixtures. It
is an *input* format; the printed score is always engraved from the IR.

Example::

    title: Example
    tempo: 96
    time: 4/4
    patterns:
      groove:
        hh: "x-x-x-x-x-x-x-x-"
        sn: "----x-------x---"
        bd: "x-------x-x-----"
    sections:
      - label: Verse
        bars: ["groove*3", {hh: "x-x-x-x-x-x-x-x-", sn: "----x---xxxx|rrrr"}]

Pattern strings: characters divide the bar evenly, or, if the string contains
"|", each "|"-separated segment is one beat and its characters divide that beat
(so triplets and 16ths can share a bar). Symbols:

    - .   no stroke             x  stroke              X >  accent
    g     ghost note            o  open hi-hat (hh line only)
    h     half-open hi-hat      f  flam   F accented flam
    d     drag (ruff)           r  roll; extend it with ~ ("r~~~")
    c     cymbal choke
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from .kit import DEFAULT_KIT, Kit
from .model import CHART_TYPES, Hit, Measure, Score, ScoreError, TimeSig

_SYMBOLS = set("-.xX>goh fFdrc~")


class ChartSpecError(ScoreError):
    pass


def parse_tempo(value: Any) -> float:
    """Tempo as quarter notes per minute. Accepts 120, "120", "4=120", "4.=80", "2=60", "8=180"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace(" ", "")
    try:
        if "=" not in text:
            return float(text)
        unit, bpm = text.split("=", 1)
        dotted = unit.endswith(".")
        base = Fraction(1, int(unit.rstrip(".")))
        if dotted:
            base *= Fraction(3, 2)
        return float(bpm) * float(base / Fraction(1, 4))
    except (ValueError, ZeroDivisionError):
        raise ChartSpecError(f"tempo {value!r}: use quarter notes per minute (120) "
                             f"or a mark like '4.=80'") from None


# Slots per beat the engraver can spell (rhythm.py): simple beats take 8ths, 16ths,
# 32nds, triplets and sextuplets; dotted (compound) beats take 8ths, 16ths, duplets
# and quadruplets.
_SIMPLE_SLOTS = (1, 2, 3, 4, 6, 8, 12)
_COMPOUND_SLOTS = (1, 2, 3, 4, 6, 12)


def _beat_slots(blen: Fraction) -> tuple[int, ...]:
    return _COMPOUND_SLOTS if (blen / Fraction(3, 8)).denominator == 1 and blen.numerator % 3 == 0 else _SIMPLE_SLOTS


def _check_grid(text: str, slots: list[tuple[Fraction, Fraction, str]], ts: TimeSig, offset: Fraction,
                bar: Fraction) -> None:
    """Every beat must hold a whole, supported number of characters, so a
    miscounted line fails here with a clear message instead of as an odd tuplet."""
    beats = [(st - offset, ln) for st, ln in ts.beats() if st >= offset]
    for start, blen in beats:
        in_beat = [step for pos, step, _ in slots if start <= pos < start + blen]
        aligned = any(pos == start for pos, _, _ in slots)
        n = len(in_beat)
        if not aligned or n == 0 or sum(in_beat) != blen or n not in _beat_slots(blen):
            if "|" in text:
                k = beats.index((start, blen)) + 1
                raise ChartSpecError(f"beat {k} has {n} characters; a beat can hold "
                                     f"{', '.join(map(str, _beat_slots(blen)))}")
            good = [k for k in range(1, 97) if _fits_uniform(k, beats, bar)]
            raise ChartSpecError(
                f"{len(text)} characters don't divide this {ts} bar into a supported grid; use "
                f"{', '.join(map(str, good))} characters, or separate the beats with '|'")


def _fits_uniform(k: int, beats: list[tuple[Fraction, Fraction]], bar: Fraction) -> bool:
    step = bar / k
    return all((start / step).denominator == 1 and (blen / step).denominator == 1
               and int(blen / step) in _beat_slots(blen) for start, blen in beats)


def parse_pattern_line(text: str, ts: TimeSig, length: Fraction | None = None) -> list[tuple[Fraction, str, Fraction | None]]:
    """Parse one instrument line into (position, symbol, roll length) tuples."""
    s = re.sub(r"\s+", "", text)
    bar = length if length is not None else ts.bar_length
    offset = ts.bar_length - bar
    if "|" in s:
        parts = s.split("|")
        if parts and parts[-1] == "":
            parts = parts[:-1]
        beats = [(st - offset, ln) for st, ln in ts.beats() if st >= offset]
        if len(parts) != len(beats):
            raise ChartSpecError(f"pattern {text!r} has {len(parts)} beat segments but the bar has {len(beats)} beats")
        slots: list[tuple[Fraction, Fraction, str]] = []
        for (start, blen), part in zip(beats, parts):
            if not part:
                raise ChartSpecError(f"empty beat segment in {text!r}")
            step = blen / len(part)
            slots += [(start + i * step, step, ch) for i, ch in enumerate(part)]
    else:
        if not s:
            return []
        step = bar / len(s)
        slots = [(i * step, step, ch) for i, ch in enumerate(s)]
    _check_grid(s, slots, ts, offset, bar)
    out: list[tuple[Fraction, str, Fraction | None]] = []
    i = 0
    while i < len(slots):
        pos, step, ch = slots[i]
        if ch not in _SYMBOLS:
            raise ChartSpecError(f"unknown symbol {ch!r} in pattern {text!r}")
        if ch == "~":
            raise ChartSpecError(f"'~' must follow a roll 'r' in {text!r}")
        if ch in "-.":
            i += 1
            continue
        roll = None
        if ch == "r":
            j, total = i + 1, step
            while j < len(slots) and slots[j][2] == "~":
                total += slots[j][1]
                j += 1
            roll = total
            out.append((pos, ch, roll))
            i = j
            continue
        out.append((pos, ch, None))
        i += 1
    return out


STICKING_KEYS = ("sticking", "stick")


def _apply_sticking(line: str, hits: list[Hit], ts: TimeSig, length: Fraction | None, kit: Kit) -> None:
    """A sticking line ("R-L-R-L-..." on the same grid as the instrument lines) names the hand
    for the stroke at each position: a drum stroke if there is one, else a cymbal."""
    compact = re.sub(r"\s+", "", line)
    letters = [c.upper() for c in compact if c not in "-.|"]
    bad = sorted({c for c in letters if c not in "RLB"})
    if bad:
        raise ChartSpecError(f"sticking line {line!r}: use R, L or B (both hands) and - for none, not {bad}")
    grid = "".join("x" if c.upper() in "RLB" else c for c in compact)
    for (pos, _, _), letter in zip(parse_pattern_line(grid, ts, length), letters):
        at = [h for h in hits if h.pos == pos and not kit.is_foot(h.inst)]
        if not at:
            raise ChartSpecError(f"sticking line {line!r}: {letter} at {pos} has no hand stroke under it")
        at.sort(key=lambda h: (kit[h.inst].family != "drum", -kit[h.inst].position))
        at[0].sticking = letter


def _hits_from_pattern(pattern: dict[str, str], ts: TimeSig, length: Fraction | None, kit: Kit) -> list[Hit]:
    hits: list[Hit] = []
    sticking = None
    for name, line in pattern.items():
        if str(name).lower() in STICKING_KEYS:
            sticking = str(line)
            continue
        inst = kit.resolve(name)
        try:
            parsed = parse_pattern_line(str(line), ts, length)
        except ChartSpecError as exc:
            raise ChartSpecError(f"{name} line {str(line)!r}: {exc}") from None
        for pos, ch, roll in parsed:
            this = inst
            h = Hit(pos=pos, inst=inst)
            if ch in "X>":
                h.accent = True
            elif ch == "g":
                h.ghost = True
            elif ch in "oh":
                if inst != "hihat":
                    raise ChartSpecError(f"'{ch}' (open/half-open) is only valid on the hi-hat line, not {name}")
                this = "hihat_open" if ch == "o" else "hihat_half"
            elif ch in "fF":
                h.flam = True
                h.accent = ch == "F"
            elif ch == "d":
                h.drag = True
            elif ch == "r":
                h.roll = roll
            elif ch == "c":
                h.choke = True
            h.inst = this
            hits.append(h)
    if sticking is not None:
        _apply_sticking(sticking, hits, ts, length, kit)
    return hits


_BAR_KEYS = {"pattern", "time", "beat_groups", "tempo", "tempo_text", "length", "uncertain", "notes", "cue"}


def compile_spec(spec: dict[str, Any], kit: Kit = DEFAULT_KIT) -> Score:
    if not isinstance(spec, dict):
        raise ChartSpecError("a chart spec is a mapping with 'title', 'tempo', 'sections', ...")
    patterns: dict[str, dict[str, str]] = spec.get("patterns", {}) or {}
    if not isinstance(patterns, dict):
        raise ChartSpecError("'patterns' must map pattern names to instrument lines")
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections or not all(isinstance(x, dict) for x in sections):
        raise ChartSpecError("chart spec needs a 'sections' list; each section is a mapping with 'bars'")
    for k, sec in enumerate(sections, 1):
        if not isinstance(sec.get("bars", []), list):
            raise ChartSpecError(f"section {k} ({sec.get('label')!r}): 'bars' must be a list")
        rep = sec.get("repeat", 1)
        if isinstance(rep, bool) or not isinstance(rep, int) or rep < 1:
            raise ChartSpecError(f"section {k} ({sec.get('label')!r}): 'repeat' must be a whole number from 1")
    for pname, pat in patterns.items():
        if not isinstance(pat, dict):
            raise ChartSpecError(f"pattern {pname!r} must map instruments to strings")
        misplaced = sorted(set(pat) & _BAR_KEYS)
        if misplaced:
            raise ChartSpecError(
                f"pattern {pname!r} contains {misplaced}; patterns hold instrument lines only. "
                f"Set these on the section or on the bar entry, e.g. {{pattern: {pname}, {misplaced[0]}: ...}}")
    ts = TimeSig.parse(str(spec.get("time", "4/4")), spec.get("beat_groups"))
    tempo = parse_tempo(spec.get("tempo", 120))
    measures: list[Measure] = []
    pending_tempo: float | None = tempo
    pending_text: str | None = _text(spec.get("tempo_text"), "tempo_text") or ("Swing" if spec.get("swing") else None)
    pickup = spec.get("pickup")

    for sec in sections:
        label = _text(sec.get("label"), "section label")
        if "time" in sec:
            ts = TimeSig.parse(str(sec["time"]), sec.get("beat_groups"))
        if "tempo" in sec:
            pending_tempo = parse_tempo(sec["tempo"])
        if "tempo_text" in sec:
            pending_text = _text(sec["tempo_text"], f"section {label!r} tempo_text")
        repeat = int(sec.get("repeat", 1))
        bar_entries: list[Any] = []
        for entry in sec.get("bars", []):
            if isinstance(entry, str) and "*" in entry:
                name, count = entry.rsplit("*", 1)
                bar_entries += [name.strip()] * int(count)
            else:
                bar_entries.append(entry)
        bar_entries = bar_entries * repeat
        if not bar_entries:
            raise ChartSpecError(f"section {label!r} has no bars")
        for bi, entry in enumerate(bar_entries):
            bar_ts = ts
            length = None
            extra: dict[str, Any] = {}
            if isinstance(entry, str):
                if entry not in patterns:
                    raise ChartSpecError(f"unknown pattern {entry!r} in section {label!r}")
                pat = patterns[entry]
            elif isinstance(entry, dict):
                extra = {k: v for k, v in entry.items() if k in _BAR_KEYS}
                if "pattern" in entry:
                    if entry["pattern"] not in patterns:
                        raise ChartSpecError(f"unknown pattern {entry['pattern']!r}")
                    pat = patterns[entry["pattern"]]
                else:
                    pat = {k: v for k, v in entry.items() if k not in _BAR_KEYS}
                if "time" in extra:
                    bar_ts = TimeSig.parse(str(extra["time"]), extra.get("beat_groups"))
                    ts = bar_ts  # a time change persists, as on paper
                if "length" in extra:
                    length = Fraction(str(extra["length"]))
                if "tempo" in extra:
                    pending_tempo = parse_tempo(extra["tempo"])
                if "tempo_text" in extra:
                    pending_text = _text(extra["tempo_text"], f"section {label!r} tempo_text")
            else:
                raise ChartSpecError(f"bar entries must be pattern names or mappings, got {entry!r}")
            if not measures and pickup is not None and length is None:
                length = Fraction(str(pickup))
            try:
                bar_hits = _hits_from_pattern(pat, bar_ts, length, kit)
            except ChartSpecError as exc:
                what = f"pattern {entry!r}" if isinstance(entry, str) else (
                    f"pattern {entry['pattern']!r}" if "pattern" in entry else "inline bar")
                raise ChartSpecError(f"section {label!r}, bar {bi + 1} ({what}, {bar_ts}): {exc}") from None
            m = Measure(time_sig=bar_ts, length=length, hits=bar_hits)
            if bi == 0 and label:
                m.section = label
            cue = extra.get("cue", sec.get("cue") if bi == 0 else None)
            if cue is not None:
                m.cue = _text(cue, f"section {label!r} cue")
            if pending_tempo is not None:
                m.tempo = pending_tempo
                pending_tempo = None
            if pending_text is not None:
                m.tempo_text = pending_text
                if m.tempo is None:
                    m.tempo = _current_tempo(measures) or tempo
                pending_text = None
            m.uncertain = bool(extra.get("uncertain", False))
            m.notes = [_text(n, "bar notes") for n in extra.get("notes", [])]
            measures.append(m)

    chart_type = spec.get("chart_type", "pattern_study")
    if chart_type not in CHART_TYPES:
        raise ChartSpecError(f"chart_type must be one of {sorted(CHART_TYPES)}")
    score = Score(
        measures=measures,
        title=_text(spec.get("title", "Untitled"), "title"),
        artist=_text(spec.get("artist"), "artist"),
        transcriber=_text(spec.get("transcriber"), "transcriber"),
        chart_type=chart_type,
        status=spec.get("status", "entered"),
        rights=spec.get("rights"),
        source=_text(spec.get("source"), "source"),
        swing=bool(spec.get("swing", False)),
        feel_note=_text(spec.get("feel_note"), "feel_note"),
        copyright=_text(spec.get("copyright"), "copyright"),
    )
    score.validate(kit)
    return score


def _current_tempo(measures: list[Measure]) -> float | None:
    for m in reversed(measures):
        if m.tempo is not None:
            return m.tempo
    return None


# Fields printed as text. YAML would read `title: 1999`, `artist: Yes` or `label: 2`
# as a number or a boolean; these keep exactly what was written.
TEXT_KEYS = frozenset({"title", "artist", "transcriber", "label", "tempo_text", "source",
                       "feel_note", "copyright", "cue", "sticking", "stick"})


def _yaml_load(text: str) -> Any:
    import yaml

    class TextLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            mapping = super().construct_mapping(node, deep=deep)
            for key_node, value_node in node.value:
                if (isinstance(key_node, yaml.ScalarNode) and key_node.value in TEXT_KEYS
                        and isinstance(value_node, yaml.ScalarNode)
                        and value_node.tag != "tag:yaml.org,2002:null"):
                    mapping[key_node.value] = value_node.value
            return mapping

    return yaml.load(text, Loader=TextLoader)  # noqa: S506 - a SafeLoader subclass


def _text(value: Any, what: str) -> str | None:
    """A text field from a spec: numbers become their text (JSON has no unquoted text)."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ChartSpecError(f"{what} must be text, got {value!r}; put it in quotes")


def load_spec(path: str | Path, kit: Kit = DEFAULT_KIT) -> Score:
    path = Path(path)
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ChartSpecError("PyYAML is required for .yaml chart specs (pip install pyyaml)") from exc
        try:
            data = _yaml_load(text)
        except yaml.YAMLError as exc:
            raise ChartSpecError(f"{path}: not valid YAML: {exc}") from None
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ChartSpecError(f"{path}: top level must be a mapping")
    return compile_spec(data, kit)


def load_any(path: str | Path, kit: Kit = DEFAULT_KIT) -> Score:
    """Load an IR score (.json with 'measures') or a chart spec (.yaml/.json with 'sections')."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text())
        except ValueError as exc:
            raise ChartSpecError(f"{path}: not valid JSON: {exc}") from None
        if not isinstance(data, dict):
            raise ChartSpecError(f"{path}: top level must be a mapping")
        if "measures" in data:
            score = Score.from_dict(data)
            score.validate(kit)
            return score
        return compile_spec(data, kit)
    return load_spec(path, kit)
