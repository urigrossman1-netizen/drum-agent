"""LilyPond writer: Score -> .ly source.

The .ly contains two \\score blocks over the same music: one engraved (PDF/PNG)
and one with \\unfoldRepeats that produces MIDI. Because both come from one
source, tests can read LilyPond's MIDI to verify what was actually engraved.
"""

from __future__ import annotations

from fractions import Fraction

from ..kit import DEFAULT_KIT, Kit
from ..layout import LayoutPlan, PrintedBar, plan_layout, same_meter, volta_restates_meter
from ..model import CHART_TYPES, STATUSES, Hit, Measure, Score
from ..rhythm import SpelledMeasure, Token, check_tokens, spell_measure

LY_VERSION = "2.24.0"  # minimum syntax level; rendered with 2.26 where available

_NOTEHEAD = {"normal": "()", "cross": "cross", "xcircle": "xcircle", "diamond": "diamond",
             "triangle": "triangle", "slashed": "()"}
_ARTIC = {None: "#f", "open": "(open . ,UP)", "halfopen": "halfopen", "stopped": "stopped",
          "open-down": "(open . ,DOWN)"}
_SEMITONE = [(0, "0"), (0, "1/2"), (1, "0"), (1, "1/2"), (2, "0"), (3, "0"), (3, "1/2"),
             (4, "0"), (4, "1/2"), (5, "0"), (5, "1/2"), (6, "0")]

CLOSED_HH = "hihatclosed"  # display-only name: closed hi-hat with "+" after an open one


def ly_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def duration(value: Fraction, dots: int = 0) -> str:
    if value == 2:
        base = "\\breve"
    else:
        inv = 1 / value
        if inv.denominator != 1:
            raise ValueError(f"not a note value: {value}")
        base = str(inv.numerator)
    return base + "." * dots


def _midi_pitch(n: int) -> str:
    octave = n // 12 - 5
    step, alter = _SEMITONE[n % 12]
    return f"(ly:make-pitch {octave} {step} {alter})"


def preamble(kit: Kit) -> str:
    style = []
    names = []
    midi = []
    for ins in kit.instruments:
        style.append(f"    ({ins.ly_name} {_NOTEHEAD[ins.notehead]} {_ARTIC[ins.articulation]} {ins.position})")
        names.append(f"drumPitchNames.{ins.ly_name} = #'{ins.ly_name}")
        midi.append(f"    ({ins.ly_name} . ,{_midi_pitch(ins.midi)})")
    hh = kit["hihat"]
    style.append(f"    ({CLOSED_HH} {_NOTEHEAD[hh.notehead]} stopped {hh.position})")
    names.append(f"drumPitchNames.{CLOSED_HH} = #'{CLOSED_HH}")
    midi.append(f"    ({CLOSED_HH} . ,{_midi_pitch(hh.midi)})")
    return "\n".join([
        f'\\version "{LY_VERSION}"',
        "",
        "% Drum notation style generated from drum_agent/kit.py (see docs/NOTATION_SPEC.md).",
        "#(define drum-agent-style `(",
        *style,
        "    ))",
        "#(define drum-agent-midi `(",
        *midi,
        "    ))",
        *names,
        "",
        "% Rimshot: normal notehead with a slash through it.",
        "#(define (rimshot-head grob)",
        "   (let* ((head (ly:note-head::print grob))",
        "          (x (ly:stencil-extent head X))",
        "          (y (ly:stencil-extent head Y)))",
        "     (ly:stencil-add head",
        "       (make-line-stencil 0.16 (- (car x) 0.25) (- (car y) 0.3) (+ (cdr x) 0.25) (+ (cdr y) 0.3)))))",
        "",
    ])


def header(score: Score) -> str:
    lines = ["\\header {", f"  title = {ly_string(score.title)}"]
    if score.artist:
        lines.append(f"  subtitle = {ly_string(score.artist)}")
    info = CHART_TYPES[score.chart_type]
    status = STATUSES.get(score.status)
    sub = info + (f"  ·  {status}" if status else "")
    lines.append(f"  subsubtitle = \\markup \\normal-text \\italic {ly_string(sub)}")
    if score.transcriber:
        lines.append(f"  composer = {ly_string('Transcribed by ' + score.transcriber)}")
    if score.copyright:
        lines.append(f"  copyright = {ly_string(score.copyright)}")
    lines.append("  tagline = ##f")
    lines.append("}")
    return "\n".join(lines)


