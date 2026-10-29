"""Drum kit definition: the single table that maps instruments to notation.

Every exporter (LilyPond, MusicXML, MIDI), the legend and the transcription
classes read from here. See docs/NOTATION_SPEC.md §3.

Staff positions use LilyPond's convention: 0 is the middle line (B4 in treble
clef terms) and each step is half a staff space, so the snare (3rd space) is 1
and the bass drum (1st space) is -3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

# Staff position -> (display step, display octave) for MusicXML, treble-clef equivalent.
_STEPS = ["C", "D", "E", "F", "G", "A", "B"]


def position_to_pitch(position: int) -> tuple[str, int]:
    """Convert a LilyPond staff position (0 = B4) to a treble-clef step/octave."""
    # B4 is diatonic index 4*7 + 6 = 34.
    idx = 34 + position
    return _STEPS[idx % 7], idx // 7


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    position: int
    notehead: str  # "normal", "cross", "xcircle", "diamond", "triangle", "slashed"
    voice: int  # 1 = hands (stems up), 2 = feet (stems down)
    midi: int  # General MIDI percussion key (channel 10)
    articulation: str | None = None  # "open", "halfopen", "stopped", "open-down"
    family: str = "drum"  # drum | cymbal | hihat | percussion
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ly_name(self) -> str:
        """Alphabetic name used inside LilyPond's \\drummode."""
        digits = {"1": "one", "2": "two"}
        out = self.id
        for d, w in digits.items():
            out = out.replace(d, w)
        return out.replace("_", "")


DEFAULT_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument("china", "China", 8, "cross", 1, 52, family="cymbal", aliases=("cn", "chi")),
    Instrument("crash2", "Crash 2", 7, "cross", 1, 57, family="cymbal", aliases=("cr2", "c2")),
    Instrument("splash", "Splash", 7, "xcircle", 1, 55, family="cymbal", aliases=("spl",)),
    Instrument("crash", "Crash", 6, "cross", 1, 49, family="cymbal", aliases=("cr", "cc", "c")),
    Instrument("hihat", "Hi-hat", 5, "cross", 1, 42, family="hihat", aliases=("hh", "h", "hhc")),
    Instrument("hihat_open", "Open hi-hat", 5, "cross", 1, 46, articulation="open",
               family="hihat", aliases=("hho", "oh")),
    Instrument("hihat_half", "Half-open hi-hat", 5, "cross", 1, 46, articulation="halfopen",
               family="hihat", aliases=("hhh", "hhhalf")),
    Instrument("ride", "Ride", 4, "cross", 1, 51, family="cymbal", aliases=("rd", "r", "ri")),
    Instrument("ride_bell", "Ride bell", 4, "diamond", 1, 53, family="cymbal",
               aliases=("rb", "bell")),
    Instrument("tom1", "Tom 1", 3, "normal", 2, 48, aliases=("t1", "ht", "tomh")),
    Instrument("cowbell", "Cowbell", 3, "triangle", 1, 56, family="percussion",
               aliases=("cb", "cow")),
    Instrument("tom2", "Tom 2", 2, "normal", 2, 45, aliases=("t2", "mt", "tomm")),
    Instrument("snare", "Snare", 1, "normal", 2, 38, aliases=("sn", "sd", "s")),
    Instrument("cross_stick", "Cross-stick", 1, "cross", 2, 37, aliases=("cs", "xs", "ss")),
    Instrument("rimshot", "Rimshot", 1, "slashed", 2, 40, aliases=("rs", "rim")),
    Instrument("floor_tom", "Floor tom", -1, "normal", 2, 43, aliases=("ft", "t3", "tomf")),
    Instrument("floor_tom2", "Floor tom 2", -2, "normal", 2, 41, aliases=("ft2", "t4")),
    Instrument("kick", "Bass drum", -3, "normal", 2, 36, aliases=("bd", "k", "kd")),
    Instrument("kick2", "Bass drum 2", -4, "normal", 2, 35, aliases=("bd2", "k2")),
    Instrument("hihat_pedal", "Hi-hat (foot)", -5, "cross", 2, 44, family="hihat",
               aliases=("hf", "hhp", "hhf", "pedal")),
    Instrument("hihat_splash", "Hi-hat splash (foot)", -5, "cross", 2, 44,
               articulation="open-down", family="hihat", aliases=("hhs",)),
)


