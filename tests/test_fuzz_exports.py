"""Property-based fuzzing of the engraving/export chain on random valid scores.

A seeded generator (``random.Random(seed)``, no external libraries) builds
scores across 4/4, 3/4, 2/4, 6/8, 12/8, 5/4 and 7/8 (2+2+3 and 3+2+2) with:

* a random grid per beat: straight 8ths/16ths/32nds, 8th triplets and
  sextuplets in simple beats; 8ths, 16ths, duplets and quadruplets in
  compound (dotted) beats;
* random instruments from ``DEFAULT_KIT`` (at most two hands and two feet,
  one stroke per drum/cymbal at a time), accents, ghosts, flams, drags,
  chokes, open/half-open/closed hi-hat, and rolls that never overlap a later
  stroke in the same voice or cross the barline;
* meter and tempo changes, tempo texts, section labels, a pickup (first bar
  only), uncertain bars, empty bars, runs of identical bars and repeated
  phrases (so the layout compresses some of them), and near-repeats that
  must stay written out.

Every generated score passes ``Score.validate()``; a rejection is a generator
bug. Pure-Python properties run over thousands of bars (spelling tiles the
bar, every stroke appears once, beams/tuplets/ties are well formed, the layout
plan expands back to the score, MusicXML and MIDI read back as the IR). The
LilyPond test engraves a few long random scores through ``export_all`` with
full verification, which raises if LilyPond's MIDI, the MusicXML or our MIDI
disagree with the IR, if the MusicXML is schema-invalid, or if LilyPond warns.
"""

import copy
import random
import re
from collections import Counter
from fractions import Fraction as F

import pytest

from conftest import needs_lilypond
from drum_agent.export.lilypond import to_lilypond
from drum_agent.export.midi import write_midi
from drum_agent.export.musicxml import to_musicxml
from drum_agent.kit import DEFAULT_KIT
from drum_agent.layout import plan_layout
from drum_agent.model import CHART_TYPES, RIGHTS, STATUSES, Hit, Measure, Score, TimeSig, is_power_of_two_fraction
from drum_agent.rhythm import assign_voices, check_tokens, spell_measure
from drum_agent.verify import expected_midi_keys, midi_events, musicxml_events, validate_musicxml

# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

METERS = [
    TimeSig(4, 4), TimeSig(3, 4), TimeSig(2, 4), TimeSig(6, 8), TimeSig(12, 8), TimeSig(5, 4),
    TimeSig(7, 8, (2, 2, 3)), TimeSig(7, 8, (3, 2, 2)),
]
METER_WEIGHTS = [5, 2, 1, 2, 1, 1, 1, 1]

# Slots per beat and weight. Simple beats: quarter, 8ths, 16ths, 32nds, 8th triplets,
# sextuplets. Compound beats: dotted quarter, 8ths, 16ths, duplets, quadruplets.
BINARY_GRIDS = {1: 2, 2: 4, 4: 5, 8: 1, 3: 3, 6: 1}
TERNARY_GRIDS = {1: 2, 3: 5, 6: 3, 2: 2, 4: 1}

HAND_WEIGHTS = {
    "hihat": 10, "hihat_open": 3, "hihat_half": 1, "ride": 4, "ride_bell": 1, "crash": 2, "crash2": 1,
    "china": 1, "splash": 1, "snare": 8, "cross_stick": 1, "rimshot": 1, "tom1": 2, "tom2": 2,
    "floor_tom": 2, "floor_tom2": 1, "cowbell": 1,
}
FOOT_WEIGHTS = {"kick": 8, "kick2": 1, "hihat_pedal": 2, "hihat_splash": 1}
# One stroke per physical drum/cymbal at a time.
EXCLUSIVE = [{"snare", "cross_stick", "rimshot"}, {"ride", "ride_bell"},
             {"hihat", "hihat_open", "hihat_half"}, {"hihat_pedal", "hihat_splash"}]
