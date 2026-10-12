"""Read exported files back and compare them with the IR.

These readers are deliberately independent of the writers: they parse the
MusicXML and MIDI files as any other program would, expand repeats, and
return (position in whole notes, instrument or MIDI key) events. The CLI's
`verify` step and the test suite use them to prove that the PDF's LilyPond
source, the MusicXML and the MIDI all encode the same music as the IR.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import mido

from .kit import DEFAULT_KIT, Kit
from .model import Score

SCHEMA_DIR = Path(__file__).parent / "schemas" / "musicxml-4.0"


@dataclass
class Comparison:
    name: str
    expected: int
    found: int
    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra

    def summary(self) -> str:
        status = "OK" if self.ok else "MISMATCH"
        text = f"{self.name}: {status} ({self.found}/{self.expected} events)"
        if self.missing:
            text += f"; missing {self.missing[:5]}"
        if self.extra:
            text += f"; extra {self.extra[:5]}"
        return text


def _compare(name: str, expected: list, found: list) -> Comparison:
    from collections import Counter
    e, f = Counter(expected), Counter(found)
    missing = sorted((e - f).elements())
    extra = sorted((f - e).elements())
    return Comparison(name, len(expected), len(found), missing, extra)


# ---------------------------------------------------------------------------
# Expected events from the IR
# ---------------------------------------------------------------------------

def expected_events(score: Score) -> list[tuple[Fraction, str]]:
    return score.event_list()


GRACE_GAP = Fraction(1, 64)  # must match export/midi.py (TICKS_PER_BEAT // 16)


def expected_midi_keys(score: Score, kit: Kit = DEFAULT_KIT, expand_rolls: bool = False,
                       include_graces: bool = False) -> list[tuple[Fraction, int]]:
    out = []
    starts = score.measure_starts()
    for i, _, h in score.iter_hits():
        key = kit[h.inst].midi
        on = starts[i] + h.pos
        if include_graces:
            # Grace notes that would start before the file are left out (export/midi.py).
            gaps = ([1] if h.flam else []) + ([2, 1] if h.drag else [])
            out += [(on - k * GRACE_GAP, key) for k in gaps if on - k * GRACE_GAP >= 0]
        if h.roll is not None and expand_rolls:
            t = Fraction(0)
            while t < h.roll:
                out.append((starts[i] + h.pos + t, key))
                t += Fraction(1, 32)
        else:
            out.append((starts[i] + h.pos, key))
    return sorted(out)


# ---------------------------------------------------------------------------
# MusicXML
# ---------------------------------------------------------------------------

def musicxml_events(path: str | Path) -> list[tuple[Fraction, str]]:
    """Events from a MusicXML file with repeats expanded; tie continuations and graces skipped."""
    root = ET.parse(path).getroot()
    part = root.find("part")
    if part is None:
        raise ValueError("MusicXML has no <part>")
    measures = part.findall("measure")
    divisions = 1
    order = _play_order(measures)

    events: list[tuple[Fraction, str]] = []
    measure_start = Fraction(0)
    for mi in order:
        mel = measures[mi]
        pos = Fraction(0)
        length = Fraction(0)
        last_onset = Fraction(0)
        for el in mel:
            if el.tag == "attributes":
                d = el.find("divisions")
                if d is not None:
                    divisions = int(d.text)
            elif el.tag == "backup":
                pos -= Fraction(int(el.find("duration").text), divisions * 4)
            elif el.tag == "forward":
                pos += Fraction(int(el.find("duration").text), divisions * 4)
            elif el.tag == "note":
                if el.find("grace") is not None:
                    continue
                dur = Fraction(int(el.find("duration").text), divisions * 4)
                is_chord = el.find("chord") is not None
                onset = last_onset if is_chord else pos
                if not is_chord:
                    last_onset = pos
                    pos += dur
                length = max(length, pos)
                if el.find("rest") is not None:
                    continue
                tie_stop = any(t.get("type") == "stop" for t in el.findall("tie"))
                if tie_stop:
                    continue
                inst = el.find("instrument")
                if inst is None:
                    raise ValueError(f"measure {mel.get('number')}: unpitched note without <instrument>")
                events.append((measure_start + onset, inst.get("id").split("-", 1)[1]))
        measure_start += length
    return sorted(events)


def validate_musicxml(path: str | Path) -> list[str]:
    """Validate against the MusicXML 4.0 XSD. Returns a list of errors (empty = valid)."""
    try:
        import xmlschema
    except ImportError:
        return ["xmlschema is not installed; cannot validate (pip install xmlschema)"]
    schema = _schema()
    errors = []
    for err in schema.iter_errors(str(path)):
        errors.append(f"{err.path}: {err.reason}")
        if len(errors) >= 20:
            break
    return errors


_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        import xmlschema
        xsd = SCHEMA_DIR / "musicxml.xsd"
        _SCHEMA = xmlschema.XMLSchema(
            str(xsd),
            locations={
                "http://www.w3.org/XML/1998/namespace": str(SCHEMA_DIR / "xml.xsd"),
                "http://www.w3.org/1999/xlink": str(SCHEMA_DIR / "xlink.xsd"),
            },
        )
    return _SCHEMA


# ---------------------------------------------------------------------------
# MIDI
# ---------------------------------------------------------------------------

def midi_events(path: str | Path, channel: int | None = 9) -> list[tuple[Fraction, int]]:
    """(position in whole notes, key) for every note-on (velocity > 0).

    Positions come from ticks, so they don't depend on tempo. LilyPond's MIDI
    puts drums on channel 10 as well. Pass channel=None to accept any channel.
    """
    mid = mido.MidiFile(str(path))
    tpb = mid.ticks_per_beat
    out = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and (channel is None or msg.channel == channel):
                out.append((Fraction(tick, 4 * tpb), msg.note))
    return sorted(out)


# ---------------------------------------------------------------------------
# Tempo, bar grid and articulations: what the event comparisons can't see
# ---------------------------------------------------------------------------

def midi_tempo_at_bars(path: str | Path, bar_starts: list[Fraction]) -> list[float]:
    """Quarter-note BPM in effect at each bar start (positions in whole notes)."""
    mid = mido.MidiFile(str(path))
    tpb = mid.ticks_per_beat
    changes = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                changes.append((Fraction(tick, 4 * tpb), mido.tempo2bpm(msg.tempo)))
    changes.sort(key=lambda c: c[0])
    out = []
    for pos in bar_starts:
        bpm = 120.0  # MIDI default when a file sets no tempo
        for at, b in changes:
            if at <= pos:
                bpm = b
        out.append(bpm)
    return out


def _compare_tempo(name: str, score: Score, path: Path, tolerance: float) -> Comparison:
    starts = score.measure_starts()
    found = midi_tempo_at_bars(path, starts)
    expected = [score.tempo_at(i) for i in range(len(score.measures))]
    bad = [(i + 1, round(e, 2), round(f, 2)) for i, (e, f) in enumerate(zip(expected, found)) if abs(e - f) > tolerance]
    return Comparison(name, len(expected), len(expected) - len(bad), missing=[(b, e) for b, e, _ in bad],
                      extra=[(b, f) for b, _, f in bad])


def midi_barlines(path: str | Path, end: Fraction) -> list[Fraction]:
    """Barline positions implied by the file's time signatures, up to `end` (whole notes)."""
    mid = mido.MidiFile(str(path))
    tpb = mid.ticks_per_beat
    sigs = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "time_signature":
                sigs.append((Fraction(tick, 4 * tpb), Fraction(msg.numerator, msg.denominator)))
    sigs.sort(key=lambda x: x[0])
    if not sigs or sigs[0][0] != 0:
        sigs.insert(0, (Fraction(0), Fraction(1)))
    lines, pos, k = [], Fraction(0), 0
    while pos < end:
        while k + 1 < len(sigs) and sigs[k + 1][0] <= pos:
            k += 1
        lines.append(pos)
        pos += sigs[k][1]
    return lines


