"""The structured request the beat generator works from (`BeatSpec`).

Every field has a meaning a drummer would recognize; `None` means "the style's
default". A spec comes from the prompt (`parse.py`, or Claude when configured),
plus any settings the user overrides; `from_dict` validates and clamps anything
that comes from outside, so the engine only ever sees values it can play.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field, fields

from ..model import TimeSig
from .styles import DEFAULT_STYLE, STYLES

TIME_SIGNATURES = ("2/4", "3/4", "4/4", "5/4", "6/8", "7/8", "9/8", "12/8")
DIFFICULTIES = ("beginner", "intermediate", "advanced")
FEELS = ("straight", "triplet", "half_time", "double_time")
CYMBALS = ("hihat", "ride")
HAT_RATES = ("quarters", "8ths", "16ths", "shuffle", "triplets", "jazz_ride")
FILL_VOICES = ("toms", "snare", "mixed")
ENDINGS = ("none", "crash", "fill_crash", "stop", "dramatic")
ENERGIES = ("low", "medium", "high")
SECTIONS = ("Intro", "Verse", "Groove", "Pre-Chorus", "Chorus", "Bridge", "Breakdown", "Build", "Solo", "Outro")
LAYERS = ("kick", "snare", "hats", "fills", "variation")
MIN_BPM, MAX_BPM = 40, 300
MAX_BARS = 64
COMPLEXITY = {"beginner": 0.2, "intermediate": 0.5, "advanced": 0.8}


@dataclass
class BeatSpec:
    style: str = DEFAULT_STYLE
    bpm: float | None = None
    time_signature: str | None = None
    bars: int = 8
    difficulty: str = "intermediate"
    complexity: float | None = None  # 0..1; None: from the difficulty
    feel: str | None = None  # None: the style's
    cymbal: str | None = None
    hat_rate: str | None = None
    open_hats: bool | None = None
    ghost_notes: bool | None = None
    syncopation: float | None = None  # kick syncopation 0..1, None: the style's
    double_bass: bool | None = None
    cross_stick: bool | None = None
    fill_every: int | None = None  # bars between fills; 0 = no fills; None: the phrase length
    fill_beats: int | None = None  # fill length in beats; None: from the phrase and difficulty
    fill_voice: str = "toms"
    crashes: str = "sections"  # none | sections | phrases
    ending: str | None = None  # None: none for a loop of up to 8 bars, else a fill and a final crash
    energy: str | None = None
    sections: list[str] | None = None  # section names in order; None: planned from the length
    title: str | None = None
    seed: int = 1
    layer_seeds: dict[str, int] = field(default_factory=dict)  # per-layer reseeds (variations)

    # ---- derived ---------------------------------------------------------
    @property
    def style_def(self):
        return STYLES[self.style]

    def resolved_bpm(self) -> float:
        return float(self.bpm if self.bpm is not None else self.style_def.bpm)

    def resolved_time_signature(self) -> str:
        return self.time_signature or self.style_def.time_signature

    def resolved_complexity(self) -> float:
        return self.complexity if self.complexity is not None else COMPLEXITY[self.difficulty]

    def resolved_ending(self) -> str:
        if self.ending is not None:
            return self.ending
        return "none" if self.bars <= 8 else "fill_crash"

    def resolved_energy(self) -> str:
        return self.energy or self.style_def.energy

    def layer_seed(self, layer: str) -> str:
        return f"{self.seed}:{layer}:{self.layer_seeds.get(layer, 0)}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> BeatSpec:
        """A spec from untrusted input: unknown keys are ignored, values clamped or reset."""
        d = dict(d or {})
        known = {f.name for f in fields(cls)}
        spec = cls(**{k: v for k, v in d.items() if k in known and k not in ("layer_seeds", "sections")})
        spec.layer_seeds = {k: int(v) for k, v in (d.get("layer_seeds") or {}).items()
                            if k in LAYERS and isinstance(v, (int, float))}
        secs = d.get("sections")
        spec.sections = [s for s in secs if s in SECTIONS][:12] if isinstance(secs, list) else None
        return spec.clamped()

    def clamped(self) -> BeatSpec:
        if self.style not in STYLES:
            self.style = DEFAULT_STYLE
        if self.bpm is not None:
            try:
                self.bpm = float(min(MAX_BPM, max(MIN_BPM, float(self.bpm))))
            except (TypeError, ValueError):
                self.bpm = None
        if self.time_signature is not None:
            ts = str(self.time_signature).strip()
            self.time_signature = ts if ts in TIME_SIGNATURES else None
        try:
            self.bars = int(min(MAX_BARS, max(1, int(self.bars))))
        except (TypeError, ValueError):
            self.bars = 8
        if self.difficulty not in DIFFICULTIES:
            self.difficulty = "intermediate"
        if self.complexity is not None:
            try:
                self.complexity = round(min(1.0, max(0.0, float(self.complexity))), 3)
            except (TypeError, ValueError):
                self.complexity = None
        if self.syncopation is not None:
            try:
                self.syncopation = round(min(1.0, max(0.0, float(self.syncopation))), 3)
            except (TypeError, ValueError):
                self.syncopation = None
        for name, allowed in (("feel", FEELS), ("cymbal", CYMBALS), ("hat_rate", HAT_RATES), ("energy", ENERGIES)):
            if getattr(self, name) not in allowed:
                setattr(self, name, None)
        if self.fill_voice not in FILL_VOICES:
            self.fill_voice = "toms"
        if self.ending is not None and self.ending not in ENDINGS:
            self.ending = None
        if self.crashes not in ("none", "sections", "phrases"):
            self.crashes = "sections"
        for name in ("fill_every", "fill_beats"):
            v = getattr(self, name)
            if v is not None:
                try:
                    setattr(self, name, int(min(MAX_BARS if name == "fill_every" else 16, max(0, int(v)))))
                except (TypeError, ValueError):
                    setattr(self, name, None)
        for name in ("open_hats", "ghost_notes", "double_bass", "cross_stick"):
            v = getattr(self, name)
            if v is not None and not isinstance(v, bool):
                setattr(self, name, bool(v))
        try:
            self.seed = int(self.seed) % 2**31
        except (TypeError, ValueError):
            self.seed = 1
        if self.title is not None:
            self.title = " ".join(str(self.title).split())[:120] or None
        # A meter the style's feel can't use falls back to a plain feel.
        ts = TimeSig.parse(self.resolved_time_signature())
        if ts.is_compound or ts.is_irregular:
            if self.feel == "triplet":
                self.feel = "straight"
            if self.hat_rate in ("shuffle", "triplets", "jazz_ride"):
                self.hat_rate = None
        return self


def new_seed() -> int:
    return random.SystemRandom().randrange(1, 2**31)
