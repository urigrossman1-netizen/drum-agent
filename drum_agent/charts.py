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
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(" ", "")
    if "=" not in text:
        return float(text)
    unit, bpm = text.split("=", 1)
    dotted = unit.endswith(".")
    base = Fraction(1, int(unit.rstrip(".")))
    if dotted:
        base *= Fraction(3, 2)
    return float(bpm) * float(base / Fraction(1, 4))


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


def _hits_from_pattern(pattern: dict[str, str], ts: TimeSig, length: Fraction | None, kit: Kit) -> list[Hit]:
    hits: list[Hit] = []
    for name, line in pattern.items():
        inst = kit.resolve(name)
        for pos, ch, roll in parse_pattern_line(str(line), ts, length):
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
    return hits


_BAR_KEYS = {"pattern", "time", "beat_groups", "tempo", "tempo_text", "length", "uncertain", "notes"}


def compile_spec(spec: dict[str, Any], kit: Kit = DEFAULT_KIT) -> Score:
    patterns: dict[str, dict[str, str]] = spec.get("patterns", {}) or {}
    for pname, pat in patterns.items():
        if not isinstance(pat, dict):
            raise ChartSpecError(f"pattern {pname!r} must map instruments to strings")
    ts = TimeSig.parse(str(spec.get("time", "4/4")), spec.get("beat_groups"))
    tempo = parse_tempo(spec.get("tempo", 120))
    measures: list[Measure] = []
    pending_tempo: float | None = tempo
    pending_text: str | None = spec.get("tempo_text") or ("Swing" if spec.get("swing") else None)
    pickup = spec.get("pickup")

    sections = spec.get("sections")
    if not sections:
        raise ChartSpecError("chart spec needs a 'sections' list")
    for sec in sections:
        label = sec.get("label")
        if "time" in sec:
            ts = TimeSig.parse(str(sec["time"]), sec.get("beat_groups"))
        if "tempo" in sec:
            pending_tempo = parse_tempo(sec["tempo"])
        if "tempo_text" in sec:
            pending_text = sec["tempo_text"]
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
                    pending_text = extra["tempo_text"]
            else:
                raise ChartSpecError(f"bar entries must be pattern names or mappings, got {entry!r}")
            if not measures and pickup is not None and length is None:
                length = Fraction(str(pickup))
            m = Measure(time_sig=bar_ts, length=length,
                        hits=_hits_from_pattern(pat, bar_ts, length, kit))
            if bi == 0 and label:
                m.section = label
            if pending_tempo is not None:
                m.tempo = pending_tempo
                pending_tempo = None
            if pending_text is not None:
                m.tempo_text = pending_text
                if m.tempo is None:
                    m.tempo = _current_tempo(measures) or tempo
                pending_text = None
            m.uncertain = bool(extra.get("uncertain", False))
            m.notes = list(extra.get("notes", []))
            measures.append(m)

    chart_type = spec.get("chart_type", "pattern_study")
    if chart_type not in CHART_TYPES:
        raise ChartSpecError(f"chart_type must be one of {sorted(CHART_TYPES)}")
    score = Score(
        measures=measures,
        title=spec.get("title", "Untitled"),
        artist=spec.get("artist"),
        transcriber=spec.get("transcriber"),
        chart_type=chart_type,
        status=spec.get("status", "verified"),
        rights=spec.get("rights"),
        source=spec.get("source"),
        swing=bool(spec.get("swing", False)),
        feel_note=spec.get("feel_note"),
        copyright=spec.get("copyright"),
    )
    score.validate(kit)
    return score


def _current_tempo(measures: list[Measure]) -> float | None:
    for m in reversed(measures):
        if m.tempo is not None:
            return m.tempo
    return None


def load_spec(path: str | Path, kit: Kit = DEFAULT_KIT) -> Score:
    path = Path(path)
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ChartSpecError("PyYAML is required for .yaml chart specs (pip install pyyaml)") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ChartSpecError(f"{path}: top level must be a mapping")
    return compile_spec(data, kit)


def load_any(path: str | Path, kit: Kit = DEFAULT_KIT) -> Score:
    """Load an IR score (.json with 'measures') or a chart spec (.yaml/.json with 'sections')."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        if "measures" in data:
            score = Score.from_dict(data)
            score.validate(kit)
            return score
        return compile_spec(data, kit)
    return load_spec(path, kit)
