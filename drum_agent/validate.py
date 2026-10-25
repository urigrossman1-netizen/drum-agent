"""Chart validation: is the score musically and mathematically sound, and does it cover
the whole recording?

These checks look at the score itself (score.json), independently of the renderers;
`verify.py` separately proves the PDF, MusicXML and MIDI encode the same music. A chart
is complete only when both pass and no bar is flagged for review (see `chart_status`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fractions import Fraction

from .kit import DEFAULT_KIT, Kit
from .model import Score, ScoreError

MIN_BPM, MAX_BPM = 20.0, 400.0
MAX_GRID = 96  # finest position: a 1/96 note (32nd-note triplets); denominators must divide 2^a * 3
COVERAGE_TOLERANCE_S = 1.0  # strokes may fall this far outside the notated timeline
BAR_TIMING_TOLERANCE = 0.25  # a bar may run this much longer or shorter than its tempo says


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # "error" fails validation; "review" asks a person to listen


@dataclass
class Validation:
    checks: list[Check] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "error")

    @property
    def needs_review(self) -> bool:
        return any(not c.ok for c in self.checks if c.severity == "review")

    def to_dict(self) -> dict:
        return {"ok": self.ok, "needs_review": self.needs_review, "coverage": self.coverage,
                "checks": [asdict(c) for c in self.checks]}


def _grid_ok(pos: Fraction) -> bool:
    d = pos.denominator
    if MAX_GRID % 3 == 0 and d % 3 == 0:
        d //= 3
    return d & (d - 1) == 0 and pos.denominator <= MAX_GRID


def _bar_seconds(score: Score, i: int) -> float:
    m = score.measures[i]
    return float(m.actual_length) * 4 * 60.0 / score.tempo_at(i)


def validate_score(score: Score, kit: Kit = DEFAULT_KIT, audio_duration: float | None = None) -> Validation:
    v = Validation()
    ms = score.measures
    add = lambda *a, **k: v.checks.append(Check(*a, **k))
    if not ms:
        add("measures", False, "the chart has no measures")
        return v
    try:
        warnings = score.validate(kit)
        add("score structure", True, "the score file is well formed" + (f" ({len(warnings)} warning(s))" if warnings else ""))
    except ScoreError as e:
        add("score structure", False, str(e))

    bad_len = [i + 1 for i, m in enumerate(ms)
               if m.actual_length != m.time_sig.bar_length and not (i == 0 and m.is_pickup)]
    add("measure durations", not bad_len,
        f"{len(ms)} measures; each holds exactly its time signature" + (" (bar 1 is a pickup)" if ms[0].is_pickup else "")
        if not bad_len else f"bars {bad_len[:10]} are shorter or longer than their time signature")

    bad_pos, off_grid, dup = [], [], []
    for i, m in enumerate(ms):
        seen = set()
        for h in m.hits:
            if not (0 <= h.pos < m.actual_length):
                bad_pos.append(i + 1)
            elif not _grid_ok(h.pos):
                off_grid.append(i + 1)
            if (h.pos, h.inst) in seen:
                dup.append(i + 1)
            seen.add((h.pos, h.inst))
    add("event positions", not bad_pos, "every stroke lies inside its bar" if not bad_pos
        else f"strokes outside their bar in bars {sorted(set(bad_pos))[:10]}")
    add("subdivisions", not off_grid, "every stroke is on a 32nd-note or triplet grid position" if not off_grid
        else f"strokes off the notation grid in bars {sorted(set(off_grid))[:10]}")
    add("duplicate strokes", not dup, "no instrument is struck twice at the same position" if not dup
        else f"duplicate strokes in bars {sorted(set(dup))[:10]}")

    unknown = sorted({h.inst for m in ms for h in m.hits if h.inst not in kit})
    add("instruments", not unknown, "every instrument is in the kit (" + ", ".join(
        sorted({h.inst for m in ms for h in m.hits})) + ")" if not unknown else f"unknown instruments: {unknown}")

    tempi = [(i + 1, score.tempo_at(i)) for i in range(len(ms)) if i == 0 or ms[i].tempo is not None]
    bad_tempo = [(b, t) for b, t in tempi if not (MIN_BPM <= t <= MAX_BPM)]
    add("tempo map", not bad_tempo, f"{len(tempi)} tempo mark(s), {min(t for _, t in tempi):g}-"
        f"{max(t for _, t in tempi):g} BPM" if not bad_tempo else f"implausible tempi {bad_tempo[:5]}")

    labels = [(i + 1, m.section) for i, m in enumerate(ms) if m.section]
    empty = [b for b, s in labels if not s.strip()]
    add("sections", not empty and (not labels or labels[0][0] <= 2),
        f"{len(labels)} section(s) in order: " + ", ".join(s for _, s in labels[:12]) if labels and not empty
        else ("no section labels" if not labels else f"empty section labels at bars {empty}"),
        severity="error" if empty else "review")

    _coverage(score, v, audio_duration)

    flagged = [i + 1 for i, m in enumerate(ms) if m.uncertain]
    add("review flags", not flagged, "no bar is flagged as uncertain" if not flagged
        else f"{len(flagged)} of {len(ms)} bars hold a stroke the detector was unsure of (marked (?)); "
             f"listen to them: {flagged[:20]}{' ...' if len(flagged) > 20 else ''}", severity="review")
    return v


def _coverage(score: Score, v: Validation, audio_duration: float | None) -> None:
    """For audio transcriptions: bar start times are monotonic, bars last what their tempo
    says, every detected stroke falls inside the notated timeline, and the timeline runs
    from the first stroke of the recording to its last."""
    ms = score.measures
    add = lambda *a, **k: v.checks.append(Check(*a, **k))
    starts = [m.start_time for m in ms]
    times = [h.time for m in ms for h in m.hits if h.time is not None]
    if any(s is None for s in starts) or not times:
        add("timeline coverage", True, "written chart: no recording timeline to check", severity="review")
        return
    nonmono = [i + 1 for i in range(1, len(ms)) if starts[i] <= starts[i - 1]]
    add("bar timing", not nonmono, "bar start times increase through the song" if not nonmono
        else f"bars {nonmono[:10]} start before the bar ahead of them")
    drift = []
    for i in range(len(ms) - 1):
        actual, expected = starts[i + 1] - starts[i], _bar_seconds(score, i)
        if abs(actual - expected) > BAR_TIMING_TOLERANCE * expected:
            drift.append(i + 1)
    add("bars against the recording", len(drift) <= max(1, len(ms) // 50),
        "every bar lasts what its tempo mark says (within 25%)" if not drift
        else f"{len(drift)} bar(s) last longer or shorter than their tempo mark says: {drift[:10]}",
        severity="review")
    end = starts[-1] + _bar_seconds(score, len(ms) - 1)
    first, last = min(times), max(times)
    outside = sum(1 for t in times if t < starts[0] - COVERAGE_TOLERANCE_S or t > end + COVERAGE_TOLERANCE_S)
    v.coverage = {"chart_start_s": round(starts[0], 2), "chart_end_s": round(end, 2),
                  "first_stroke_s": round(first, 2) + 0.0, "last_stroke_s": round(last, 2),
                  "notated_strokes": len(times)}
    if audio_duration:
        v.coverage["audio_duration_s"] = round(audio_duration, 2)
        v.coverage["trailing_s"] = round(max(0.0, audio_duration - end), 2)
    add("timeline coverage", outside == 0 and starts[0] <= first + COVERAGE_TOLERANCE_S
        and end >= last - COVERAGE_TOLERANCE_S and (audio_duration is None or end <= audio_duration + 2 * COVERAGE_TOLERANCE_S),
        f"bars 1-{len(ms)} run from {starts[0]:.1f} s to {end:.1f} s, covering every stroke "
        f"({max(first, 0.0):.1f}-{last:.1f} s)" + (f" of the {audio_duration:.1f} s recording" if audio_duration else "")
        if outside == 0 else f"{outside} stroke(s) fall outside the notated bars")
    detected = score.analysis.get("detected_onsets") if score.analysis else None
    if detected:
        kept = len(times) / detected
        v.coverage["detected_strokes"] = detected
        add("strokes notated", kept >= 0.85, f"{len(times)} of {detected} detected strokes are in the chart "
            f"({kept:.0%}; flam grace notes and merged doubles account for the rest)", severity="review")


def chart_status(validation: Validation, rendering_ok: bool) -> str:
    """COMPLETE only when the score is valid, renders identically in every format, covers
    the recording and no bar awaits review; otherwise NEEDS_CORRECTION."""
    if validation.ok and rendering_ok and not validation.needs_review:
        return "COMPLETE"
    return "NEEDS_CORRECTION"
