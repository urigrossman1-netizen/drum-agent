"""The beat generator: a `BeatSpec` in, a `Score` of real strokes out.

The steps:

1. Plan sections from the length (or the requested sections) and give each a role:
   intro, main, high (chorus), breakdown, build.
2. Write each section's groove from the style's conventions on a metric grid:
   - the cymbal hand: hi-hat, ride, crash quarters, open hats;
   - the backbeat;
   - the kick: its core, plus syncopations drawn per slot;
   - ghost notes and open hi-hats.
3. Vary the last bar of a phrase. Put fills at phrase ends, crashes after fills and
   at section starts, and the ending.
4. Make it playable: never more than two hands or a foot per limb at once.

Randomness is seeded per layer (kick, snare, hats, fills, variation), and every
optional stroke has a fixed draw compared with its probability. So:

- the same spec gives the same beat;
- reseeding one layer changes only that layer;
- raising the complexity adds strokes to the same groove instead of replacing it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction

from ..kit import DEFAULT_KIT, Kit
from ..model import Hit, Measure, Score, TimeSig
from .spec import BeatSpec
from .styles import Style

ENGINE_VERSION = "beatgen-1"
HAND_CYMBALS = {"hihat", "hihat_open", "hihat_half", "ride", "ride_bell", "crash", "crash2", "china", "splash"}
VEL = {  # energy -> (accent, backbeat, kick, cymbal strong, cymbal weak, ghost)
    "low": (105, 92, 88, 78, 58, 30),
    "medium": (118, 108, 100, 88, 68, 34),
    "high": (124, 118, 112, 96, 76, 38),
}


@dataclass(frozen=True)
class Step:
    pos: Fraction
    beat: int
    level: str  # "1", "&", "e", "a" (16ths) or "1", "trip", "let" (triplets)

    @property
    def slot(self) -> str:
        return f"{self.beat + 1}{self.level}"


@dataclass
class Section:
    name: str
    role: str  # intro | main | high | breakdown | build
    first: int  # first bar (0-based)
    bars: int


def grid(ts: TimeSig, triplet: bool) -> list[Step]:
    """Every 16th (or, with a triplet feel, every triplet 8th) of the bar, named by level."""
    steps: list[Step] = []
    for b, (start, length) in enumerate(ts.beats()):
        eighths = int(length / Fraction(1, 8))
        if triplet and eighths == 2:
            for k, name in enumerate(("1", "trip", "let")):
                steps.append(Step(start + k * length / 3, b, name))
            continue
        for k in range(eighths * 2):
            if k == 0:
                name = "1"
            elif eighths == 2:
                name = ("1", "e", "&", "a")[k]
            else:  # a compound or long beat: inner 8ths are offbeats, 16ths between them
                name = "&" if k % 2 == 0 else ("e" if k % 4 == 1 else "a")
            steps.append(Step(start + k * Fraction(1, 16), b, name))
    return steps


class Bar:
    """The strokes of one bar, at most one per (position, instrument)."""

    def __init__(self, ts: TimeSig):
        self.ts = ts
        self.hits: dict[tuple[Fraction, str], Hit] = {}

    def add(self, pos: Fraction, inst: str, velocity: int, **flags) -> Hit:
        h = Hit(pos=pos, inst=inst, velocity=max(1, min(127, int(velocity))), **flags)
        self.hits[(pos, inst)] = h
        return h

    def remove(self, pred) -> None:
        for k in [k for k, h in self.hits.items() if pred(h)]:
            del self.hits[k]

    def at(self, pos: Fraction) -> list[Hit]:
        return [h for (p, _), h in self.hits.items() if p == pos]

    def sorted(self) -> list[Hit]:
        return sorted(self.hits.values(), key=lambda h: (h.pos, h.inst))


def plan_sections(spec: BeatSpec, style: Style) -> list[Section]:
    n = spec.bars
    roles = {"Intro": "intro", "Verse": "main", "Groove": "main", "Pre-Chorus": "build", "Chorus": "high",
             "Bridge": "breakdown", "Breakdown": "breakdown", "Build": "build", "Solo": "high", "Outro": "main"}
    if spec.sections:
        names = list(spec.sections)[:n]
        base = max(1, n // len(names))
        lengths = [base] * len(names)
        lengths[-1] += n - sum(lengths)
    elif n <= 8:
        names, lengths = ["Groove"], [n]
    elif n <= 12:
        names, lengths = ["Verse", "Chorus"], [8, n - 8]
    elif n <= 16:
        names, lengths = ["Verse", "Chorus"], [n - 8, 8]
    elif n <= 20:
        names, lengths = ["Intro", "Verse", "Chorus"], [4, 8, n - 12]
    elif n <= 28:
        names, lengths = ["Intro", "Verse", "Chorus", "Outro"], [4, 8, 8, n - 20]
    else:
        names, lengths = ["Intro", "Verse", "Chorus", "Bridge", "Chorus"], [4, 8, 8, 4, 8]
        rest = n - 32
        while rest > 0:
            add = min(8, rest)
            names.append("Verse" if len(names) % 2 else "Chorus")
            lengths.append(add)
            rest -= add
    out, first = [], 0
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    seen: dict[str, int] = {}
    for name, length in zip(names, lengths):
        if length <= 0:
            continue
        seen[name] = seen.get(name, 0) + 1
        label = f"{name} {seen[name]}" if counts[name] > 1 and name in ("Verse", "Chorus") else name
        out.append(Section(label, roles.get(name, "main"), first, length))
        first += length
    return out


class Engine:
    def __init__(self, spec: BeatSpec, kit: Kit = DEFAULT_KIT):
        self.spec = spec.clamped()
        self.style = self.spec.style_def
        self.kit = kit
        self.ts = TimeSig.parse(self.spec.resolved_time_signature())
        simple = not (self.ts.is_compound or self.ts.is_irregular)
        feel = self.spec.feel
        self.triplet = simple and (feel == "triplet" or (feel is None and self.style.triplet))
        self.steps = grid(self.ts, self.triplet)
        self.complexity = self.spec.resolved_complexity()
        self.energy = self.spec.resolved_energy()
        self.v = VEL[self.energy]
        self.beginner = self.spec.difficulty == "beginner"
        self.advanced = self.spec.difficulty == "advanced"
        n = len(self.ts.beats())
        self.backbeats = self._backbeats(n)
        self._draws: dict[str, list[float]] = {}

    # ---- randomness --------------------------------------------------------
    def rng(self, layer: str, *keys) -> random.Random:
        return random.Random(":".join([self.spec.layer_seed(layer), *map(str, keys)]))

    def draws(self, layer: str, key: str) -> list[float]:
        """One fixed draw per grid step: a stroke is kept when its draw is under its probability."""
        k = f"{layer}:{key}"
        if k not in self._draws:
            r = self.rng(layer, key)
            self._draws[k] = [r.random() for _ in self.steps]
        return self._draws[k]

    # ---- conventions --------------------------------------------------------
    def _backbeats(self, n: int) -> set[int]:
        feel, style = self.spec.feel, self.style
        mode = style.backbeat
        if feel == "half_time":
            mode = "3"
        if mode == "none" or mode == "one_drop" and n < 3:
            return set()
        if mode == "one_drop" or mode == "3":
            return {n // 2} if n > 1 else {0}
        if mode == "all":
            return set(range(n))
        if mode == "2&3":
            return {1, 2} if n >= 3 else {1}
        if n == 1:
            return set()
        if n == 3:
            return {2}
        return {b for b in range(n) if b % 2 == 1}

    def hat_rate(self, role: str) -> str:
        rate = self.spec.hat_rate or self.style.hat_rate
        if self.triplet and rate == "8ths":
            rate = "shuffle"
        if not self.triplet and rate in ("shuffle", "triplets", "jazz_ride"):
            rate = "8ths"
        if self.beginner and rate == "16ths":
            rate = "8ths"
        bpm = self.spec.resolved_bpm()
        if rate == "16ths" and bpm > 140:
            rate = "8ths"  # one hand can't keep 16ths on the hi-hat this fast
        if rate == "8ths" and bpm > 230 and not self.triplet:
            rate = "quarters"
        if role == "intro" and rate == "16ths":
            rate = "8ths"
        return rate

    def cymbal_steps(self, rate: str) -> list[Step]:
        if rate == "quarters":
            return [s for s in self.steps if s.level == "1"]
        if rate == "8ths":
            return [s for s in self.steps if s.level in ("1", "&")]
        if rate == "16ths" or rate == "triplets":
            return list(self.steps)
        if rate == "shuffle":
            return [s for s in self.steps if s.level in ("1", "let")]
        if rate == "jazz_ride":
            return [s for s in self.steps if s.level == "1" or (s.level == "let" and s.beat % 2 == 1)]
        return [s for s in self.steps if s.level in ("1", "&")]

    # ---- one groove bar ---------------------------------------------------
    def groove(self, role: str, bar_in_phrase: int, phrase_len: int, section_index: int, bar_index: int) -> Bar:
        st, spec, v = self.style, self.spec, self.v
        bar = Bar(self.ts)
        complexity = self.complexity
        if role == "high":
            complexity = min(1.0, complexity + 0.15)
        elif role in ("intro", "breakdown"):
            complexity = max(0.0, complexity - 0.2)
        last_of_phrase = bar_in_phrase == phrase_len - 1
        backbeat_beats = self.backbeats if role != "breakdown" or st.breakdown != "half_time" else self._half()
        double_time = spec.feel == "double_time"

        # The cymbal hand.
        cymbal = spec.cymbal or st.cymbal
        rate = self.hat_rate(role)
        steps = self.cymbal_steps(rate)
        inst, open_all = ("ride" if cymbal == "ride" else "hihat"), False
        if role == "high":
            if st.chorus == "ride":
                inst = "ride"
            elif st.chorus == "crash_quarters":
                inst, steps = "crash", [s for s in self.steps if s.level == "1"]
            elif st.chorus == "open_hats":
                open_all = True
                steps = [s for s in self.steps if s.level in ("1", "&")] if not self.triplet else steps
        if role == "breakdown":
            if st.breakdown == "floor_tom":
                inst = "floor_tom"
            elif cymbal != "ride":
                inst = "ride"
        for s in steps:
            strong = s.level == "1"
            vel = v[3] if strong else (v[4] + 6 if s.level in ("&", "let") else v[4])
            name = "hihat_open" if open_all and inst == "hihat" else inst
            if inst == "crash":
                vel = v[0] - 6
            bar.add(s.pos, name, vel)
        if rate == "16ths" and inst in ("hihat", "ride") and bar_in_phrase % 2 == 1 and not open_all:
            r = self.rng("hats", "variation", section_index, bar_in_phrase)
            for s in steps:
                if s.level in ("e", "a") and r.random() < 0.25 + 0.3 * (1 - complexity):
                    bar.hits.pop((s.pos, inst), None)
        if st.disco_hats and inst == "hihat" and not self.triplet:
            for s in self.steps:
                if s.level == "&":
                    bar.add(s.pos, "hihat_open", v[3])
                    bar.hits.pop((s.pos, "hihat"), None)

        # The backbeat.
        snare = "cross_stick" if (spec.cross_stick or (spec.cross_stick is None and st.snare_inst == "cross_stick"
                                                        and role not in ("high", "build"))) else "snare"
        if double_time:
            for s in self.steps:
                if s.level == ("let" if self.triplet else "&"):
                    bar.add(s.pos, snare, v[1])
        else:
            for s in self.steps:
                if s.level == "1" and s.beat in backbeat_beats:
                    bar.add(s.pos, snare, v[1])

        # The kick.
        kick_steps = self.kick(role, complexity, backbeat_beats, double_time)
        if last_of_phrase and complexity >= 0.3 and role != "intro":
            kick_steps |= self.kick_variation(section_index, backbeat_beats)
        for s in kick_steps:
            bar.add(s.pos, "kick", v[2] if s.level == "1" else v[2] - 8)

        # Ghost notes (hands permitting).
        ghosts = spec.ghost_notes if spec.ghost_notes is not None else (st.ghosts > 0 and not self.beginner)
        if ghosts and role != "intro" and not double_time:
            density = (st.ghosts or 0.3) * (0.15 + 0.75 * complexity)
            draws = self.draws("snare", "ghosts")
            slots = [k for k, s in enumerate(self.steps) if s.level in ("e", "a", "trip")
                     and not any(h.inst in (snare, "snare") for h in bar.at(s.pos))]
            picked = [k for k in slots if draws[k] < density]
            if spec.ghost_notes:  # asked for: always a few, the likeliest slots first
                want = 1 + (complexity >= 0.4) + (complexity >= 0.7)
                for k in sorted(slots, key=lambda k: draws[k]):
                    if len(picked) >= want:
                        break
                    if k not in picked:
                        picked.append(k)
            for k in picked:
                bar.add(self.steps[k].pos, "snare", v[5], ghost=True)

        # Open hi-hat at the end of a phrase bar (or every other bar when busy).
        opens = spec.open_hats if spec.open_hats is not None else st.open_hats > 0
        if opens and inst == "hihat" and not open_all and not st.disco_hats:
            p = (st.open_hats or 0.5) * (0.6 + complexity)
            u = self.rng("hats", "open", section_index, bar_in_phrase).random()
            if (last_of_phrase and u < p + 0.3) or (bar_in_phrase % 2 == 1 and u < p * 0.6):
                last = [s for s in steps if s.level in ("&", "let") and s.beat == len(self.ts.beats()) - 1]
                if last:
                    s = last[-1]
                    bar.hits.pop((s.pos, "hihat"), None)
                    bar.add(s.pos, "hihat_open", v[3])
                    for h in list(bar.hits.values()):  # nothing else on the hat until it closes
                        if h.inst == "hihat" and s.pos < h.pos:
                            del bar.hits[(h.pos, h.inst)]

        # Hi-hat foot.
        pedal = st.pedal_hat if (cymbal == "ride" or inst == "ride") else "none"
        if pedal == "2&4" and not self.beginner:
            for s in self.steps:
                if s.level == "1" and s.beat % 2 == 1:
                    bar.add(s.pos, "hihat_pedal", 70)

        if self.style.key == "bossa":
            self._bossa(bar, v)
        if self.style.backbeat == "one_drop" and spec.feel != "half_time":
            for s in self.steps:
                if s.level == "1" and s.beat in self.backbeats:
                    bar.add(s.pos, "kick", v[2])
        return bar

    def _half(self) -> set[int]:
        n = len(self.ts.beats())
        return {n // 2} if n > 1 else {0}

    def kick(self, role: str, complexity: float, backbeats: set[int], double_time: bool) -> set[Step]:
        st, spec = self.style, self.spec
        n = len(self.ts.beats())
        core = {"1": {0}, "1&3": {b for b in range(0, n, 2) if b not in backbeats} | {0},
                "four": set(range(n)), "none": set()}[st.kick_core]
        if double_time:
            core = set(range(n))
        chosen = {s for s in self.steps if s.level == "1" and s.beat in core}
        double = spec.double_bass if spec.double_bass is not None else (st.double_bass and role == "high")
        if double and not self.beginner:
            levels = ("1", "e", "&", "a") if self.advanced and not self.triplet else ("1", "&", "let", "trip")
            return chosen | {s for s in self.steps if s.level in levels}
        if st.kick_core == "four" or double_time:
            return chosen
        sync = spec.syncopation if spec.syncopation is not None else 0.5
        scale = (0.2 + 1.4 * complexity) * (0.4 + 1.2 * sync)
        draws = self.draws("kick", "breakdown" if role == "breakdown" else "main")
        for k, s in enumerate(self.steps):
            if s in chosen or (s.level == "1" and s.beat in backbeats):
                continue
            if s.level in ("&", "let"):
                p = st.kick_offbeats
            elif s.level in ("e", "a", "trip"):
                p = 0.0 if self.beginner else st.kick_16ths
            else:
                p = 0.25
            if s.slot in st.kick_favorites:
                p *= 1.8
            if role == "intro":
                p *= 0.5
            if draws[k] < min(0.9, p * scale):
                chosen.add(s)
        return self._thin(chosen, backbeats)

    def kick_variation(self, section_index: int, backbeats: set[int]) -> set[Step]:
        r = self.rng("variation", "kick", section_index)
        options = [s for s in self.steps if s.level in ("&", "a", "let") and s.beat == len(self.ts.beats()) - 1
                   or s.slot in self.style.kick_favorites]
        options = [s for s in options if not (s.level == "1" and s.beat in backbeats)]
        if self.beginner:
            options = [s for s in options if s.level in ("&", "let")]
        return {r.choice(options)} if options else set()

    def _thin(self, chosen: set[Step], backbeats: set[int]) -> set[Step]:
        """No more than two kicks in a row on adjacent 16ths, except for advanced players."""
        if self.advanced:
            return chosen
        order = sorted(chosen, key=lambda s: s.pos)
        out: list[Step] = []
        idx = {s: k for k, s in enumerate(self.steps)}
        for s in order:
            if len(out) >= 2 and idx[out[-1]] == idx[s] - 1 and idx[out[-2]] == idx[s] - 2:
                continue
            out.append(s)
        return set(out)

    def _bossa(self, bar: Bar, v) -> None:
        """Bossa nova: kick on 1 and the "a" of 2 (and 3, 4), cross-stick on the clave."""
        bar.remove(lambda h: h.inst in ("kick", "snare", "cross_stick"))
        if self.ts.num != 4 or self.ts.den != 4 or self.triplet:
            return
        q = Fraction(1, 4)
        for b in range(4):
            bar.add(b * q, "kick", v[2] - 10)
            bar.add(b * q + Fraction(3, 16), "kick", v[2] - 20)
        for p in (Fraction(0), Fraction(3, 16), Fraction(6, 16), Fraction(10, 16), Fraction(13, 16)):
            bar.add(p, "cross_stick", v[1] - 10)

    # ---- fills, crashes and endings --------------------------------------
    def fill(self, bar: Bar, start_beat: int, key: str, *, build: bool = False) -> None:
        """Replace the hands (and most kicks) from `start_beat` to the end of the bar with a fill."""
        beats = self.ts.beats()
        if start_beat >= len(beats):
            return
        r = self.rng("fills", key)
        t0 = beats[start_beat][0]
        bar.remove(lambda h: h.pos >= t0)
        rate = 2 if self.beginner else self.style.fill_rate
        if self.advanced and rate == 4 and r.random() < 0.35:
            rate = 6
        if build:
            rate = 2 if self.beginner else 4
        voice_mode = "snare" if build else self.spec.fill_voice
        voices = list(self.style.fill_voices)
        toms = [x for x in voices if x != "snare"] or ["tom1", "tom2", "floor_tom"]
        positions: list[tuple[Fraction, int]] = []  # (pos, beat index within the fill)
        for b in range(start_beat, len(beats)):
            start, length = beats[b]
            eighths = int(length / Fraction(1, 8))
            per = rate
            if eighths == 3:  # a dotted-quarter beat: 8ths (3) or 16ths (6)
                per = 3 if rate in (2, 3) else 6
            elif rate == 6 and eighths == 2 and r.random() < 0.5:
                per = 4
            cells = {2: [(1, 1)], 3: [(1, 1, 1), (1, 0, 1)], 4: [(1, 1, 1, 1), (1, 1, 1, 1), (1, 0, 1, 1), (1, 1, 0, 1)],
                     6: [(1,) * 6]}.get(per, [(1,) * per])
            cell = cells[0] if build else r.choice(cells)
            for k, on in enumerate(cell):
                if on:
                    positions.append((start + k * length / per, b - start_beat))
        n_beats = len(beats) - start_beat
        total = len(positions)
        flam_beats = self.advanced and not build and r.random() < 0.4
        for k, (pos, beat) in enumerate(positions):
            if voice_mode == "snare":
                inst = "snare"
            elif voice_mode == "mixed":
                inst = "snare" if k < total // 2 else toms[min(len(toms) - 1, (k - total // 2) * len(toms) // max(1, total - total // 2))]
            else:
                seq = (["snare"] if n_beats > 1 else []) + toms
                inst = seq[min(len(seq) - 1, k * len(seq) // max(1, total))]
            crescendo = int(self.v[1] - 18 + 24 * (k / max(1, total - 1)))
            first_of_beat = k == 0 or positions[k - 1][1] != beat
            accent = first_of_beat and (self.energy == "high" or build) and not self.beginner
            flam = flam_beats and first_of_beat and inst != "snare"
            bar.add(pos, inst, crescendo, accent=accent, flam=flam)
            if first_of_beat and (beat == 0 or self.energy == "high"):
                bar.add(pos, "kick", self.v[2])

    def crash(self, bar: Bar) -> None:
        bar.remove(lambda h: h.pos == 0 and h.inst in HAND_CYMBALS)
        bar.add(Fraction(0), "crash", self.v[0])
        bar.add(Fraction(0), "kick", self.v[2])

    def ending_bar(self, kind: str) -> Bar:
        bar = Bar(self.ts)
        v = self.v
        bar.add(Fraction(0), "crash", v[0], accent=True, choke=kind == "stop")
        bar.add(Fraction(0), "kick", v[2])
        if kind == "dramatic":
            beats = self.ts.beats()
            hits = [beats[len(beats) // 2][0] - (Fraction(1, 8) if len(beats) > 2 else 0), beats[-1][0]]
            for k, p in enumerate(sorted(set(hits))):
                if p <= 0:
                    continue
                last = k == len(hits) - 1
                bar.add(p, "crash", v[0], accent=True, choke=last)
                bar.add(p, "snare", v[1], accent=True)
                bar.add(p, "kick", v[2])
        return bar

    # ---- the arrangement ----------------------------------------------------
    def fill_schedule(self, sections: list[Section], ending: str) -> dict[int, int]:
        """bar index -> first beat of the fill in that bar (0 = a whole-bar fill)."""
        spec, n_bars = self.spec, self.spec.bars
        n_beats = len(self.ts.beats())
        out: dict[int, int] = {}
        if spec.fill_every == 0 or n_bars < 2:
            return out
        if spec.fill_every:
            ends = list(range(spec.fill_every - 1, n_bars, spec.fill_every))
        else:
            phrase = self.style.phrase
            ends = [i for i in range(phrase - 1, n_bars, phrase)]
            ends += [s.first + s.bars - 1 for s in sections]
        ends = sorted(set(ends))
        last_music = n_bars - 1 if ending in ("none",) else n_bars - 2
        for end in ends:
            if end > last_music:
                continue
            major = (end + 1) % 8 == 0 or any(end == s.first + s.bars - 1 for s in sections[:-1]) or end == last_music
            beats = spec.fill_beats
            if beats is None:
                beats = (n_beats if (major and not self.beginner) else max(1, n_beats // 2))
                if n_bars <= 4 and end == n_bars - 1:
                    beats = max(1, n_beats // 2)
            beats = max(1, beats)
            k, remaining = end, beats
            while remaining > 0 and k >= 0:
                take = min(n_beats, remaining)
                out[k] = n_beats - take
                remaining -= take
                k -= 1
        if ending in ("fill_crash", "dramatic") and n_bars >= 2 and (n_bars - 2) not in out:
            out[n_bars - 2] = 0 if not self.beginner else max(1, n_beats // 2)
        return out

    def score(self) -> Score:
        spec, st = self.spec, self.style
        sections = plan_sections(spec, st)
        ending = spec.resolved_ending()
        if spec.bars < 2:
            ending = "none"
        fills = self.fill_schedule(sections, ending)
        measures: list[Measure] = []
        after_fill = False
        for si, sec in enumerate(sections):
            phrase = min(st.phrase, sec.bars) if sec.bars >= 2 else 1
            for j in range(sec.bars):
                i = sec.first + j
                is_last = i == spec.bars - 1
                if is_last and ending in ("crash", "fill_crash", "stop", "dramatic"):
                    bar = self.ending_bar(ending)
                else:
                    role = sec.role
                    if role == "build":
                        bar = Bar(self.ts)
                        self.fill(bar, 0, f"build:{i}", build=True)
                        if j == sec.bars - 1 or i in fills:
                            bar = self.groove("main", j % phrase, phrase, si, i)
                            self.fill(bar, 0, f"{i}")
                    else:
                        bar = self.groove(role, j % phrase, phrase, si, i)
                        if i in fills:
                            start = fills[i]
                            two_bar_lead = (i + 1) in fills and fills.get(i + 1) == 0 and start == 0 and \
                                (i + 2) not in fills
                            self.fill(bar, start, f"{i}", build=two_bar_lead)
                    opening = i == 0 and self.energy != "low"
                    crash_here = (spec.crashes != "none" and j == 0 and (si > 0 or opening)) or after_fill or (
                        spec.crashes == "phrases" and j % phrase == 0)
                    if crash_here and not (i in fills and fills[i] == 0):
                        self.crash(bar)
                after_fill = i in fills
                m = Measure(time_sig=self.ts, hits=self._playable(bar))
                if j == 0:
                    m.section = sec.name
                measures.append(m)
        measures[0].tempo = spec.resolved_bpm()
        measures[0].tempo_text = st.label if st.label.lower() not in (spec.title or "").lower() else None
        title = spec.title or f"{st.label} Beat"
        score = Score(measures=measures, title=title, chart_type="original_beat", status="entered", rights="original",
                      source="generated from a description")
        score.analysis = {"input": "generator", "generator": {
            "engine": ENGINE_VERSION, "spec": spec.to_dict(), "ending": ending,
            "sections": [{"name": s.name, "role": s.role, "first_bar": s.first + 1, "bars": s.bars} for s in sections],
            "fills": sorted(i + 1 for i in fills), "feel": "triplet" if self.triplet else (spec.feel or "straight")}}
        return score

    def _playable(self, bar: Bar) -> list[Hit]:
        """Never three hands at once: drop the cymbal hand, then ghost notes."""
        by_pos: dict[Fraction, list[Hit]] = {}
        for h in bar.hits.values():
            by_pos.setdefault(h.pos, []).append(h)
        for pos, hs in by_pos.items():
            def hands(hs=hs):
                return sum(2 if (h.flam or h.drag) else 1 for h in hs if not self.kit.is_foot(h.inst))
            for drop in (lambda h: h.ghost, lambda h: h.inst in HAND_CYMBALS and h.inst != "crash",
                         lambda h: h.inst in HAND_CYMBALS):
                while hands() > 2 and any(drop(h) for h in hs):
                    victim = next(h for h in hs if drop(h))
                    hs.remove(victim)
                    del bar.hits[(victim.pos, victim.inst)]
            if hands() > 2:  # a flam with something else: keep the flam
                for h in [h for h in hs if not (h.flam or h.drag) and not self.kit.is_foot(h.inst)]:
                    del bar.hits[(h.pos, h.inst)]
            if "hihat_pedal" in {h.inst for h in hs} and {"hihat_open", "hihat_half"} & {h.inst for h in hs}:
                del bar.hits[(pos, "hihat_pedal")]
        return bar.sorted()


def generate(spec: BeatSpec, kit: Kit = DEFAULT_KIT) -> Score:
    return Engine(spec, kit).score()