def musicxml_meters(path: str | Path) -> list[str]:
    """Meter in effect for each measure in play order (repeats expanded)."""
    root = ET.parse(path).getroot()
    measures = root.find("part").findall("measure")
    current, out = None, []
    for i in _play_order(measures):
        tm = measures[i].find("attributes/time")
        if tm is not None:
            current = f"{tm.findtext('beats')}/{tm.findtext('beat-type')}"
        out.append(current)
    return out


_TECH_FLAGS = {("open", "above"): "open", ("open", "below"): "open-down", ("half-muted", "above"): "halfopen"}
_KIT_TECH = {"open": "open", "open-down": "open-down", "halfopen": "halfopen"}


def musicxml_articulations(path: str | Path) -> list[tuple[Fraction, str, str]]:
    """(position, instrument, flag) for accents, ghosts, flams, drags, rolls and
    hi-hat technique marks, in play order. Tie continuations are skipped."""
    root = ET.parse(path).getroot()
    measures = root.find("part").findall("measure")
    divisions = 1
    out: list[tuple[Fraction, str, str]] = []
    start = Fraction(0)
    for mi in _play_order(measures):
        pos = Fraction(0)
        length = Fraction(0)
        last_onset = Fraction(0)
        graces: dict[str, list[bool]] = {}  # instrument -> slashes of pending grace notes
        for el in measures[mi]:
            if el.tag == "attributes" and el.find("divisions") is not None:
                divisions = int(el.findtext("divisions"))
            elif el.tag == "backup":
                pos -= Fraction(int(el.findtext("duration")), divisions * 4)
            elif el.tag == "forward":
                pos += Fraction(int(el.findtext("duration")), divisions * 4)
            elif el.tag == "note":
                inst_el = el.find("instrument")
                inst = inst_el.get("id").split("-", 1)[1] if inst_el is not None else None
                g = el.find("grace")
                if g is not None:
                    graces.setdefault(inst, []).append(g.get("slash") == "yes")
                    continue
                dur = Fraction(int(el.findtext("duration")), divisions * 4)
                is_chord = el.find("chord") is not None
                onset = last_onset if is_chord else pos
                if not is_chord:
                    last_onset = pos
                    pos += dur
                length = max(length, pos)
                if el.find("rest") is not None or inst is None:
                    continue
                if any(t.get("type") == "stop" for t in el.findall("tie")):
                    continue
                at = start + onset
                if el.find("notations/articulations/accent") is not None:
                    out.append((at, inst, "accent"))
                nh = el.find("notehead")
                if nh is not None and nh.get("parentheses") == "yes":
                    out.append((at, inst, "ghost"))
                if el.find("notations/ornaments/tremolo") is not None:
                    out.append((at, inst, "roll"))
                for tech in el.findall("notations/technical/*"):
                    flag = _TECH_FLAGS.get((tech.tag, tech.get("placement", "above")))
                    if flag:
                        out.append((at, inst, flag))
                pending = graces.pop(inst, [])
                if pending == [True]:
                    out.append((at, inst, "flam"))
                elif len(pending) == 2:
                    out.append((at, inst, "drag"))
                elif pending:
                    out.append((at, inst, f"graces:{len(pending)}"))
        start += length
    return sorted(out)