ROLLABLE = ("snare", "tom1", "tom2", "floor_tom", "floor_tom2", "crash", "ride")
GRACEABLE = ("snare", "tom1", "tom2", "floor_tom", "floor_tom2", "rimshot")
CHOKEABLE = ("crash", "crash2", "china", "splash")
SECTIONS = ["Intro", "Verse 1", "Pre-Chorus", "Chorus", "Bridge", "Solo (8 bars)", "Outro", "A", "B",
            'Break "stop"', "Fill & Out", "Coda"]
TEMPO_TEXTS = ["Swing", "Half-time feel", "Straight 8ths", "Double-time"]


def voice_of(inst: str) -> int:
    return DEFAULT_KIT[inst].voice


def is_ternary(length: F) -> bool:
    return is_power_of_two_fraction(length / 3)


class Gen:
    """Random valid scores. `stats` records what was generated (for the coverage test)."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.seed = seed
        self.stats: Counter = Counter()

    def _weighted(self, table: dict):
        return self.rng.choices(list(table), list(table.values()))[0]

    def _pick(self, table: dict, k: int) -> list[str]:
        out: list[str] = []
        for _ in range(4 * k):
            if len(out) == k:
                break
            inst = self._weighted(table)
            if inst in out or any(inst in g and g & set(out) for g in EXCLUSIVE):
                continue
            out.append(inst)
        return out

    def _hit(self, pos: F, inst: str) -> Hit:
        rng = self.rng
        h = Hit(pos, inst)
        r = rng.random()
        if r < 0.12:
            h.accent = True
        elif r < 0.2:
            h.ghost = True
        if inst in GRACEABLE:
            r = rng.random()
            if r < 0.07:
                h.flam = True
            elif r < 0.11:
                h.drag = True
        if inst in CHOKEABLE and rng.random() < 0.12:
            h.choke = True
        if rng.random() < 0.2:
            h.velocity = rng.randint(1, 127)
        return h

    def bar(self, ts: TimeSig, pickup: F | None = None) -> Measure:
        rng = self.rng
        bar_len = ts.bar_length
        density = rng.choice([0.15, 0.35, 0.6, 0.85, 1.0])
        hits: dict[tuple[F, str], Hit] = {}
        slots: list[F] = []
        for start, length in ts.beats():
            n = self._weighted(TERNARY_GRIDS if is_ternary(length) else BINARY_GRIDS)
            self.stats[("grid", "ternary" if is_ternary(length) else "binary", n)] += 1
            for k in range(n):
                pos = start + length * F(k, n)
                slots.append(pos)
                if rng.random() > density:
                    continue
                nh = rng.choices([0, 1, 2], [2, 6, 2])[0]
                nf = rng.choices([0, 1, 2], [5, 4, 1])[0]
                if nh + nf == 0:
                    nh = 1
                for inst in self._pick(HAND_WEIGHTS, nh) + self._pick(FOOT_WEIGHTS, nf):
                    hits[(pos, inst)] = self._hit(pos, inst)
        rolls: list[tuple[F, F]] = []
        for _ in range(rng.choice([0, 0, 0, 1, 1, 2])):
            free = [p for p in slots if not any(s < p < e for s, e in rolls)]
            start = rng.choice(free)
            later = [p for p in slots if p > start] + [bar_len]
            later = later[:rng.choice([1, 2, 3, 4, 6, 12])]
            end = rng.choice(later)
            # Both hands are rolling: nothing else the hands play may start inside the roll.
            for key in [k for k in hits if not DEFAULT_KIT.is_foot(k[1]) and start <= k[0] < end]:
                del hits[key]
            rolls = [(s, e) for s, e in rolls if not start <= s < end] + [(start, end)]
            h = self._hit(start, rng.choice(ROLLABLE))
            h.choke = False
            h.roll = end - start
            hits[(start, h.inst)] = h
        length = None
        if pickup is not None:
            offset = bar_len - pickup
            hits = {(p - offset, i): h for (p, i), h in hits.items() if p >= offset}
            for h in hits.values():
                h.pos -= offset
            length = pickup
        m = Measure(ts, sorted(hits.values(), key=lambda h: (h.pos, h.inst)), length=length)
        self._count(m)
        return m

    def _count(self, m: Measure) -> None:
        self.stats[("meter", str(m.time_sig), m.time_sig.beat_groups)] += 1
        if not m.hits:
            self.stats["empty bar"] += 1
        for h in m.hits:
            self.stats[("inst", h.inst)] += 1
            for flag in ("accent", "ghost", "flam", "drag", "choke"):
                if getattr(h, flag):
                    self.stats[flag] += 1
            if h.roll is not None:
                self.stats["roll"] += 1
                if any(h.pos <= b < h.pos + h.roll for b, _ in m.time_sig.beats() if b > h.pos):
                    self.stats["roll across a beat"] += 1

    @staticmethod
    def clean_copy(m: Measure) -> Measure:
        return Measure(m.time_sig, copy.deepcopy(m.hits), length=m.length)

    def score(self, n_bars: int = 40) -> Score:
        rng = self.rng
        ts = rng.choices(METERS, METER_WEIGHTS)[0]
        measures: list[Measure] = []
        if rng.random() < 0.4:
            unit = rng.choice([F(1, 4), F(1, 8), F(1, 16)])
            lengths = [unit * k for k in range(1, 16) if unit * k < ts.bar_length]
            pickup = self.bar(ts, pickup=rng.choice(lengths))
            pickup.tempo = rng.choice([None, 72.0, 96.5])
            pickup.section = rng.choice([None, "Pickup"])
            measures.append(pickup)
            self.stats["pickup"] += 1
        while len(measures) < n_bars:
            if rng.random() < 0.3:
                ts = rng.choices(METERS, METER_WEIGHTS)[0]
            kind = rng.choices(["fresh", "percent", "phrase", "empty", "variant"], [5, 2, 1.5, 1, 1])[0]
            if kind == "variant" and not (measures and measures[-1].time_sig == ts
                                          and not measures[-1].is_pickup and measures[-1].hits):
                kind = "fresh"
            if kind == "fresh":
                block = [self.bar(ts)]
            elif kind == "empty":
                block = [Measure(ts) for _ in range(rng.randint(1, 2))]
                for m in block:
                    self._count(m)
            elif kind == "percent":
                first = self.bar(ts)
                block = [first] + [self.clean_copy(first) for _ in range(rng.randint(1, 4))]
            elif kind == "phrase":
                phrase = [self.bar(ts) for _ in range(rng.choice([2, 2, 4]))]
                block = list(phrase)
                for _ in range(rng.choice([1, 1, 2])):
                    block += [self.clean_copy(m) for m in phrase]
            else:  # a near-repeat (one stroke dropped or re-articulated): must stay written out
                block = [self.clean_copy(measures[-1])]
                h = rng.choice(block[0].hits)
                if h.ghost or rng.random() < 0.5:
                    block[0].hits.remove(h)
                else:
                    h.accent = not h.accent
                self._count(block[0])
            self.stats[("block", kind)] += 1
            head = block[0]
            if rng.random() < 0.2 or not measures:
                head.tempo = rng.choice([60.0, 84.0, 96.5, 120.0, 132.0, 168.0, 210.0, rng.randint(40, 240)])
                self.stats["tempo"] += 1
            if rng.random() < 0.06:
                head.tempo_text = rng.choice(TEMPO_TEXTS)
                self.stats["tempo text"] += 1
            if rng.random() < 0.25:
                head.section = rng.choice(SECTIONS)
                self.stats["section"] += 1
            if rng.random() < 0.05:
                head.uncertain = True
                head.notes = ["fuzz: low-confidence bar"]
                self.stats["uncertain"] += 1
            measures += block
        status = rng.choice(list(STATUSES))
        score = Score(measures, title=f"Fuzz {self.seed}", artist=rng.choice([None, "Random Band"]),
                      transcriber=rng.choice([None, "pytest"]), chart_type=rng.choice(list(CHART_TYPES)),
                      status=status, rights=rng.choice([None, *RIGHTS]))
        score.validate()  # a rejection here is a generator bug
        return score


def random_bars(seed: int, ts: TimeSig, n: int) -> list[Measure]:
    g = Gen(seed)
    out = []
    for k in range(n):
        if k % 5 == 4:
            unit = g.rng.choice([F(1, 8), F(1, 16)])
            lengths = [unit * j for j in range(1, 24) if unit * j < ts.bar_length]
            out.append(g.bar(ts, pickup=g.rng.choice(lengths)))
        else:
            out.append(g.bar(ts))
    return out


# ---------------------------------------------------------------------------
# Spelling invariants (NOTATION_SPEC §4)
# ---------------------------------------------------------------------------

def assert_spelling(m: Measure) -> None:
    """Check the spelled tokens of one bar against the notation rules."""
    ts = m.time_sig
    offset = ts.bar_length - m.actual_length
    beats = [(s - offset, l) for s, l in ts.beats() if s + l > offset]
    bounds = {s for s, _ in beats if s > 0} | {m.actual_length}
    beat_starts = {s for s, _ in beats if s >= 0}
    halves = set(ts.half_bar_spans() or []) if not offset else set()
    sm = spell_measure(m)
    by_voice = assign_voices(m)
    assert sorted(id(h) for v in by_voice.values() for h in v) == sorted(id(h) for h in m.hits)
    for h in by_voice[1]:  # only rolls under which the kick plays leave their voice
        assert voice_of(h.inst) == 1 or h.roll is not None
    if not m.hits:
        assert sm.shared_rest and not sm.voices[2]
    else:
        assert not sm.shared_rest
    for v in (1, 2):
        tokens = sm.voices[v]
        hits = by_voice[v]
        if not tokens:
            assert v == 2 and not m.hits
            continue
        check_tokens(tokens, m)
        ctx = f"{v=} {m.to_dict()} -> {tokens}"
        if not hits:
            assert all(t.kind != "note" for t in tokens), ctx
            if not m.is_pickup:
                assert [t.kind for t in tokens] == ["measure_rest"], ctx
            continue
        assert all(t.kind in ("note", "rest") for t in tokens), ctx
        onsets = sorted({h.pos for h in hits})
        # Every stroke is written exactly once, on a note starting at its position.
        written = [(h.pos, h.inst) for t in tokens if t.kind == "note" and not t.tie_stop for h in t.hits]
        assert sorted(written) == sorted((h.pos, h.inst) for h in hits), ctx
        for t in tokens:
            assert t.dots in (0, 1) and is_power_of_two_fraction(t.value), ctx
            ratio = F(t.tuplet[1], t.tuplet[0]) if t.tuplet else F(1)
            assert t.written * ratio == t.dur, f"written value does not match duration: {t} in {ctx}"
            end = t.pos + t.dur
            crosses = [b for b in bounds if t.pos < b < end]
            if t.kind == "rest":
                assert not t.hits, ctx
                if crosses and not t.tuplet:
                    assert (t.pos, t.dur) in halves, f"rest crosses a beat: {t} in {ctx}"
                if t.dots:  # simple meter has no dotted rests; only whole ternary beats/half bars
                    assert is_ternary(t.dur) and ((t.pos, t.dur) in beats or (t.pos, t.dur) in halves), ctx
                continue
            assert t.hits and all(any(h is x for x in by_voice[v]) for h in t.hits), ctx
            if not t.tie_stop:
                assert all(h.pos == t.pos for h in t.hits), ctx
            if t.is_roll:
                continue
            assert not t.tie_start and not t.tie_stop, f"drum notes are never tied except rolls: {ctx}"
            nxt = next((p for p in onsets if p > t.pos), m.actual_length)
            assert end <= nxt, f"note overlaps the next onset: {t} in {ctx}"
            if not t.tuplet:
                assert not crosses, f"note crosses a beat: {t} in {ctx}"
        # Ties link consecutive pieces of one roll, and the pieces add up to the roll.
        for i, t in enumerate(tokens):
            if t.tie_start:
                assert i + 1 < len(tokens) and tokens[i + 1].tie_stop, ctx
                assert [h.key() for h in tokens[i + 1].hits] == [h.key() for h in t.hits], ctx
            if t.tie_stop:
                assert i > 0 and tokens[i - 1].tie_start, ctx
            if t.kind == "note" and not t.tie_stop and t.is_roll:
                roll = {h.roll for h in t.hits if h.roll is not None}
                assert len(roll) == 1, ctx
                total, j = t.dur, i
                while tokens[j].tie_start:
                    j += 1
                    total += tokens[j].dur
                assert total == roll.pop(), f"roll pieces do not add up to the roll: {ctx}"
        # Tuplet brackets: well nested, one ratio, a whole beat (or the half bar for quarter triplets).
        open_bracket = None
        for t in tokens:
            if t.tuplet_start:
                assert open_bracket is None and t.tuplet, ctx
                open_bracket = [t]
            elif open_bracket is not None:
                open_bracket.append(t)
            else:
                assert t.tuplet is None, f"tuplet note outside a bracket: {ctx}"
            if open_bracket is not None:
                assert t.tuplet == open_bracket[0].tuplet, ctx
            if t.tuplet_stop:
                assert open_bracket is not None, ctx
                start, span = open_bracket[0].pos, sum(x.dur for x in open_bracket)
                if not offset:
                    assert start in beat_starts, ctx
                    assert (start, span) in beats or ((start, span) in halves and t.tuplet == (3, 2)), ctx
                open_bracket = None
        assert open_bracket is None, ctx
        # Beams: balanced per level, start and end on notes, stay within a beat
        # (4/4 may join two beats of plain 8ths in one half bar), hooks only on notes.
        open_levels: dict[int, list] = {}
        for t in tokens:
            for level, state in t.beams.items():
                assert t.value <= F(1, 8), ctx
                if level >= 2:
                    assert t.kind == "note" and t.beam_levels >= level, ctx
                if state == "begin":
                    assert level not in open_levels and t.kind == "note", ctx
                    open_levels[level] = [t]
                elif state in ("continue", "end"):
                    assert level in open_levels, ctx
                    open_levels[level].append(t)
                    if state == "end":
                        group = open_levels.pop(level)
                        assert t.kind == "note", ctx
                        if level == 1:
                            assert_beam_group(group, ts, offset, ctx)
                else:
                    assert state in ("forward hook", "backward hook") and level >= 2, ctx
            for level, group in open_levels.items():
                if group[-1] is not t:
                    assert level != 1, f"unbeamed token inside a beam: {ctx}"
        assert not open_levels, ctx
        # Spec §4.5: two or more short notes in one beat with nothing longer between are beamed.
        for seg in {t.segment for t in tokens}:
            run: list = []
            for t in [x for x in tokens if x.segment == seg] + [None]:
                if t is not None and t.value <= F(1, 8):
                    run.append(t)
                    continue
                notes = [x for x in run if x.kind == "note"]
                if len(notes) >= 2:
                    assert all(1 in x.beams for x in notes), f"short notes left unbeamed: {ctx}"
                run = []


def assert_beam_group(group: list, ts: TimeSig, offset: F, ctx: str) -> None:
    assert sum(1 for t in group if t.kind == "note") >= 2, ctx
    if len({t.segment for t in group}) > 1:
        assert (ts.num, ts.den) == (4, 4), f"beam crosses a beat: {ctx}"
        # Half bars are full-bar coordinates (a pickup is the tail of a full bar).
        assert len(group) == 4 and group[0].pos + offset in (0, F(1, 2)), ctx
        assert all(t.kind == "note" and t.value == F(1, 8) and not t.dots and not t.tuplet for t in group), ctx


@pytest.mark.parametrize("ts", METERS, ids=[f"{t}{'-' + '+'.join(map(str, t.beat_groups)) if t.beat_groups else ''}"
                                             for t in METERS])
def test_random_bars_spell_correctly(ts):
    """~500 random bars per meter (every 5th a pickup): spelling invariants hold."""
    for seed in range(5):
        for m in random_bars(1000 * METERS.index(ts) + seed, ts, 100):
            assert_spelling(m)


# ---------------------------------------------------------------------------
# Layout and file round trips (no LilyPond needed)
# ---------------------------------------------------------------------------

PY_SEEDS = list(range(100, 124))
LILY_SEEDS = [7, 2024, 31337, 4242]


def assert_layout(score: Score, plan, mode: str) -> None:
    ms = score.measures
    assert plan.expand() == list(range(len(ms)))
    assert set(plan.printed_numbers) == set(range(len(ms)))
    bars = plan.bars
    assert bars[0].line_break and not bars[0].percent
    for k, b in enumerate(bars):
        if b.line_break:
            assert not b.percent, "a simile mark never starts a line"
        if b.percent:
            assert mode != "none"
            prev = bars[k - 1]
            assert not prev.volta_end and b.index == prev.index + 1
            assert ms[b.index].musical_signature() == ms[prev.index].musical_signature()
            assert ms[b.index].tempo is None and ms[b.index].section is None and not ms[b.index].uncertain
            assert ms[b.index].tempo_text is None and not ms[prev.index].uncertain
        if b.rest_run:  # a multi-bar rest: empty bars of one meter, marks only on the first
            assert mode != "none" and b.rest_run >= 2 and not b.in_rest and not b.percent
            run = bars[k:k + b.rest_run]
            assert [x.index for x in run] == list(range(b.index, b.index + b.rest_run))
            assert all(x.in_rest and not x.line_break and not x.percent for x in run[1:])
            for x in run:
                m = ms[x.index]
                assert not m.hits and not m.uncertain and not m.is_pickup
                assert str(m.time_sig) == str(ms[b.index].time_sig)
                if x is not b:
                    assert m.tempo is None and m.tempo_text is None and m.section is None
        elif b.in_rest:
            assert bars[k - 1].in_rest or bars[k - 1].rest_run
    k = 0
    while k < len(bars):
        if not bars[k].volta_start:
            k += 1
            continue
        assert mode == "auto"
        j = k
        while not bars[j].volta_end:
            j += 1
        phrase = [b.index for b in bars[k:j + 1]]
        times = bars[k].volta_times
        assert times >= 2 and bars[j].volta_times == times and len(phrase) in (2, 4, 8)
        assert not any(ms[idx].uncertain for idx in phrase)
        for t in range(1, times):
            for idx in phrase:
                copy_ = ms[idx + t * len(phrase)]
                assert copy_.musical_signature() == ms[idx].musical_signature()
                assert copy_.tempo is None and copy_.section is None and not copy_.uncertain
        k = j + 1


def test_random_scores_layout_reproduces_the_bars():
    """plan_layout(...).expand() is the score's bar sequence in every repeat mode; repeats are exact."""
    compressed = Counter()
    for seed in PY_SEEDS:
        score = Gen(seed).score()
        for mode in ("auto", "percent", "none"):
            for bpl in (2.0, 4.0, 6.0):
                plan = plan_layout(score, repeats=mode, bars_per_line=bpl)
                assert_layout(score, plan, mode)
                if mode == "auto":
                    compressed["percent"] += sum(b.percent for b in plan.bars)
                    compressed["volta"] += sum(b.volta_start for b in plan.bars)
                    compressed["rest"] += sum(b.rest_run > 0 for b in plan.bars)
        assert len(plan_layout(score, repeats="none").bars) == len(score.measures)
    assert compressed["percent"] > 20 and compressed["volta"] > 5 and compressed["rest"] > 0, compressed


