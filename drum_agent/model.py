"""Intermediate representation (IR): the single source of truth for a chart.

Everything downstream (LilyPond, MusicXML, MIDI, reports, tests) reads a
`Score`. Musical positions are exact `Fraction`s measured in whole notes from
the start of the bar (a quarter note is 1/4). Performed timing from audio is
kept alongside (`Hit.time`, `Hit.offset_ms`) without disturbing notation.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator

from .kit import DEFAULT_KIT, Kit

SCHEMA_VERSION = 1

CHART_TYPES = {
    "full_transcription": "Full Drum Transcription",
    "performance_chart": "Performance Chart: grooves and roadmap, not a note-for-note transcription",
    "pattern_study": "Pattern Study",
}

STATUSES = {  # status -> text printed under the title (None: nothing printed)
    "verified": None,  # a human checked it against the recording
    "entered": None,  # written as a chart spec (by hand or from a description); nothing detected
    "unverified_auto": "Automatic transcription, unverified",
    "unverified_import": "Imported from MIDI, unverified",
    "draft": "Draft",
}

RIGHTS = {
    "own": "Recording owned by the user",
    "permission": "Transcribed with the rights holder's permission",
    "licensed": "Licensed material",
    "public_domain": "Public-domain material",
    "original": "Original composition/pattern",
}


STICKING = re.compile(r"[RLB]{1,3}")


class ScoreError(ValueError):
    """Raised for an IR that is structurally invalid."""


def frac(value: Any) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, str):
        return Fraction(value.strip())
    if isinstance(value, float):
        raise ScoreError(f"positions must be exact; got float {value!r}. Use a string like '3/16'.")
    raise ScoreError(f"cannot convert {value!r} to a fraction")


def frac_str(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


@dataclass(frozen=True)
class TimeSig:
    num: int
    den: int
    beat_groups: tuple[int, ...] | None = None  # in units of 1/den, e.g. (2, 2, 3) for 7/8

    def __post_init__(self) -> None:
        if self.num <= 0 or self.den not in (1, 2, 4, 8, 16, 32):
            raise ScoreError(f"invalid time signature {self.num}/{self.den}")
        if self.beat_groups is not None and sum(self.beat_groups) != self.num:
            raise ScoreError(f"beat groups {self.beat_groups} do not add up to {self.num}")

    @classmethod
    def parse(cls, text: str, beat_groups: Any = None) -> "TimeSig":
        try:
            n, d = text.strip().split("/")
            groups = None
            if beat_groups:
                if isinstance(beat_groups, str):
                    groups = tuple(int(x) for x in beat_groups.replace("+", " ").replace(",", " ").split())
                else:
                    groups = tuple(int(x) for x in beat_groups)
            return cls(int(n), int(d), groups)
        except (ValueError, AttributeError) as exc:
            raise ScoreError(f"cannot parse time signature {text!r}") from exc

    def __str__(self) -> str:
        return f"{self.num}/{self.den}"

    @property
    def bar_length(self) -> Fraction:
        return Fraction(self.num, self.den)

    @property
    def is_compound(self) -> bool:
        return self.den >= 8 and self.num % 3 == 0 and self.num >= 6 and self.beat_groups is None

    @property
    def is_irregular(self) -> bool:
        return self.beat_groups is not None or (self.den >= 8 and self.num in (5, 7, 10, 11, 13))

    def groups(self) -> tuple[int, ...]:
        """Beat groups in units of 1/den."""
        if self.beat_groups is not None:
            return self.beat_groups
        if self.is_compound:
            return tuple([3] * (self.num // 3))
        if self.is_irregular:
            if self.num == 5:
                return (2, 3)
            if self.num % 2 == 0:
                return tuple([2] * (self.num // 2))
            return tuple([2] * ((self.num - 3) // 2) + [3])
        if self.den >= 8 and self.num in (2, 3, 4):  # 2/8, 3/8, 4/8: beamed in one or two groups
            return {2: (2,), 3: (3,), 4: (2, 2)}[self.num]
        return tuple([1] * self.num)

    def beats(self) -> list[tuple[Fraction, Fraction]]:
        """(start, length) of each beat in whole notes."""
        out = []
        pos = Fraction(0)
        for g in self.groups():
            length = Fraction(g, self.den)
            out.append((pos, length))
            pos += length
        return out

    @property
    def beat_unit(self) -> Fraction:
        """Most common beat length (used for the tempo mark)."""
        beats = [length for _, length in self.beats()]
        return max(set(beats), key=beats.count)

    def metronome_unit(self) -> tuple[Fraction | None, bool]:
        """Note value of the tempo mark as (undotted value, dotted?), or (None, False)
        for a plain quarter-note mark. Compound meters and 3/8 count dotted beats;
        irregular meters (5/8, 7/8) mix beat lengths, so they keep the quarter."""
        unit = self.beat_unit
        if self.is_irregular:
            return (unit, False) if unit == Fraction(1, 4) else (None, False)
        if unit.numerator == 3 and (Fraction(3, 2) / unit).denominator == 1:
            return unit * 2 / 3, True
        return (unit, False) if (1 / unit).denominator == 1 else (None, False)

    def half_bar_spans(self) -> list[tuple[Fraction, Fraction]] | None:
        """Half-bar nodes for the rest hierarchy (only meters with a strong middle)."""
        beats = self.beats()
        if len(beats) in (2, 4) and len({b[1] for b in beats}) == 1:
            half = self.bar_length / 2
            return [(Fraction(0), half), (half, half)]
        return None


@dataclass
class Hit:
    pos: Fraction
    inst: str
    velocity: int = 90
    accent: bool = False
    ghost: bool = False
    flam: bool = False
    drag: bool = False
    roll: Fraction | None = None  # notated roll duration in whole notes
    choke: bool = False
    confidence: float = 1.0
    sticking: str | None = None  # hand(s) to play it with, printed under the staff: R, L, B (both), RL...
    time: float | None = None  # performed onset in seconds (audio/MIDI sources)
    offset_ms: float | None = None  # performed time minus quantized time

    def key(self) -> tuple[Fraction, str]:
        return (self.pos, self.inst)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"pos": frac_str(self.pos), "inst": self.inst}
        if self.velocity != 90:
            d["velocity"] = self.velocity
        for name in ("accent", "ghost", "flam", "drag", "choke"):
            if getattr(self, name):
                d[name] = True
        if self.roll is not None:
            d["roll"] = frac_str(self.roll)
        if self.confidence != 1.0:
            d["confidence"] = round(self.confidence, 3)
        if self.sticking:
            d["sticking"] = self.sticking
        if self.time is not None:
            d["time"] = round(self.time, 4)
        if self.offset_ms is not None:
            d["offset_ms"] = round(self.offset_ms, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Hit":
        unknown = set(d) - {"pos", "inst", "velocity", "accent", "ghost", "flam", "drag", "roll",
                            "choke", "confidence", "sticking", "time", "offset_ms"}
        if unknown:
            raise ScoreError(f"unknown hit fields {sorted(unknown)}")
        return cls(
            pos=frac(d["pos"]),
            inst=d["inst"],
            velocity=int(d.get("velocity", 90)),
            accent=bool(d.get("accent", False)),
            ghost=bool(d.get("ghost", False)),
            flam=bool(d.get("flam", False)),
            drag=bool(d.get("drag", False)),
            roll=frac(d["roll"]) if d.get("roll") is not None else None,
            choke=bool(d.get("choke", False)),
            confidence=float(d.get("confidence", 1.0)),
            sticking=d.get("sticking"),
            time=d.get("time"),
            offset_ms=d.get("offset_ms"),
        )


@dataclass
class Measure:
    time_sig: TimeSig
    hits: list[Hit] = field(default_factory=list)
    length: Fraction | None = None  # set only for a pickup bar shorter than the time signature
    tempo: float | None = None  # new tempo (quarter notes per minute) starting at this bar
    tempo_text: str | None = None  # e.g. "Swing", "Half-time feel"
    section: str | None = None  # section label starting at this bar
    cue: str | None = None  # text above the staff at the start of the bar ("Band in", "Gtr. solo")
    uncertain: bool = False  # contains low-confidence material needing human review
    notes: list[str] = field(default_factory=list)  # free-text review notes (not printed)
    start_time: float | None = None  # performed start of the bar in seconds (audio sources)

    @property
    def actual_length(self) -> Fraction:
        return self.length if self.length is not None else self.time_sig.bar_length

    @property
    def is_pickup(self) -> bool:
        return self.length is not None and self.length < self.time_sig.bar_length

    def musical_signature(self) -> tuple:
        """Everything that is printed for this bar, used to detect exact repeats."""
        hits = tuple(sorted(
            (h.pos, h.inst, h.accent, h.ghost, h.flam, h.drag, h.roll, h.choke, h.sticking or "")
            for h in self.hits
        ))
        return (str(self.time_sig), self.time_sig.beat_groups, self.actual_length, hits, self.cue or "")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"time": str(self.time_sig)}
        if self.time_sig.beat_groups:
            d["beat_groups"] = list(self.time_sig.beat_groups)
        if self.length is not None:
            d["length"] = frac_str(self.length)
        if self.tempo is not None:
            d["tempo"] = round(self.tempo, 2)
        if self.tempo_text:
            d["tempo_text"] = self.tempo_text
        if self.section:
            d["section"] = self.section
        if self.cue:
            d["cue"] = self.cue
        if self.uncertain:
            d["uncertain"] = True
        if self.notes:
            d["notes"] = list(self.notes)
        if self.start_time is not None:
            d["start_time"] = round(self.start_time, 4)
        d["hits"] = [h.to_dict() for h in sorted(self.hits, key=lambda h: (h.pos, h.inst))]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Measure":
        return cls(
            time_sig=TimeSig.parse(d["time"], d.get("beat_groups")),
            hits=[Hit.from_dict(h) for h in d.get("hits", [])],
            length=frac(d["length"]) if d.get("length") is not None else None,
            tempo=float(d["tempo"]) if d.get("tempo") is not None else None,
            tempo_text=d.get("tempo_text"),
            section=d.get("section"),
            cue=d.get("cue"),
            uncertain=bool(d.get("uncertain", False)),
            notes=list(d.get("notes", [])),
            start_time=d.get("start_time"),
        )


@dataclass
class Score:
    measures: list[Measure]
    title: str = "Untitled"
    artist: str | None = None
    transcriber: str | None = None
    chart_type: str = "full_transcription"
    status: str = "draft"  # never "verified" by default: that claim needs a human (edit --status)
    rights: str | None = None
    source: str | None = None
    swing: bool = False
    feel_note: str | None = None
    copyright: str | None = None
    analysis: dict[str, Any] = field(default_factory=dict)  # transcription diagnostics

    # ---- derived helpers -------------------------------------------------
    @property
    def initial_tempo(self) -> float:
        """Tempo of bar 1. Without a mark it is 120 (what validate() warns about,
        what our MIDI writes and what the LilyPond MIDI score is told)."""
        if self.measures and self.measures[0].tempo is not None:
            return self.measures[0].tempo
        return 120.0

    def tempo_at(self, index: int) -> float:
        tempo = self.initial_tempo
        for m in self.measures[: index + 1]:
            if m.tempo is not None:
                tempo = m.tempo
        return tempo

    def measure_starts(self) -> list[Fraction]:
        """Absolute start of each bar in whole notes."""
        out, pos = [], Fraction(0)
        for m in self.measures:
            out.append(pos)
            pos += m.actual_length
        return out

    def measure_start_seconds(self) -> list[float]:
        """Nominal (quantized-tempo) start time of each bar in seconds."""
        out, t = [], 0.0
        tempo = self.initial_tempo
        for m in self.measures:
            if m.tempo is not None:
                tempo = m.tempo
            out.append(t)
            t += float(m.actual_length) * 4 * 60.0 / tempo
        return out

    def hihat_close_marks(self) -> set[tuple[int, Fraction]]:
        """(bar index, position) of closed hi-hat strokes that get a "+".

        The "+" goes on the first closed stick stroke after an open or half-open
        one. The state is followed in time order over both voices (a pedal stroke
        closes the hat as well), in performance order; for repeated material that
        is the first pass, which is what the printed bars show.
        """
        marks: set[tuple[int, Fraction]] = set()
        is_open = False
        for i, m in enumerate(self.measures):
            at: dict[Fraction, set[str]] = {}
            for h in m.hits:
                at.setdefault(h.pos, set()).add(h.inst)
            for pos in sorted(at):
                insts = at[pos]
                if "hihat" in insts and is_open:
                    marks.add((i, pos))
                if insts & {"hihat_open", "hihat_half"}:
                    is_open = True
                elif insts & {"hihat", "hihat_pedal"}:
                    is_open = False
        return marks

    def iter_hits(self) -> Iterator[tuple[int, Measure, Hit]]:
        for i, m in enumerate(self.measures):
            for h in sorted(m.hits, key=lambda h: (h.pos, h.inst)):
                yield i, m, h

    def instruments_used(self) -> list[str]:
        used = {h.inst for _, _, h in self.iter_hits()}
        return [i for i in DEFAULT_KIT.ids() if i in used] + sorted(used - set(DEFAULT_KIT.ids()))

    def event_list(self) -> list[tuple[Fraction, str]]:
        """Canonical (absolute position, instrument) list used to compare exports."""
        starts = self.measure_starts()
        return sorted((starts[i] + h.pos, h.inst) for i, _, h in self.iter_hits())

    # ---- validation ------------------------------------------------------
    def validate(self, kit: Kit = DEFAULT_KIT) -> list[str]:
        """Raise ScoreError for structural problems; return non-fatal warnings."""
        warnings: list[str] = []
        if not self.measures:
            raise ScoreError("score has no measures")
        if self.chart_type not in CHART_TYPES:
            raise ScoreError(f"chart_type must be one of {sorted(CHART_TYPES)}")
        if self.status not in STATUSES:
            raise ScoreError(f"status must be one of {sorted(STATUSES)}")
        if self.rights is not None and self.rights not in RIGHTS:
            raise ScoreError(f"rights must be one of {sorted(RIGHTS)}")
        for name in ("title", "artist", "transcriber", "source", "feel_note", "copyright"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ScoreError(f"{name} must be text, got {value!r}")
        if not isinstance(self.title, str):
            raise ScoreError("title must be text")
        if self.measures[0].tempo is None:
            warnings.append("bar 1 has no tempo; 120 BPM assumed")
        for i, m in enumerate(self.measures, start=1):
            for name in ("section", "tempo_text", "cue"):
                value = getattr(m, name)
                if value is not None and not isinstance(value, str):
                    raise ScoreError(f"bar {i}: {name} must be text, got {value!r}")
            if not all(isinstance(n, str) for n in m.notes):
                raise ScoreError(f"bar {i}: notes must be texts")
            if m.length is not None:
                if i != 1:
                    raise ScoreError(f"bar {i}: only the first bar may be a pickup (shorter bar)")
                if not (0 < m.length < m.time_sig.bar_length):
                    raise ScoreError(f"bar {i}: pickup length {m.length} must be shorter than the bar")
            if m.tempo is not None and not (20 <= m.tempo <= 400):
                raise ScoreError(f"bar {i}: tempo {m.tempo} BPM is outside 20-400")
            seen: set[tuple[Fraction, str]] = set()
            for h in m.hits:
                if h.inst not in kit:
                    raise ScoreError(f"bar {i}: unknown instrument {h.inst!r}")
                if not (0 <= h.pos < m.actual_length):
                    raise ScoreError(f"bar {i}: {h.inst} at {h.pos} is outside the bar (length {m.actual_length})")
                if h.key() in seen:
                    raise ScoreError(f"bar {i}: duplicate {h.inst} at {h.pos}")
                seen.add(h.key())
                if not 1 <= h.velocity <= 127:
                    raise ScoreError(f"bar {i}: velocity {h.velocity} out of range")
                if h.accent and h.ghost:
                    raise ScoreError(f"bar {i}: {h.inst} at {h.pos} cannot be both accent and ghost")
                if h.roll is not None:
                    if h.roll <= 0:
                        raise ScoreError(f"bar {i}: roll length must be positive")
                    if h.pos + h.roll > m.actual_length:
                        raise ScoreError(f"bar {i}: roll at {h.pos} runs past the barline; split it across bars")
                if not 0.0 <= h.confidence <= 1.0:
                    raise ScoreError(f"bar {i}: confidence must be within 0..1")
                if h.sticking is not None and (not isinstance(h.sticking, str)
                                               or not STICKING.fullmatch(h.sticking)):
                    raise ScoreError(f"bar {i}: sticking {h.sticking!r} at {h.pos}: use R, L or B "
                                     f"(both hands), up to three letters such as RL")
            # Hi-hat physically can't be open and closed at the same instant.
            by_pos: dict[Fraction, set[str]] = {}
            for h in m.hits:
                by_pos.setdefault(h.pos, set()).add(h.inst)
            for pos, insts in by_pos.items():
                stick_hh = insts & {"hihat", "hihat_open", "hihat_half"}
                if len(stick_hh) > 1:
                    raise ScoreError(f"bar {i}: conflicting hi-hat states {sorted(stick_hh)} at {pos}")
                hands = [x for x in insts if not kit.is_foot(x)]
                if len(hands) > 3:
                    warnings.append(f"bar {i}: {len(hands)} simultaneous hand strokes at {pos} "
                                    f"({', '.join(sorted(hands))}) - check playability")
        return warnings

    # ---- serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"schema": SCHEMA_VERSION, "title": self.title}
        for name in ("artist", "transcriber", "rights", "source", "feel_note", "copyright"):
            if getattr(self, name):
                d[name] = getattr(self, name)
        d["chart_type"] = self.chart_type
        d["status"] = self.status
        if self.swing:
            d["swing"] = True
        if self.analysis:
            d["analysis"] = self.analysis
        d["measures"] = [m.to_dict() for m in self.measures]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Score":
        if d.get("schema", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ScoreError(f"score.json schema {d.get('schema')!r} is not supported: this drum_agent reads "
                             f"schema {SCHEMA_VERSION}" + (" (the file is from a newer version)"
                                                          if isinstance(d.get("schema"), int)
                                                          and d["schema"] > SCHEMA_VERSION else ""))
        return cls(
            measures=[Measure.from_dict(m) for m in d["measures"]],
            title=d.get("title", "Untitled"),
            artist=d.get("artist"),
            transcriber=d.get("transcriber"),
            chart_type=d.get("chart_type", "full_transcription"),
            status=d.get("status", "draft"),
            rights=d.get("rights"),
            source=d.get("source"),
            swing=bool(d.get("swing", False)),
            feel_note=d.get("feel_note"),
            copyright=d.get("copyright"),
            analysis=d.get("analysis", {}),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "Score":
        return cls.from_dict(json.loads(Path(path).read_text()))


def is_power_of_two_fraction(f: Fraction) -> bool:
    """True for 1, 1/2, 1/4, ... and 2, 4 (note values without dots)."""
    if f <= 0:
        return False
    n, d = f.numerator, f.denominator
    return (n == 1 and d & (d - 1) == 0) or (d == 1 and n & (n - 1) == 0)


def log2_fraction(f: Fraction) -> int:
    return int(round(math.log2(f)))
