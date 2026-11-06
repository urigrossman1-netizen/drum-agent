"""Practice versions: an easier chart made from a transcription.

A practice version holds only notes of the transcription, at their places: simplifying leaves
notes out and takes ornaments off; it never adds or moves a note. It's a chart of its own, for
working towards the real part, so it says on the page and in the PDF header that it isn't what
was played, and the transcription it came from stays as it is.

- Intermediate: no ghost notes, flams, drags or rolls; the time-keeping cymbal on the 8ths;
  kick, snare and toms on the 16ths (on the 8ths in a fill); the hi-hat foot on the beats.
- Beginner: the time-keeping cymbal on the 8ths (on the beats when that's too fast); kick, snare,
  toms and crashes on the beats; no accents, chokes or hi-hat foot.

A bar that was played never goes silent: if the rules leave nothing, its first strong strokes stay.
"""

from __future__ import annotations

from fractions import Fraction

from .kit import DEFAULT_KIT, FEET
from .model import Hit, Measure, Score

LEVELS = {"beginner": "practice_beginner", "intermediate": "practice_intermediate"}
BEAT, EIGHTH, SIXTEENTH, FINER = range(4)  # how strong a place in the bar is
FAST_BPM = 130  # above this a beginner's hi-hat plays the beats: 8ths get hard to keep even
TIME_KEEPING = frozenset({"hihat", "hihat_open", "hihat_half", "ride", "ride_bell"})
# Facts about the transcription's own strokes: not true of a version that leaves some out.
TRANSCRIPTION_ONLY = ("detected_onsets", "instrument_counts")


def place(m: Measure, pos: Fraction) -> int:
    """BEAT, EIGHTH, SIXTEENTH or FINER. A shuffled off-beat, written as the beat's last triplet,
    is the 8th it stands for; the middle triplet is finer. A pickup counts back from the barline."""
    at = pos + (m.time_sig.bar_length - m.actual_length if m.is_pickup else 0)
    for start, length in m.time_sig.beats():
        if at < start + length:
            into = at - start
            if into == 0:
                return BEAT
            if (into / Fraction(1, 8)).denominator == 1 or (length == Fraction(1, 4) and into == Fraction(1, 6)):
                return EIGHTH
            return SIXTEENTH if (into / Fraction(1, 16)).denominator == 1 else FINER
    return FINER


def _keeps(h: Hit, where: int, level: str, tempo: float, fill: bool) -> bool:
    beginner = level == "beginner"
    if h.ghost:
        return False
    if h.inst in FEET and DEFAULT_KIT[h.inst].family == "hihat":
        return not beginner and where == BEAT
    if h.inst in TIME_KEEPING:
        return where == BEAT if beginner and tempo > FAST_BPM else where <= EIGHTH
    if beginner:
        return where == BEAT
    if DEFAULT_KIT[h.inst].family == "cymbal":
        return where <= EIGHTH
    return where <= (EIGHTH if fill else SIXTEENTH)


def _first_strong(m: Measure) -> list[Hit]:
    """The bar's earliest strokes on its strongest place."""
    played = [h for h in m.hits if not h.ghost] or m.hits
    strongest = min(place(m, h.pos) for h in played)
    strong = [h for h in played if place(m, h.pos) == strongest]
    first = min(h.pos for h in strong)
    return [h for h in strong if h.pos == first]


def _plain(h: Hit, level: str) -> Hit:
    h.ghost = h.flam = h.drag = False
    h.roll = None
    if level == "beginner":
        h.accent = h.choke = False
    return h


def simplify(score: Score, level: str) -> Score:
    """A practice version of `score` at `level` (a new score; `score` isn't changed)."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {sorted(LEVELS)}")
    if score.status == "simplified":
        raise ValueError("this is already a practice version: make one from the transcription")
    out = Score.from_dict(score.to_dict())
    total = sum(len(m.hits) for m in out.measures)
    for i, m in enumerate(out.measures):
        tempo = score.tempo_at(i)
        kept = [h for h in m.hits if _keeps(h, place(m, h.pos), level, tempo, m.cue == "Fill")]
        m.hits = [_plain(h, level) for h in (kept or (_first_strong(m) if m.hits else []))]
        m.uncertain = False  # reviewing belongs to the transcription: a fix here wouldn't reach it
    out.chart_type = LEVELS[level]
    out.status = "simplified"
    out.analysis = {k: v for k, v in (out.analysis or {}).items() if k not in TRANSCRIPTION_ONLY}
    out.analysis["simplified"] = {"level": level, "kept": sum(len(m.hits) for m in out.measures), "of": total}
    return out