def test_random_scores_musicxml_and_midi_match_the_ir(tmp_path):
    """MusicXML (schema-valid) and our MIDI read back as the IR; the LilyPond source builds."""
    for n, seed in enumerate(PY_SEEDS[:8]):
        score = Gen(seed).score()
        plan = plan_layout(score)
        xml = tmp_path / f"fuzz{seed}.musicxml"
        xml.write_text(to_musicxml(score, plan=plan))
        assert musicxml_events(xml) == score.event_list(), f"seed {seed}"
        if n < 3:  # schema validation is the slow part
            assert validate_musicxml(xml) == [], f"seed {seed}"
        mid = write_midi(score, tmp_path / f"fuzz{seed}.mid")
        assert midi_events(mid) == expected_midi_keys(score, expand_rolls=True, include_graces=True), f"seed {seed}"
        ly = to_lilypond(score, plan=plan)
        body = re.sub(r'"(\\.|[^"\\])*"', '""', ly)  # strings may contain braces
        assert body.count("{") == body.count("}"), f"seed {seed}: unbalanced braces in the .ly"
        # Each repeated phrase opens one volta in each of the three streams (global, up, down).
        assert ly.count("\\repeat volta") == 3 * sum(b.volta_start for b in plan.bars)
        again = Score.from_dict(score.to_dict())
        assert [m.musical_signature() for m in again.measures] == [m.musical_signature() for m in score.measures]
        assert again.event_list() == score.event_list()