# Limbs: these are played with the feet; everything else with the hands.
FEET = frozenset({"kick", "kick2", "hihat_pedal", "hihat_splash"})

# Voicings: which instruments share the stems-up voice. "cymbals-up" (default):
# cymbals, hi-hat and cowbell stems up; snare, toms and feet stems down, as in
# Guitar Pro and Songsterr charts. "hands-up": everything the hands play stems
# up, the feet down (Weinberg / Percussive Arts Society).
VOICINGS = ("cymbals-up", "hands-up")
DEFAULT_VOICING = "cymbals-up"


def voicing_voice(ins: "Instrument", voicing: str) -> int:
    if voicing not in VOICINGS:
        raise KitError(f"unknown voicing {voicing!r}; use {' or '.join(VOICINGS)}")
    if ins.id in FEET:
        return 2
    if voicing == "hands-up":
        return 1
    return 1 if ins.family in ("cymbal", "hihat", "percussion") else 2


class KitError(ValueError):
    pass


NOTEHEADS = ("normal", "cross", "xcircle", "diamond", "triangle", "slashed")
ARTICULATIONS = (None, "open", "halfopen", "stopped", "open-down")
POSITION_RANGE = (-12, 16)  # staff steps from the middle line: far beyond any ledger line used


def _check_instrument(ins: Instrument) -> None:
    """Every field is written into the LilyPond source (some inside Scheme), so each one
    must be exactly the type and range expected: a kit file is data, never code."""
    def is_int(v: object) -> bool:
        return isinstance(v, int) and not isinstance(v, bool)

    if not isinstance(ins.id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", ins.id):
        raise KitError(f"instrument id {ins.id!r}: use lowercase letters, digits and _")
    if not isinstance(ins.name, str) or not ins.name.strip() or len(ins.name) > 40:
        raise KitError(f"{ins.id}: name must be a short text")
    if not is_int(ins.position) or not POSITION_RANGE[0] <= ins.position <= POSITION_RANGE[1]:
        raise KitError(f"{ins.id}: position must be a whole number from {POSITION_RANGE[0]} "
                       f"to {POSITION_RANGE[1]} (staff steps from the middle line), got {ins.position!r}")
    if ins.notehead not in NOTEHEADS:
        raise KitError(f"{ins.id}: notehead must be one of {', '.join(NOTEHEADS)}, got {ins.notehead!r}")
    if not is_int(ins.voice) or ins.voice not in (1, 2):
        raise KitError(f"{ins.id}: voice must be 1 (hands, stems up) or 2 (feet, stems down)")
    if not is_int(ins.midi) or not 0 <= ins.midi <= 127:
        raise KitError(f"{ins.id}: midi must be a note number from 0 to 127, got {ins.midi!r}")
    if ins.articulation not in ARTICULATIONS:
        raise KitError(f"{ins.id}: articulation must be one of "
                       f"{', '.join(a for a in ARTICULATIONS if a)} or null, got {ins.articulation!r}")
    if not all(isinstance(a, str) for a in ins.aliases):
        raise KitError(f"{ins.id}: aliases must be texts")


class Kit:
    """An instrument table with alias lookup. Immutable after construction."""

    def __init__(self, instruments: tuple[Instrument, ...] = DEFAULT_INSTRUMENTS):
        self.instruments = tuple(instruments)
        self._by_id: dict[str, Instrument] = {}
        self._alias: dict[str, str] = {}
        for ins in self.instruments:
            if ins.id in self._by_id:
                raise KitError(f"duplicate instrument id {ins.id!r}")
            _check_instrument(ins)
            self._by_id[ins.id] = ins
        for ins in self.instruments:
            for name in (ins.id, *ins.aliases):
                key = name.lower()
                if key in self._alias and self._alias[key] != ins.id:
                    raise KitError(f"alias {name!r} used by both {self._alias[key]} and {ins.id}")
                self._alias[key] = ins.id
        ly_names = [i.ly_name for i in self.instruments]
        if len(set(ly_names)) != len(ly_names):
            raise KitError("instrument ids must stay unique after LilyPond name conversion")

    def __contains__(self, inst_id: str) -> bool:
        return inst_id in self._by_id

    def __getitem__(self, inst_id: str) -> Instrument:
        try:
            return self._by_id[inst_id]
        except KeyError:
            raise KitError(f"unknown instrument {inst_id!r}; known: {', '.join(self._by_id)}") from None

    def resolve(self, name: str) -> str:
        """Return the canonical id for an id or alias (case-insensitive)."""
        try:
            return self._alias[name.lower()]
        except KeyError:
            raise KitError(f"unknown instrument or alias {name!r}") from None

    def ids(self) -> list[str]:
        return [i.id for i in self.instruments]

    def with_voicing(self, voicing: str) -> "Kit":
        """The same kit with stems assigned by a voicing (see VOICINGS)."""
        return Kit(tuple(replace(i, voice=voicing_voice(i, voicing)) for i in self.instruments))

    def is_foot(self, inst_id: str) -> bool:
        return inst_id in FEET

    def by_midi(self) -> dict[int, str]:
        """Default MIDI note -> instrument id (first instrument wins for shared notes)."""
        out: dict[int, str] = {}
        for ins in self.instruments:
            out.setdefault(ins.midi, ins.id)
        return out

    @classmethod
    def from_json(cls, path: str | Path, base: "Kit | None" = None) -> "Kit":
        """Load a kit override file: {"instruments": {"tom1": {"position": 4}, ...}}.

        Only listed fields change; unknown instrument ids are an error so typos
        can't silently produce a different chart.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise KitError(f"kit file {path}: {exc}") from None
        overrides = data.get("instruments", {}) if isinstance(data, dict) else None
        if not isinstance(overrides, dict):
            raise KitError(f'kit file {path}: expected {{"instruments": {{"tom1": {{"position": 4}}, ...}}}}')
        start = base.instruments if base is not None else DEFAULT_INSTRUMENTS
        base = {i.id: i for i in start}
        allowed = {"name", "position", "notehead", "voice", "midi", "articulation"}
        for inst_id, fields in overrides.items():
            if inst_id not in base:
                raise KitError(f"kit file {path}: unknown instrument {inst_id!r}")
            if not isinstance(fields, dict):
                raise KitError(f"kit file {path}: {inst_id} must map field names to values")
            bad = set(fields) - allowed
            if bad:
                raise KitError(f"kit file {path}: unsupported fields {sorted(bad)} for {inst_id}")
            base[inst_id] = replace(base[inst_id], **fields)
            try:
                _check_instrument(base[inst_id])
            except KitError as exc:
                raise KitError(f"kit file {path}: {exc}") from None
        return cls(tuple(base[i.id] for i in start))


DEFAULT_KIT = Kit()

# Pitch classes for the GM drum map, used by MIDI import. Several GM notes fold
# onto one notated instrument (e.g. 50 High Tom and 48 Hi-Mid Tom are both Tom 1
# on a 3-tom kit).
GM_IMPORT_MAP: dict[int, str] = {
    35: "kick", 36: "kick",
    37: "cross_stick",
    38: "snare", 40: "snare", 39: "snare",  # 39 hand clap rarely used in kits; treat as snare
    41: "floor_tom2", 43: "floor_tom",
    42: "hihat", 44: "hihat_pedal", 46: "hihat_open",
    45: "tom2", 47: "tom2",
    48: "tom1", 50: "tom1",
    49: "crash", 57: "crash2",
    51: "ride", 59: "ride",
    52: "china", 53: "ride_bell", 55: "splash", 56: "cowbell",
}