def paper(paper_size: str, staff_size: float, ragged_last: bool, page_count: int | None = None) -> str:
    footer = "  ragged-last = ##t\n" if ragged_last else ""
    if page_count:
        footer += f"  page-count = {int(page_count)}\n"
    return (
        f"#(set-global-staff-size {staff_size})\n"
        "\\paper {\n"
        f"  #(set-paper-size \"{paper_size}\")\n"
        "  indent = 0\\mm\n"
        "  short-indent = 0\\mm\n"
        "  top-margin = 12\\mm\n"
        "  bottom-margin = 12\\mm\n"
        "  left-margin = 14\\mm\n"
        "  right-margin = 14\\mm\n"
        "  ragged-last-bottom = ##t\n"
        "  ragged-bottom = ##f\n"
        "  markup-system-spacing.basic-distance = #7\n"
        "  score-markup-spacing.basic-distance = #8\n"
        "  score-system-spacing.basic-distance = #14\n"
        "  system-system-spacing = #'((basic-distance . 14) (minimum-distance . 10) (padding . 2) (stretchability . 12))\n"
        "  print-first-page-number = ##f\n"
        + footer +
        "}\n"
    )


def layout_block() -> str:
    return (
        "\\layout {\n"
        "  \\context {\n"
        "    \\Score\n"
        "    \\override BarNumber.break-visibility = ##(#f #f #t)\n"
        "    \\override BarNumber.font-size = #-1\n"
        "    \\override SectionLabel.font-size = #1\n"
        "    \\override SectionLabel.stencil = #(lambda (grob) (box-stencil (ly:text-interface::print grob) 0.15 0.4))\n"
        "    \\override MetronomeMark.font-size = #0\n"
        "    \\override SpacingSpanner.base-shortest-duration = #(ly:make-moment 1/16)\n"
        "    \\override TupletBracket.bracket-visibility = ##t\n"
        "    \\override PercentRepeatCounter.font-size = #-2\n"
        "    countPercentRepeats = ##t\n"
        "  }\n"
        "  \\context {\n"
        "    \\DrumStaff\n"
        "    drumStyleTable = #(alist->hash-table drum-agent-style)\n"
        "  }\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

def _tempo_mark(m: Measure, score: Score, index: int) -> str | None:
    if m.tempo is None and not m.tempo_text:
        return None
    tempo = m.tempo if m.tempo is not None else score.tempo_at(index)
    text = m.tempo_text
    unit = m.time_sig.beat_unit
    if m.time_sig.is_compound:
        bpm = tempo * 2 / 3
        unit_str = "4."
    else:
        bpm = tempo * float(Fraction(1, 4) / unit)
        unit_str = duration(unit) if representable_unit(unit) else "4"
        if not representable_unit(unit):
            bpm = tempo
    mark = f"{unit_str} = {int(round(bpm))}"
    return f"\\tempo {ly_string(text)} {mark}" if text else f"\\tempo {mark}"


def _midi_tempo(bpm: float) -> str:
    """Initial tempo for the verification MIDI score (bar 1 may carry no mark).
    LilyPond tempo marks are whole numbers, like the printed marks."""
    return str(int(round(bpm)))


def representable_unit(unit: Fraction) -> bool:
    return (1 / unit).denominator == 1


def _time_command(m: Measure) -> str:
    ts = m.time_sig
    if ts.is_irregular:
        groups = ",".join(str(g) for g in ts.groups())
        return f"\\time {groups} {ts.num}/{ts.den}"
    return f"\\time {ts.num}/{ts.den}"


def _skip(length: Fraction) -> str:
    return f"s1*{length.numerator}/{length.denominator}" if length != 1 else "s1"


class _Writer:
    def __init__(self, score: Score, kit: Kit, plan: LayoutPlan):
        self.score = score
        self.kit = kit
        self.plan = plan
        self.hh_marks = score.hihat_close_marks()  # closed strokes that get "+"
        self.bar_index = 0  # bar being written (set by music_streams)
        self.shared_rest = False

    # -- tokens ------------------------------------------------------------
    def _hit_name(self, h: Hit) -> str:
        name = self.kit[h.inst].ly_name
        if h.inst == "hihat" and (self.bar_index, h.pos) in self.hh_marks:
            name = CLOSED_HH
        return name

    def _note_body(self, h: Hit) -> str:
        name = self._hit_name(h)
        parts = []
        if h.ghost:
            parts.append("\\parenthesize ")
        if self.kit[h.inst].notehead == "slashed":
            parts.append("\\tweak NoteHead.stencil #rimshot-head ")
        parts.append(name)
        return "".join(parts)

    def token(self, t: Token, voice: int) -> str:
        if t.kind == "measure_rest":
            rest = f"R1*{t.dur.numerator}/{t.dur.denominator}" if t.dur != 1 else "R1"
            if self.shared_rest:
                # Both voices silent: one rest at its normal height, not raised for voice 1.
                rest = "\\once \\override MultiMeasureRest.direction = #CENTER " + rest
            return rest
        dur = duration(t.value, t.dots)  # a whole-bar rest (e.g. 7/8) has no single note value
        if t.kind == "rest":
            return f"r{dur}"
        hits = t.hits
        graces = ""
        if not t.tie_stop:
            flams = [h for h in hits if h.flam]
            drags = [h for h in hits if h.drag]
            if flams:
                g = " ".join(self.kit[h.inst].ly_name for h in flams)
                g = g if len(flams) == 1 else f"<{g}>"
                graces += f"\\tag #'graces \\acciaccatura {{ {g}8 }} "
            if drags:
                g = " ".join(self.kit[h.inst].ly_name for h in drags)
                g = g if len(drags) == 1 else f"<{g}>"
                graces += f"\\tag #'graces \\appoggiatura {{ {g}16[ {g}16] }} "
        if len(hits) == 1:
            body = self._note_body(hits[0]) + dur
        else:
            # LilyPond's drum engraver ignores articulations on individual chord
            # members, so an accent goes on the chord (it prints identically).
            body = "<" + " ".join(self._note_body(h) for h in hits) + ">" + dur
        if t.is_roll:
            body += ":32"
        if any(h.accent for h in hits) and not t.tie_stop:
            body += "->"
        if any(h.choke for h in hits) and not t.tie_stop:
            body += "^\\markup \\small \\italic \"choke\""
        if t.tie_start:
            body += "~"
        return graces + body

    def voice_bar(self, tokens: list[Token], voice: int, measure: Measure) -> str:
        if tokens:
            check_tokens(tokens, measure)
        out: list[str] = []
        for t in tokens:
            s = ""
            if t.tuplet_start:
                a, n = t.tuplet
                s += f"\\tuplet {a}/{n} {{ "
            s += self.token(t, voice)
            if t.beams.get(1) == "begin":
                s += "["
            elif t.beams.get(1) == "end":
                s += "]"
            if t.tuplet_stop:
                s += " }"
            out.append(s)
        return " ".join(out)

    # -- bars ----------------------------------------------------------------
    def global_bar(self, pb: PrintedBar, idx: int, prev: Measure | None,
                   end_bar: str | None = None, restate_time: bool = False) -> str:
        m = self.score.measures[idx]
        items: list[str] = []
        if pb.line_break and prev is not None:
            items.append("\\break")
        if prev is None or restate_time or not same_meter(prev, m):
            items.append(_time_command(m))
        if prev is None and m.is_pickup:
            items.append(f"\\partial {_partial(m.actual_length)}")
        tempo = _tempo_mark(m, self.score, idx)
        if tempo:
            items.append(tempo)
        if m.section:
            items.append(f"\\sectionLabel {ly_string(m.section)}")
        skip = _skip(m.actual_length)
        if m.uncertain:
            skip += "^\\markup \\small \\with-color #(rgb-color 0.35 0.35 0.35) \"(?)\""
        items.append(skip)
        if pb.volta_end:
            items.append(f"\\textEndMark \\markup \\bold \"×{pb.volta_times}\"")
        if end_bar:
            items.append(f'\\bar "{end_bar}"')
        return " ".join(items)


def _partial(length: Fraction) -> str:
    rv = None
    for dots in (0, 1):
        base = length / (2 - Fraction(1, 2 ** dots))
        if (1 / base).denominator == 1 and (1 / base).numerator & ((1 / base).numerator - 1) == 0:
            rv = duration(base, dots)
            break
    if rv is None:
        rv = f"8*{length / Fraction(1, 8)}"
    return rv


def music_streams(score: Score, kit: Kit, plan: LayoutPlan) -> tuple[str, str, str]:
    """Return (global, up, down) LilyPond music with identical repeat structure."""
    w = _Writer(score, kit, plan)
    spelled: dict[int, SpelledMeasure] = {}

    def spelled_bar(idx: int) -> SpelledMeasure:
        if idx not in spelled:
            spelled[idx] = spell_measure(score.measures[idx], kit)
        return spelled[idx]

    g_out: list[str] = []
    up_out: list[str] = []
    down_out: list[str] = []
    prev: Measure | None = None
    bars = plan.bars
    i = 0
    open_volta = False
    while i < len(bars):
        pb = bars[i]
        if pb.volta_start:
            for out in (g_out, up_out, down_out):
                out.append(f"\\repeat volta {pb.volta_times} {{")
            open_volta = True
        run = pb.percent_run if pb.percent_run > 1 else 1
        idx = pb.index
        m = score.measures[idx]
        sm = spelled_bar(idx)
        after = bars[i + run] if i + run < len(bars) else None
        last_in_group = bars[i + run - 1]
        end_bar = None
        if after is None:
            end_bar = None if last_in_group.volta_end else "|."
        elif score.measures[after.index].section and not last_in_group.volta_end and not after.volta_start:
            end_bar = "||"
        restate = pb.volta_start and volta_restates_meter(score, plan, i)
        gbar = w.global_bar(pb, idx, prev, end_bar if run == 1 else None, restate_time=restate)
        w.bar_index = idx
        w.shared_rest = sm.shared_rest
        up = w.voice_bar(sm.voices[1], 1, m)
        w.shared_rest = False
        if sm.shared_rest:
            down = _skip(m.actual_length)
        else:
            down = w.voice_bar(sm.voices[2], 2, m)
        if run > 1:
            # The global stream prints the simile marks; voices hide theirs.
            pre = ""
            if pb.line_break and prev is not None:
                pre = "\\break "
                gbar = gbar.replace("\\break ", "", 1)
            end_mark = ""
            if bars[i + run - 1].volta_end:
                end_mark = f" \\textEndMark \\markup \\bold \"×{bars[i + run - 1].volta_times}\""
            if end_bar:
                end_mark += f' \\bar "{end_bar}"'
            g_out.append(f"{pre}\\repeat percent {run} {{ {gbar} | }}{end_mark}")
            up_out.append(f"\\repeat percent {run} {{ {up} | }}")
            down_out.append(f"\\repeat percent {run} {{ {down} | }}")
            # Hi-hat state after the run equals the state after one pass (identical bars).
            i += run
            last = bars[i - 1]
        else:
            g_out.append(gbar + " |")
            up_out.append(up + " |")
            down_out.append(down + " |")
            i += 1
            last = pb
        prev = m
        if last.volta_end and open_volta:
            for out in (g_out, up_out, down_out):
                out.append("}")
            open_volta = False
    if open_volta:
        raise AssertionError("unterminated volta in layout plan")
    return "\n  ".join(g_out), "\n  ".join(up_out), "\n  ".join(down_out)


def legend(score: Score, kit: Kit) -> str:
    used = score.instruments_used()
    if not used:
        return ""
    ordered = sorted(used, key=lambda i: -kit[i].position)
    notes = []
    labels = []
    for inst in ordered:
        ins = kit[inst]
        body = ins.ly_name
        if ins.notehead == "slashed":
            body = f"\\tweak NoteHead.stencil #rimshot-head {body}"
        notes.append(f"{body}4 s4")
        labels.append(f"{ly_string(ins.name)}2")
    return (
        "\\markup \\bold \"Drum Key\"\n"
        "\\score {\n"
        "  <<\n"
        "    \\new DrumStaff \\with {\n"
        "      \\remove Time_signature_engraver\n"
        "      \\remove Bar_number_engraver\n"
        "      \\override BarLine.stencil = ##f\n"
        "      \\hide Stem\n"
        "      \\override Stem.Y-extent = ##f\n"
        "      \\override StaffSymbol.staff-space = #0.8\n"
        "      fontSize = #-2\n"
        "    } \\drummode { \\cadenzaOn " + " ".join(notes) + " \\cadenzaOff }\n"
        "    \\new Lyrics \\with { \\override LyricText.font-size = #-3 "
        "\\override VerticalAxisGroup.nonstaff-relatedstaff-spacing = #'((basic-distance . 2) (padding . 0.4)) } "
        "\\lyricmode { " + " ".join(labels) + " }\n"
        "  >>\n"
        "  \\layout { ragged-right = ##t indent = 0 \\context { \\Score \\remove Bar_number_engraver } }\n"
        "}\n"
    )


def _short_last_line(score: Score, plan: LayoutPlan) -> bool:
    """True when the final system holds less than 60% of a full line."""
    from ..layout import PERCENT_WEIGHT, _weight
    last = max(k for k, b in enumerate(plan.bars) if b.line_break)
    weight = sum(PERCENT_WEIGHT if b.percent else _weight(score.measures[b.index]) for b in plan.bars[last:])
    return weight < 0.6 * plan.bars_per_line


def to_lilypond(score: Score, kit: Kit = DEFAULT_KIT, plan: LayoutPlan | None = None,
                paper_size: str = "letter", staff_size: float = 20, with_legend: bool = True,
                repeats: str = "auto", bars_per_line: float = 4.0, page_count: int | None = None) -> str:
    score.validate(kit)
    if plan is None:
        plan = plan_layout(score, repeats=repeats, bars_per_line=bars_per_line)
    glob, up, down = music_streams(score, kit, plan)
    has_uncertain = any(m.uncertain for m in score.measures)
    parts = [
        preamble(kit),
        header(score),
        paper(paper_size, staff_size, _short_last_line(score, plan), page_count),
        layout_block(),
        f"globalMusic = {{\n  \\autoLineBreaksOff\n  {glob}\n}}",
        f"upMusic = \\drummode {{\n  \\autoBeamOff\n  {up}\n}}",
        f"downMusic = \\drummode {{\n  \\autoBeamOff\n  {down}\n}}",
        "drumMusic = \\new DrumStaff <<\n"
        "  \\new DrumVoice = \"global\" \\globalMusic\n"
        "  \\new DrumVoice = \"up\" \\with { \\hide PercentRepeat \\hide PercentRepeatCounter } { \\voiceOne \\upMusic }\n"
        "  \\new DrumVoice = \"down\" \\with { \\hide PercentRepeat \\hide PercentRepeatCounter } { \\voiceTwo \\downMusic }\n"
        ">>",
    ]
    if with_legend and len(score.instruments_used()) > 3:
        parts.append(legend(score, kit))
    if has_uncertain:
        parts.append("\\markup \\small \\italic \"(?) above a bar = it contains low-confidence "
                     "detections; verify those bars against the recording.\"")
    parts.append("\\score {\n  \\drumMusic\n  \\layout { }\n}")
    parts.append(
        "\\score {\n"
        "  \\removeWithTag #'graces \\unfoldRepeats \\drumMusic\n"
        "  \\midi {\n"
        f"    \\tempo 4 = {_midi_tempo(score.initial_tempo)}\n"
        "    \\context { \\DrumStaff drumPitchTable = #(alist->hash-table drum-agent-midi) }\n"
        "  }\n"
        "}"
    )
    return "\n\n".join(parts) + "\n"