def test_generator_covers_the_feature_space():
    """The fuzzer really exercises what it claims to (guards against a silently narrowed generator)."""
    stats: Counter = Counter()
    for seed in PY_SEEDS + LILY_SEEDS:
        g = Gen(seed)
        g.score()
        stats += g.stats
    for ts in METERS:
        assert stats[("meter", str(ts), ts.beat_groups)] > 0, ts
    for n in BINARY_GRIDS:
        assert stats[("grid", "binary", n)] > 0, n
    for n in TERNARY_GRIDS:
        assert stats[("grid", "ternary", n)] > 0, n
    for inst in DEFAULT_KIT.ids():
        assert stats[("inst", inst)] > 0, inst
    for feature in ("accent", "ghost", "flam", "drag", "choke", "roll", "roll across a beat", "pickup",
                    "tempo", "tempo text", "section", "uncertain", "empty bar"):
        assert stats[feature] > 0, feature
    for kind in ("fresh", "percent", "phrase", "empty", "variant"):
        assert stats[("block", kind)] > 0, kind


# ---------------------------------------------------------------------------
# Full engraving with LilyPond
# ---------------------------------------------------------------------------

def _export(score: Score, out):
    from drum_agent.pipeline import ExportOptions, export_all
    return export_all(score, out, "fuzz", options=ExportOptions())