def expected_articulations(score: Score, kit: Kit = DEFAULT_KIT) -> list[tuple[Fraction, str, str]]:
    out = []
    starts = score.measure_starts()
    for i, _, h in score.iter_hits():
        at = starts[i] + h.pos
        for flag in ("accent", "ghost", "flam", "drag"):
            if getattr(h, flag):
                out.append((at, h.inst, flag))
        if h.roll is not None:
            out.append((at, h.inst, "roll"))
        tech = _KIT_TECH.get(kit[h.inst].articulation or "")
        if tech:
            out.append((at, h.inst, tech))
    return sorted(out)


def _play_order(measures: list) -> list[int]:
    """Measure indices in play order with forward/backward repeats expanded."""
    order: list[int] = []
    i = 0
    repeat_start = 0
    passes: dict[int, int] = {}
    while i < len(measures):
        mel = measures[i]
        for bl in mel.findall("barline"):
            rep = bl.find("repeat")
            if rep is not None and rep.get("direction") == "forward" and passes.get(i, 0) == 0:
                repeat_start = i
        order.append(i)
        back = None
        for bl in mel.findall("barline"):
            rep = bl.find("repeat")
            if rep is not None and rep.get("direction") == "backward":
                back = int(rep.get("times", "2"))
        if back is not None:
            done = passes.get(i, 0) + 1
            passes[i] = done
            if done < back:
                i = repeat_start
                continue
            passes[i] = 0
        i += 1
    return order


def verify_exports(score: Score, ly_midi: Path | None, musicxml: Path | None, midi: Path | None,
                   kit: Kit = DEFAULT_KIT) -> list[Comparison]:
    results = []
    if ly_midi is not None:
        found = midi_events(ly_midi, channel=None)
        results.append(_compare("engraved score (LilyPond MIDI)", expected_midi_keys(score, kit), found))
        # LilyPond tempo marks are whole numbers (as printed), within a beat-unit rounding.
        results.append(_compare_tempo("engraved score tempo map", score, ly_midi, tolerance=1.0))
    if musicxml is not None:
        results.append(_compare("MusicXML", expected_events(score), musicxml_events(musicxml)))
        results.append(_compare("MusicXML articulations", expected_articulations(score, kit),
                                musicxml_articulations(musicxml)))
        meters = [(i + 1, m) for i, m in enumerate(musicxml_meters(musicxml))]
        results.append(_compare("MusicXML meters", [(i + 1, f"{m.time_sig.num}/{m.time_sig.den}")
                                                    for i, m in enumerate(score.measures)], meters))
    if midi is not None:
        found = midi_events(midi)
        expected = expected_midi_keys(score, kit, expand_rolls=True, include_graces=True)
        results.append(_compare("MIDI", expected, found))
        results.append(_compare_tempo("MIDI tempo map", score, midi, tolerance=0.01))
        starts = score.measure_starts()
        end = starts[-1] + score.measures[-1].actual_length if starts else Fraction(0)
        results.append(_compare("MIDI barlines", starts, midi_barlines(midi, end)))
    return results
