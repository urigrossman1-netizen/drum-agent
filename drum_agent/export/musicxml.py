"""MusicXML 4.0 writer (score-partwise), from the same tokens and layout plan
as the LilyPond writer.

The file opens as an editable drum-set part in MuseScore, Dorico, Sibelius and
Finale: each kit piece is a <score-instrument> with a GM <midi-unpitched> key,
and every note carries <unpitched> display position, notehead, voice, stem
direction and explicit beams. Element order follows the XSD; tests validate
the output against drum_agent/schemas/musicxml-4.0/musicxml.xsd.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import xml.etree.ElementTree as ET
from fractions import Fraction

from .. import __version__
from ..kit import DEFAULT_KIT, Kit, position_to_pitch
from ..layout import LayoutPlan, plan_layout, same_meter, volta_restates_meter
from ..model import CHART_TYPES, STATUSES, Hit, Measure, Score
from ..rhythm import Token, check_tokens, silent_voices, spell_measure, two_voice_bar, upper_bar_empty

_TYPE = {Fraction(2): "breve", Fraction(1): "whole", Fraction(1, 2): "half", Fraction(1, 4): "quarter",
         Fraction(1, 8): "eighth", Fraction(1, 16): "16th", Fraction(1, 32): "32nd", Fraction(1, 64): "64th"}
_NOTEHEAD = {"cross": "x", "xcircle": "circle-x", "diamond": "diamond", "triangle": "triangle",
             "slashed": "slashed"}


# Characters XML 1.0 does not allow (C0 controls other than tab/newline/CR, and
# non-characters); a title pasted from elsewhere or a MIDI track name can carry them.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrib: str) -> ET.Element:
    el = ET.SubElement(parent, tag, {k.replace("_", "-"): _NOT_XML.sub("", v) for k, v in attrib.items()})
    if text is not None:
        el.text = _NOT_XML.sub("", text)
    return el


def _lcm(a: int, b: int) -> int:
    return a * b // math.gcd(a, b)


def _divisions(score: Score) -> int:
    div = 1
    for m in score.measures:
        sm = spell_measure(m)
        for tokens in sm.voices.values():
            for t in tokens:
                div = _lcm(div, (t.dur * 4).denominator)
        div = _lcm(div, (m.actual_length * 4).denominator)
    return div


# kit articulation -> (MusicXML <technical> element, placement)
_TECHNICAL = {
    "open": ("open", "above"),
    "open-down": ("open", "below"),
    "halfopen": ("half-muted", "above"),
    "stopped": ("stopped", "above"),
}


class _XmlWriter:
    def __init__(self, score: Score, kit: Kit, plan: LayoutPlan):
        self.score = score
        self.kit = kit
        self.plan = plan
        self.div = _divisions(score)
        self.hh_marks = score.hihat_close_marks()  # closed strokes that get "+"
        self.bar_index = 0
        # One-voice chart (as in the LilyPond engraving): the empty voice is left out and the
        # other is written stems up, accents above, except in a bar with a roll moved up.
        self.silent = silent_voices(score.measures, kit)
        self.two_voices = False  # this bar of a one-voice chart is in two voices (a roll moved up)

    def stem(self, voice: int) -> str:
        return "up" if voice == 1 or (self.silent and not self.two_voices) else "down"

    def ticks(self, dur: Fraction) -> int:
        t = dur * 4 * self.div
        if t.denominator != 1:
            raise ValueError(f"duration {dur} not representable with divisions {self.div}")
        return int(t)

    # -- notes ---------------------------------------------------------------
    def _unpitched(self, note: ET.Element, inst: str) -> None:
        step, octave = position_to_pitch(self.kit[inst].position)
        up = _sub(note, "unpitched")
        _sub(up, "display-step", step)
        _sub(up, "display-octave", str(octave))

    def _notehead(self, note: ET.Element, h: Hit) -> None:
        head = _NOTEHEAD.get(self.kit[h.inst].notehead)
        if head or h.ghost:
            el = _sub(note, "notehead", head or "normal")
            if h.ghost:
                el.set("parentheses", "yes")

    def _grace_notes(self, measure_el: ET.Element, hits: list[Hit], voice: int) -> bool:
        flams = [h for h in hits if h.flam]
        drags = [h for h in hits if h.drag]
        if not flams and not drags:
            return False
        stem = self.stem(voice)
        groups: list[tuple[list[Hit], str, int]] = []
        if drags:
            groups.append((drags, "16th", 2))
        if flams:
            groups.append((flams, "eighth", 1))
        first = True
        for ghits, gtype, count in groups:
            for k in range(count):
                for ci, h in enumerate(ghits):
                    n = _sub(measure_el, "note")
                    g = _sub(n, "grace")
                    if gtype == "eighth":
                        g.set("slash", "yes")
                    if ci > 0:
                        _sub(n, "chord")
                    self._unpitched(n, h.inst)
                    _sub(n, "instrument", id=f"P1-{h.inst}")
                    _sub(n, "voice", str(voice))
                    _sub(n, "type", gtype)
                    _sub(n, "stem", stem)
                    self._notehead(n, h)
                    if ci == 0 and count == 2:
                        _sub(n, "beam", "begin" if k == 0 else "end", number="1")
                        _sub(n, "beam", "begin" if k == 0 else "end", number="2")
                    if ci == 0 and first:
                        nots = _sub(n, "notations")
                        _sub(nots, "slur", type="start", number="1")
                        first = False
        return True

    def note_token(self, measure_el: ET.Element, t: Token, voice: int, measure: Measure) -> None:
        stem = self.stem(voice)
        if t.kind in ("rest", "measure_rest"):
            n = _sub(measure_el, "note")
            r = _sub(n, "rest")
            if t.kind == "measure_rest":
                r.set("measure", "yes")
            _sub(n, "duration", str(self.ticks(t.dur)))
            _sub(n, "voice", str(voice))
            if t.kind == "rest":
                _sub(n, "type", _TYPE[t.value])
                for _ in range(t.dots):
                    _sub(n, "dot")
                self._time_mod(n, t)
                for level in sorted(t.beams):
                    _sub(n, "beam", t.beams[level], number=str(level))
                self._tuplet_notations(n, t)
            return
        has_grace = False if t.tie_stop else self._grace_notes(measure_el, t.hits, voice)
        for ci, h in enumerate(t.hits):
            n = _sub(measure_el, "note")
            if ci > 0:
                _sub(n, "chord")
            self._unpitched(n, h.inst)
            _sub(n, "duration", str(self.ticks(t.dur)))
            if t.tie_stop:
                _sub(n, "tie", type="stop")
            if t.tie_start:
                _sub(n, "tie", type="start")
            _sub(n, "instrument", id=f"P1-{h.inst}")
            _sub(n, "voice", str(voice))
            _sub(n, "type", _TYPE[t.value])
            for _ in range(t.dots):
                _sub(n, "dot")
            self._time_mod(n, t)
            _sub(n, "stem", stem)
            self._notehead(n, h)
            if ci == 0:
                for level in sorted(t.beams):
                    _sub(n, "beam", t.beams[level], number=str(level))
            nots = ET.Element("notations")
            if t.tie_stop:
                _sub(nots, "tied", type="stop")
            if t.tie_start:
                _sub(nots, "tied", type="start")
            if ci == 0 and has_grace:
                _sub(nots, "slur", type="stop", number="1")
            if ci == 0:
                self._tuplet_into(nots, t)
            if h.roll is not None:
                orn = _sub(nots, "ornaments")
                _sub(orn, "tremolo", str(max(1, 3 - t.beam_levels)), type="single")
            tech = None
            if not t.tie_stop:
                # The kit's articulation field drives the mark, as in LilyPond's drum style.
                art_kind = self.kit[h.inst].articulation
                if h.inst == "hihat" and (self.bar_index, h.pos) in self.hh_marks:
                    art_kind = "stopped"
                tech = _TECHNICAL.get(art_kind) if art_kind else None
            sticking = h.sticking if not t.tie_stop else None
            if tech or sticking:
                tech_el = _sub(nots, "technical")
                if tech:
                    _sub(tech_el, tech[0], placement=tech[1])
                if sticking:
                    _sub(tech_el, "fingering", sticking, placement="below")
            if h.accent and not t.tie_stop:
                art = _sub(nots, "articulations")
                _sub(art, "accent", placement="above" if stem == "up" else "below")
            if len(nots):
                n.append(nots)

    def _time_mod(self, n: ET.Element, t: Token) -> None:
        if t.tuplet:
            tm = _sub(n, "time-modification")
            _sub(tm, "actual-notes", str(t.tuplet[0]))
            _sub(tm, "normal-notes", str(t.tuplet[1]))

    def _tuplet_into(self, nots: ET.Element, t: Token) -> None:
        if t.tuplet_start:
            _sub(nots, "tuplet", type="start", bracket="yes" if t.bracket else "no")
        if t.tuplet_stop:
            _sub(nots, "tuplet", type="stop")

    def _tuplet_notations(self, n: ET.Element, t: Token) -> None:
        nots = ET.Element("notations")
        self._tuplet_into(nots, t)
        if len(nots):
            n.append(nots)

    # -- measures ------------------------------------------------------------
    def direction_words(self, measure_el: ET.Element, text: str, placement: str = "above",
                        **attrs: str) -> None:
        d = _sub(measure_el, "direction", placement=placement)
        dt = _sub(d, "direction-type")
        _sub(dt, "words", text, **attrs)

    def tempo_direction(self, measure_el: ET.Element, m: Measure, index: int) -> None:
        if m.tempo is None and not m.tempo_text:
            return
        tempo = m.tempo if m.tempo is not None else self.score.tempo_at(index)
        d = _sub(measure_el, "direction", placement="above")
        if m.tempo_text:
            dt = _sub(d, "direction-type")
            _sub(dt, "words", m.tempo_text, font_weight="bold")
        dt = _sub(d, "direction-type")
        met = _sub(dt, "metronome")
        unit, dotted = m.time_sig.metronome_unit()
        if unit is None or unit not in _TYPE:
            _sub(met, "beat-unit", "quarter")
            _sub(met, "per-minute", str(int(round(tempo))))
        else:
            _sub(met, "beat-unit", _TYPE[unit])
            if dotted:
                _sub(met, "beat-unit-dot")
            _sub(met, "per-minute", str(int(round(tempo * float(Fraction(1, 4) / (unit * 3 / 2 if dotted else unit))))))
        _sub(d, "sound", tempo=f"{tempo:g}")


def to_musicxml(score: Score, kit: Kit = DEFAULT_KIT, plan: LayoutPlan | None = None,
                repeats: str = "auto", bars_per_line: float = 4.0) -> str:
    score.validate(kit)
    if plan is None:
        plan = plan_layout(score, repeats=repeats, bars_per_line=bars_per_line)
    w = _XmlWriter(score, kit, plan)

    root = ET.Element("score-partwise", version="4.0")
    work = _sub(root, "work")
    _sub(work, "work-title", score.title)
    ident = _sub(root, "identification")
    if score.artist:
        _sub(ident, "creator", score.artist, type="composer")
    if score.transcriber:
        _sub(ident, "creator", f"Transcribed by {score.transcriber}", type="arranger")
    if score.copyright:
        _sub(ident, "rights", score.copyright)
    enc = _sub(ident, "encoding")
    _sub(enc, "software", f"Drum Agent {__version__}")
    _sub(enc, "encoding-date", _dt.date.today().isoformat())
    _sub(enc, "supports", element="beam", type="yes")
    _sub(enc, "supports", element="stem", type="yes")
    _sub(enc, "supports", element="print", type="yes", attribute="new-system", value="yes")
    if score.source:
        _sub(ident, "source", score.source)
    misc = _sub(ident, "miscellaneous")
    _sub(misc, "miscellaneous-field", CHART_TYPES[score.chart_type], name="chart-type")
    status = STATUSES.get(score.status)
    if status:
        _sub(misc, "miscellaneous-field", status, name="status")
    if score.rights:
        _sub(misc, "miscellaneous-field", score.rights, name="rights")

    credit_lines = [("title", score.title)]
    if score.artist:
        credit_lines.append(("subtitle", score.artist))
    sub = CHART_TYPES[score.chart_type] + (f" · {status}" if status else "")
    credit_lines.append(("subtitle", sub))
    for ctype, text in credit_lines:
        c = _sub(root, "credit", page="1")
        _sub(c, "credit-type", ctype)
        _sub(c, "credit-words", text, justify="center", halign="center", valign="top",
             font_size="22" if ctype == "title" else "12")

    plist = _sub(root, "part-list")
    sp = _sub(plist, "score-part", id="P1")
    _sub(sp, "part-name", "Drum Set")
    _sub(sp, "part-abbreviation", "Dr.")
    used = score.instruments_used() or ["snare"]
    for inst in used:
        si = _sub(sp, "score-instrument", id=f"P1-{inst}")
        _sub(si, "instrument-name", kit[inst].name)
    for inst in used:
        mi = _sub(sp, "midi-instrument", id=f"P1-{inst}")
        _sub(mi, "midi-channel", "10")
        _sub(mi, "midi-program", "1")
        _sub(mi, "midi-unpitched", str(kit[inst].midi + 1))
        _sub(mi, "volume", "80")

    part = _sub(root, "part", id="P1")
    prev: Measure | None = None
    bars = plan.bars
    in_percent = False
    for bi, pb in enumerate(bars):
        m = score.measures[pb.index]
        w.bar_index = pb.index
        number = plan.printed_numbers.get(pb.index, bi + 1)
        mel = _sub(part, "measure", number=str(number))
        if m.is_pickup and prev is None:
            mel.set("implicit", "yes")
        if pb.line_break and prev is not None:
            _sub(mel, "print", new_system="yes")
        if pb.volta_start:
            bl = _sub(mel, "barline", location="left")
            _sub(bl, "bar-style", "heavy-light")
            _sub(bl, "repeat", direction="forward")
        # attributes
        attrs = ET.Element("attributes")
        if prev is None:
            _sub(attrs, "divisions", str(w.div))
            key = _sub(attrs, "key")
            _sub(key, "fifths", "0")
        restate = pb.volta_start and volta_restates_meter(score, plan, bi)
        if prev is None or restate or not same_meter(prev, m):
            tm = _sub(attrs, "time")
            _sub(tm, "beats", str(m.time_sig.num))
            _sub(tm, "beat-type", str(m.time_sig.den))
        if prev is None:
            clef = _sub(attrs, "clef")
            _sub(clef, "sign", "percussion")
            sd = _sub(attrs, "staff-details")
            _sub(sd, "staff-lines", "5")
        if pb.rest_run > 1:  # the bars are all written; readers show them as one multi-bar rest
            ms = _sub(attrs, "measure-style")
            _sub(ms, "multiple-rest", str(pb.rest_run))
        if pb.percent and not in_percent:
            ms = _sub(attrs, "measure-style")
            _sub(ms, "measure-repeat", "1", type="start")
            in_percent = True
        elif not pb.percent and in_percent:
            ms = _sub(attrs, "measure-style")
            _sub(ms, "measure-repeat", type="stop")
            in_percent = False
        if len(attrs):
            mel.append(attrs)
        if m.section:
            d = _sub(mel, "direction", placement="above")
            dt = _sub(d, "direction-type")
            _sub(dt, "rehearsal", m.section, enclosure="rectangle")
        w.tempo_direction(mel, m, pb.index)
        if m.cue:
            w.direction_words(mel, m.cue, font_style="italic")
        if m.uncertain:
            w.direction_words(mel, "(?)", font_size="9", color="#555555")
        sm = spell_measure(m, kit)
        w.two_voices = two_voice_bar(sm, w.silent)
        written = False
        for voice in (1, 2):
            tokens = sm.voices[voice]
            if (not tokens or (voice in w.silent and not sm.shared_rest and not w.two_voices)
                    or (voice == 1 and upper_bar_empty(sm))):
                continue
            check_tokens(tokens, m)
            if written:
                b = _sub(mel, "backup")
                _sub(b, "duration", str(w.ticks(m.actual_length)))
            written = True
            # An empty bar's rest goes in the voice that carries the chart.
            xml_voice = 2 if sm.shared_rest and 1 in w.silent else voice
            for t in tokens:
                if any(h.choke for h in t.hits) and not t.tie_stop:
                    w.direction_words(mel, "choke", font_style="italic", font_size="9")
                w.note_token(mel, t, xml_voice, m)
        if pb.volta_end:
            w.direction_words(mel, f"×{pb.volta_times}", font_weight="bold")
            bl = _sub(mel, "barline", location="right")
            _sub(bl, "bar-style", "light-heavy")
            _sub(bl, "repeat", direction="backward", times=str(pb.volta_times))
        else:
            nxt = bars[bi + 1] if bi + 1 < len(bars) else None
            if nxt is None:
                bl = _sub(mel, "barline", location="right")
                _sub(bl, "bar-style", "light-heavy")
            elif score.measures[nxt.index].section and not nxt.volta_start:
                bl = _sub(mel, "barline", location="right")
                _sub(bl, "bar-style", "light-light")
        prev = m
    ET.indent(root, space=" ")
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n' + body + "\n")