def _minimize(score: Score, tmp_path) -> str:
    """Find the smallest failing piece (a single bar, else a pair of bars) of a failing score."""
    from drum_agent.export.render import RenderError
    from drum_agent.pipeline import ExportError

    def fails(i: int, j: int) -> str | None:
        ms = copy.deepcopy(score.measures[i:j])
        ms[0].tempo = score.tempo_at(i)
        try:
            _export(Score(ms, title="Minimal"), tmp_path / "min" / f"{i}-{j}")
        except (ExportError, RenderError, AssertionError, ValueError) as exc:
            return f"{type(exc).__name__}: {str(exc)[:1500]}"
        return None

    for width in (1, 2):
        for i in range(len(score.measures) - width + 1):
            err = fails(i, i + width)
            if err:
                bars = [m.to_dict() for m in score.measures[i:i + width]]
                return f"score bar(s) {i + 1}..{i + width} fail on their own: {bars}\n{err}"
    return "no single bar or pair of bars reproduces the failure"


@needs_lilypond
@pytest.mark.lilypond
@pytest.mark.parametrize("seed", LILY_SEEDS)
def test_random_score_engraves_and_all_formats_agree(seed, tmp_path):
    """~40 random bars engraved through export_all with full verification."""
    from drum_agent.export.render import RenderError
    from drum_agent.pipeline import ExportError

    score = Gen(seed).score(40)
    try:
        report = _export(score, tmp_path / "out")
    except (ExportError, RenderError) as exc:
        pytest.fail(f"seed {seed}: {type(exc).__name__}: {str(exc)[:3000]}\n--- minimized ---\n"
                    f"{_minimize(score, tmp_path)}")
    assert report.rendering_ok
    names = {c.name: c for c in report.comparisons}
    assert set(names) == {"engraved score (LilyPond MIDI)", "engraved score tempo map",
                          "MusicXML", "MusicXML articulations", "MusicXML meters",
                          "MIDI", "MIDI tempo map", "MIDI barlines"}
    assert names["MusicXML"].expected == len(score.event_list()) > 0
    assert not report.musicxml_errors
    lily_warnings = [w for w in report.warnings if w.startswith("LilyPond")]
    assert not lily_warnings, f"seed {seed}: {lily_warnings}\n--- minimized ---\n{_minimize(score, tmp_path)}"
    assert report.files["pdf"].stat().st_size > 1000
    assert any(k.startswith("png") for k in report.files)
