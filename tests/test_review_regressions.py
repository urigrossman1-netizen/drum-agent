"""Regressions for defects found in code review and in real skill sessions.

Each test pins one confirmed defect: the engraving, the exports or the
verification were wrong while every check reported OK.
"""

import re
from fractions import Fraction as F

import mido
import pytest

from conftest import needs_lilypond
from drum_agent.charts import compile_spec
from drum_agent.export.lilypond import to_lilypond
from drum_agent.export.midi import build_midi, write_midi
from drum_agent.export.musicxml import to_musicxml
from drum_agent.io_midi import read_midi
from drum_agent.layout import plan_layout
from drum_agent.model import Hit, Measure, Score, TimeSig
from drum_agent.pipeline import export_all
from drum_agent.verify import (expected_articulations, midi_barlines, midi_tempo_at_bars, musicxml_articulations,
                               musicxml_meters, verify_exports)


def spec(sections, **kw):
    d = {"title": "t", "sections": sections}
    d.update(kw)
    return compile_spec(d)


GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
FILL = {"sn": "xxxxxxxx", "bd": "x-------"}


def note_events(mid):
    out, tick = [], 0
    for msg in mido.merge_tracks(mid.tracks):
        tick += msg.time
        out.append((tick, msg))
    return out


# --- repeats must not replay marks the music doesn't repeat --------------------------

def volta_phrases(plan):
    out, cur = [], None
    for b in plan.bars:
        if b.volta_start:
            cur = []
        if cur is not None:
            cur.append(b.index)
        if b.volta_end:
            out.append(cur)
            cur = None
    return out


def test_tempo_change_inside_a_phrase_prevents_a_volta_repeat():
    # A(100) B(140) A B A B: |: A B :| x3 would replay "100" on every pass.
    s = spec([{"tempo": 100, "bars": [GROOVE, {"tempo": 140, **FILL}, GROOVE, FILL, GROOVE, FILL]}])
    plan = plan_layout(s)
    for phrase in volta_phrases(plan):
        assert all(s.measures[i].tempo is None and not s.measures[i].tempo_text for i in phrase[1:])
    assert not plan.bars[0].volta_start


@needs_lilypond
def test_engraved_tempo_map_matches_the_score_with_repeats(tmp_path):
    s = spec([{"tempo": 100, "bars": [GROOVE, {"tempo": 140, **FILL}, GROOVE, FILL, GROOVE, FILL]}])
    report = export_all(s, tmp_path, "t")
    checks = {c.name: c for c in report.comparisons}
    assert checks["engraved score tempo map"].ok and checks["MIDI tempo map"].ok


def test_meter_change_inside_a_repeated_phrase_is_restated_at_the_repeat(tmp_path):
    s = spec([{"tempo": 100, "bars": [{"rd": "xxxx"}]},
              {"bars": [GROOVE, {"time": "3/4", "hh": "x-x-x-", "sn": "--x---"},
                        {"time": "4/4", **GROOVE}, {"time": "3/4", "hh": "x-x-x-", "sn": "--x---"}]},
              {"time": "4/4", "bars": [{"rd": "xxxx"}]}])
    plan = plan_layout(s)
    assert any(b.volta_start for b in plan.bars)
    ly = to_lilypond(s, plan=plan)
    assert re.search(r"\\repeat volta 2 \{\s*\\time 4/4", ly)
    assert musicxml_meters_ok(s, plan, tmp_path)


def musicxml_meters_ok(s, plan, tmp_path):
    p = tmp_path / "m.musicxml"
    p.write_text(to_musicxml(s, plan=plan))
    return musicxml_meters(p) == [f"{m.time_sig.num}/{m.time_sig.den}" for m in s.measures]


@needs_lilypond
def test_meter_change_inside_a_repeat_engraves_without_bar_check_warnings(tmp_path):
    s = spec([{"tempo": 100, "bars": [GROOVE, {"time": "2/4", "sn": "xxxx"}, {"time": "4/4", **GROOVE},
                                      {"time": "2/4", "sn": "xxxx"}]}, {"time": "4/4", "bars": [GROOVE]}])
    report = export_all(s, tmp_path, "m")
    assert report.rendering_ok
    assert not [w for w in report.warnings if "bar check" in w]


# --- hi-hat "+" follows time order across both voices ----------------------------

def test_closed_mark_after_open_hihat_survives_a_pedal_stroke(tmp_path):
    s = spec([{"tempo": 100, "bars": [{"hh": "x-x-x-xo", "hf": "--x-----", "bd": "x-------"},
                                      {"hh": "x-x-x-x-"}]}])
    assert s.hihat_close_marks() == {(1, F(0))}
    p = tmp_path / "h.musicxml"
    p.write_text(to_musicxml(s))
    bar2 = p.read_text().split('<measure number="2"')[1]
    assert "<stopped" in bar2
    assert "hihatclosed4" in to_lilypond(s)


# --- MIDI ------------------------------------------------------------------------

def pickup_score():
    return spec([{"tempo": 100, "bars": [{"length": "1/4", "sn": "xx"}, {"cr": "x---", "sn": "-x-x", "bd": "x-x-"},
                                         {"sn": "-x-x", "bd": "x-x-"}]}])


def test_pickup_gets_its_own_time_signature_in_midi(tmp_path):
    p = write_midi(pickup_score(), tmp_path / "p.mid")
    sigs = [(t, (m.numerator, m.denominator)) for t, m in note_events(mido.MidiFile(p)) if m.type == "time_signature"]
    assert sigs == [(0, (1, 4)), (960, (4, 4))]
    assert midi_barlines(p, F(9, 4)) == [F(0), F(1, 4), F(5, 4)]


def test_midi_pickup_round_trip(tmp_path):
    s = pickup_score()
    p = write_midi(s, tmp_path / "p.mid")
    back, rep = read_midi(p)
    assert rep.pickup == F(1, 4)
    assert back.measures[0].length == F(1, 4)
    assert back.event_list() == s.event_list()


def test_pickup_inferred_from_markers_and_explicit_pickup(tmp_path):
    # A DAW-style file: one 4/4 meter from tick 0, notes starting with a one-beat
    # pickup, markers on the real barlines (tick 960 + k * 3840).
    mid = mido.MidiFile(ticks_per_beat=960)
    meta, tr = mido.MidiTrack(), mido.MidiTrack()
    mid.tracks += [meta, tr]
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100), time=0))
    meta.append(mido.MetaMessage("marker", text="Verse", time=960))
    meta.append(mido.MetaMessage("marker", text="Chorus", time=3840 * 2))
    notes = [(0, 38), (480, 38)] + [(960 + 3840 * b + k * 960, n) for b in range(4) for k, n in
                                     enumerate([36, 38, 36, 38])] + [(960 + 3840 * b, 49) for b in (0, 2)]
    msgs = sorted([(t, 1, n) for t, n in notes] + [(t + 30, 0, n) for t, n in notes])
    last = 0
    for t, on, n in msgs:
        tr.append(mido.Message("note_on", channel=9, note=n, velocity=90 if on else 0, time=t - last))
        last = t
    path = tmp_path / "daw.mid"
    mid.save(path)
    s, rep = read_midi(path)
    assert rep.pickup == F(1, 4) and "markers" in rep.pickup_reason
    assert s.measures[0].length == F(1, 4)
    assert s.measures[1].section == "Verse" and s.measures[3].section == "Chorus"
    assert {(h.pos, h.inst) for h in s.measures[1].hits} >= {(F(0), "kick"), (F(0), "crash"), (F(1, 4), "snare")}
    assert s.status == "unverified_import"
    none, _ = read_midi(path, pickup=F(0))
    assert none.measures[0].length is None  # explicit "no pickup" is respected


def test_mid_bar_meter_change_is_reported(tmp_path):
    mid = mido.MidiFile(ticks_per_beat=960)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    tr.append(mido.MetaMessage("time_signature", numerator=3, denominator=4, time=3840 + 960 + 480))
    for k in range(12):
        tr.append(mido.Message("note_on", channel=9, note=36, velocity=90, time=0 if k == 0 else 960))
    path = tmp_path / "odd.mid"
    mid.save(path)
    _, rep = read_midi(path, pickup=F(0))
    assert any("inside a bar" in w for w in rep.warnings)


def test_hihat_splash_and_half_open_exports():
    s = spec([{"tempo": 100, "bars": [{"hf": "x-------", "hhs": "----x---", "hh": "--h-----"}]}])
    xml = to_musicxml(s)
    splash = xml.split('id="P1-hihat_splash"')[-1].split("</note>")[0]
    assert '<open placement="below"' in splash
    vel = {m.note: m.velocity for _, m in note_events(build_midi(s)) if m.type == "note_on" and m.velocity}
    assert vel[46] < 90  # half-open hi-hat is played softer than a normal stroke


def test_performed_midi_keeps_added_hits_in_their_bar_and_expands_rolls():
    bars = [Measure(TimeSig(4, 4), [Hit(F(0), "kick", time=2.5 + 2 * b)], tempo=120 if b == 0 else None,
                    start_time=2.5 + 2 * b) for b in range(4)]
    bars[2].hits.append(Hit(F(1, 4), "snare"))  # added by hand: no recorded time
    bars[3].hits.append(Hit(F(0), "snare", roll=F(1, 2)))
    s = Score(bars)
    ons = [(t / 1920, m.note) for t, m in note_events(build_midi(s, timing="performed"))
           if m.type == "note_on" and m.velocity]
    added = [t for t, n in ons if n == 38 and t < 8.0]
    assert added == [pytest.approx(7.0)]  # bar 3 starts at 6.5 s; beat 2 at 120 BPM is 0.5 s later
    assert len([t for t, n in ons if n == 38 and t >= 8.0]) == 16


def test_grace_notes_are_never_zero_length_or_merged():
    # A flam on the very first stroke; a drag right after a 16th on the same drum
    # (its first grace starts exactly where the 16th's note-off is).
    s = spec([{"tempo": 100, "bars": [{"sn": "fxd-x---x---x---"}]}])
    events = note_events(build_midi(s))
    sounding = {}
    for t, m in events:
        if m.type == "note_on" and m.velocity:
            assert m.note not in sounding, f"note {m.note} retriggered while sounding at {t}"
            sounding[m.note] = t
        elif m.type in ("note_off", "note_on") and m.note in sounding:
            assert t > sounding.pop(m.note), f"zero-length note at {t}"
    first = [t for t, m in events if m.type == "note_on" and m.velocity]
    assert first[0] == 0 and first.count(0) == 1  # the flam's grace before tick 0 is dropped, not merged


def test_score_without_a_bar_one_tempo_plays_at_120_everywhere(tmp_path):
    s = Score([Measure(TimeSig(4, 4), [Hit(F(0), "kick")]), Measure(TimeSig(4, 4), [Hit(F(0), "kick")], tempo=90)])
    assert s.initial_tempo == 120
    p = write_midi(s, tmp_path / "t.mid")
    assert midi_tempo_at_bars(p, s.measure_starts()) == [pytest.approx(120), pytest.approx(90)]
    assert "\\tempo 4 = 120" in to_lilypond(s)


# --- the checks must catch broken files ------------------------------------------

def test_verification_catches_a_dropped_accent_and_a_wrong_tempo(tmp_path):
    s = spec([{"tempo": 100, "bars": [{"sn": "X-x-g-x-", "bd": "x---x---"}]}])
    xml = tmp_path / "a.musicxml"
    xml.write_text(to_musicxml(s).replace("<accent", "<staccato"))
    assert musicxml_articulations(xml) != expected_articulations(s)
    mid = build_midi(s)
    for m in mid.tracks[0]:
        if m.type == "set_tempo":
            m.tempo = mido.bpm2tempo(110)
    p = tmp_path / "a.mid"
    mid.save(p)
    checks = {c.name: c for c in verify_exports(s, None, xml, p)}
    assert not checks["MusicXML articulations"].ok
    assert not checks["MIDI tempo map"].ok
    assert checks["MusicXML"].ok and checks["MIDI"].ok  # the note events alone would have passed


# --- MIDI import and quantization (second review) ----------------------------------

def midi_file(tmp_path, notes, tpb=960, tempos=((0, 120),), sigs=((0, 4, 4),), markers=(), name="t.mid"):
    """notes: (tick, GM note, velocity); events of each kind keep their given order."""
    mid = mido.MidiFile(ticks_per_beat=tpb)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    ev = [(t, 0, i, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(b))) for i, (t, b) in enumerate(tempos)]
    ev += [(t, 0, 100 + i, mido.MetaMessage("time_signature", numerator=n, denominator=d))
           for i, (t, n, d) in enumerate(sigs)]
    ev += [(t, 0, 200 + i, mido.MetaMessage("marker", text=x)) for i, (t, x) in enumerate(markers)]
    for t, n, v in notes:
        ev += [(t, 2, 0, mido.Message("note_on", channel=9, note=n, velocity=v)),
               (t + 30, 1, 0, mido.Message("note_off", channel=9, note=n, velocity=0))]
    last = 0
    for t, _, _, m in sorted(ev, key=lambda e: (e[0], e[1], e[2])):
        tr.append(m.copy(time=t - last))
        last = t
    p = tmp_path / name
    mid.save(p)
    return p


ROCK = [(b * 3840 + k * 960, n, 90) for b in range(4) for k, n in enumerate([36, 38, 36, 38])]


@pytest.mark.parametrize("time,pickup", [("4/4", "1/8"), ("6/8", "1/8"), ("4/4", "3/16")])
def test_pickups_shorter_than_a_beat_round_trip(tmp_path, time, pickup):
    s = spec([{"time": time, "tempo": 100, "bars": [{"length": pickup, "sn": "x" if pickup == "1/8" else "xxx"},
                                                    {"bd": "x-----" if time == "6/8" else "x---", "sn": "--x---" if time == "6/8" else "--x-"}]}])
    back, rep = read_midi(write_midi(s, tmp_path / "p.mid"))
    assert back.event_list() == s.event_list()


def test_short_real_bar_before_another_meter_is_not_a_pickup(tmp_path):
    s = spec([{"tempo": 100, "time": "2/4", "bars": [{"sn": "xxxx"}]},
              {"time": "6/8", "bars": [{"bd": "x-----", "sn": "---x--"}, {"bd": "x-----", "sn": "---x--"}]}])
    back, rep = read_midi(write_midi(s, tmp_path / "m.mid"))
    assert rep.pickup is None and [str(m.time_sig) for m in back.measures] == ["2/4", "6/8", "6/8"]


def test_one_cue_marker_does_not_rebar_the_song(tmp_path):
    notes = ROCK + [(0, 49, 100)]
    path = midi_file(tmp_path, notes, markers=[(3 * 3840 + 960, "Vocal in")])
    s, rep = read_midi(path)
    assert rep.pickup is None
    assert {(h.pos, h.inst) for h in s.measures[1].hits} == {(F(0), "kick"), (F(1, 4), "snare"),
                                                            (F(1, 2), "kick"), (F(3, 4), "snare")}


def test_final_stroke_played_early_keeps_its_bar(tmp_path):
    path = midi_file(tmp_path, ROCK + [(4 * 3840 - 15, 49, 100)])
    s, _ = read_midi(path)
    assert len(s.measures) == 5 and [(h.pos, h.inst) for h in s.measures[4].hits] == [(F(0), "crash")]


def test_32nd_note_triplets_survive_import(tmp_path):
    s = spec([{"tempo": 80, "bars": [{"sn": "xxxxxxxxxxxx|x|x|x", "bd": "x|-|x|-"}]}])
    back, _ = read_midi(write_midi(s, tmp_path / "t.mid"))
    assert back.event_list() == s.event_list()


def test_swing_reading_leaves_triplet_and_16th_fills_alone():
    from drum_agent.quantize import BarDef, Onset, QuantizeOptions, quantize
    beat = 0.5
    onsets = []
    for b in range(8):  # swung ride: beat, swung offbeat
        for q in range(4):
            t0 = (b * 4 + q) * beat
            onsets += [Onset(t0, "ride"), Onset(t0 + beat * 2 / 3, "ride")]
    t = 32 * beat
    onsets += [Onset(t + q * beat / 3, "snare") for q in range(12)]  # a bar of 8th-note triplets
    t = 36 * beat
    onsets += [Onset(t + q * beat / 4, "snare") for q in range(16)]  # a bar of straight 16ths
    bars = [BarDef(4 * i, TimeSig(4, 4), 4) for i in range(10)]
    res = quantize(onsets, [i * beat for i in range(41)], bars, QuantizeOptions())
    assert res.feel == "swing"
    assert sorted(h.pos for h in res.measures[8].hits) == [F(k, 12) for k in range(12)]
    assert sorted(h.pos for h in res.measures[9].hits) == [F(k, 16) for k in range(16)]
    assert sorted(h.pos for h in res.measures[0].hits) == [F(k, 8) for k in range(8)]  # swung 8ths written straight


def test_tempo_jump_is_marked_on_the_bar_where_it_happens():
    from drum_agent.quantize import QuantizeOptions, _apply_tempo_marks
    ms = [Measure(TimeSig(4, 4), []) for _ in range(8)]
    _apply_tempo_marks(ms, [120.0] * 4 + [150.0] * 4, QuantizeOptions())
    assert [(i + 1, m.tempo) for i, m in enumerate(ms) if m.tempo] == [(1, 120.0), (5, 150.0)]


def test_the_later_tempo_event_at_a_tick_wins(tmp_path):
    s, _ = read_midi(midi_file(tmp_path, ROCK, tempos=((0, 120), (0, 140))))
    assert s.measures[0].tempo == 140


def test_no_32nds_keeps_16ths_in_cut_time(tmp_path):
    from drum_agent.quantize import QuantizeOptions
    s = spec([{"tempo": 70, "time": "2/2", "bars": [{"hh": "x" * 16, "bd": "x-------x-------"}] * 2}])
    back, _ = read_midi(write_midi(s, tmp_path / "c.mid"), options=QuantizeOptions(allow_32nds=False))
    assert back.event_list() == s.event_list()


def test_count_in_clicks_are_trimmed(tmp_path):
    clicks = [(k * 960, 33, 70) for k in range(8)]
    s, rep = read_midi(midi_file(tmp_path, clicks + [(t + 2 * 3840, n, v) for t, n, v in ROCK]))
    assert rep.trimmed_leading_bars == 2 and s.measures[0].hits and rep.unmapped == {33: 8}


def test_tempo_mapped_jitter_gets_one_mark_and_mid_bar_changes_warn(tmp_path):
    jitter = tuple((k * 960, 120 + (0.6 if k % 2 else -0.5)) for k in range(16))
    s, _ = read_midi(midi_file(tmp_path, ROCK, tempos=jitter))
    assert sum(m.tempo is not None for m in s.measures) == 1
    s, rep = read_midi(midi_file(tmp_path, ROCK, tempos=((0, 100), (2 * 3840 + 1920, 140)), name="m.mid"))
    assert any("inside bar 3" in w for w in rep.warnings)


def test_flams_and_drags_round_trip_through_midi(tmp_path):
    s = spec([{"tempo": 100, "bars": [{"sn": "--d---f-", "bd": "x---x---"}, {"sn": "--d---F-", "bd": "x---x---"}]}])
    back, rep = read_midi(write_midi(s, tmp_path / "g.mid"))
    assert back.event_list() == s.event_list()
    got = {(i, h.pos): (h.flam, h.drag, h.accent) for i, m in enumerate(back.measures) for h in m.hits if h.inst == "snare"}
    assert got[(0, F(1, 4))] == (False, True, False) and got[(0, F(3, 4))] == (True, False, False)
    assert got[(1, F(3, 4))][0] is True and rep.graces_folded == 6


# --- notation (second review) --------------------------------------------------------

def _svg_positions(ly_path, tmp_path):
    """x positions of barlines, time signatures and grace noteheads, per system (y)."""
    import subprocess
    from drum_agent.export.render import find_lilypond
    ly = ly_path.read_text().replace(
        "    \\Score\n", "    \\Score\n"
        "    \\override BarLine.output-attributes = #'((class . \"BarLine\"))\n"
        "    \\override TimeSignature.output-attributes = #'((class . \"TimeSig\"))\n", 1)
    # (a grace under a cymbal voice is written stems up: tag it after that override)
    for g in ("\\acciaccatura {", "\\appoggiatura {", "\\override Stem.direction = #UP"):
        ly = ly.replace(g, g + " \\once \\override NoteHead.output-attributes = #'((class . \"Grace\"))")
    src = tmp_path / "tagged.ly"
    src.write_text(ly)
    subprocess.run([find_lilypond(), "-dbackend=svg", "-o", str(tmp_path / "tagged"), str(src)],
                   capture_output=True, check=True)
    svg = (tmp_path / "tagged.svg").read_text()
    rows: dict[int, list] = {}
    for m in re.finditer(r'<g class="(BarLine|TimeSig|Grace)"[^>]*>(.*?)</g>', svg, re.S):
        x, y = map(float, re.search(r'translate\(([\d.\-]+),\s*([\d.\-]+)\)', m.group(2)).groups())
        rows.setdefault(round(y), []).append((x, m.group(1)))
    return [sorted(r) for _, r in sorted(rows.items())]


@needs_lilypond
def test_downbeat_flam_and_drag_are_engraved_after_the_barline_and_meter(tmp_path):
    # LilyPond aligns grace time across voices: without matching grace skips in the
    # other streams, the barline, time signature and line break came before the graces.
    s = spec([{"label": "A", "bars": [{"sn": "f-x-x-x-", "bd": "x---x---"}, GROOVE,
                                      {"time": "3/4", "sn": "f-x-x-", "bd": "x-----"}, {"time": "4/4", **GROOVE}]},
              {"label": "B", "bars": [{"sn": "d-x-x-x-", "cr": "x-------", "bd": "x-------"}, GROOVE]}], tempo=100)
    report = export_all(s, tmp_path, "s")
    assert report.rendering_ok, [c.summary() for c in report.comparisons if not c.ok]
    ly = (tmp_path / "s.ly").read_text()
    glob = re.search(r"globalMusic = \{(.*?)\n\}", ly, re.S).group(1)
    assert glob.count("\\tag #'graces \\grace { s8 }") == 2 and "\\tag #'graces \\grace { s16 s16 }" in glob
    systems = _svg_positions(tmp_path / "s.ly", tmp_path)
    first = systems[0]
    # System 1: the opening flam follows the 4/4 time signature; the 3/4 bar's flam
    # follows its own time signature (one time signature per meter change, no stray one).
    kinds = [k for _, k in first]
    assert kinds.index("Grace") > kinds.index("TimeSig")
    ts = [x for x, k in first if k == "TimeSig"]
    graces = [x for x, k in first if k == "Grace"]
    assert len(graces) == 2 and graces[1] > ts[1]
    # Section B starts a new system and its drag is on that system, not at the end of system 1.
    # (only the first grace notehead of the drag is tagged)
    assert sum(k == "Grace" for _, k in systems[1]) == 1


def test_downbeat_grace_skip_covers_a_simile_run_and_a_pickup():
    from drum_agent.export.lilypond import downbeat_grace_skip
    from drum_agent.rhythm import spell_measure
    s = spec([{"bars": [{"sn": "f-x-x-x-", "bd": "x---x---"}] * 3}], tempo=100)
    ly = to_lilypond(s)
    assert ly.count("\\tag #'graces \\grace { s8 }") >= 1
    pick = spec([{"bars": [{"sn": "f-"}, GROOVE]}], tempo=100, pickup="1/4")
    from drum_agent.kit import DEFAULT_KIT
    assert downbeat_grace_skip(spell_measure(pick.measures[0]).voices[DEFAULT_KIT["snare"].voice]) == "s8"
    assert "\\tag #'graces \\grace { s8 }" in to_lilypond(pick)


A = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
B = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x--xx---"}
C = {"rd": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x-x-"}
D = {"rd": "x-x-x-x-", "sn": "--x-xxxx", "bd": "x---x---"}
REST = {"hh": "--------"}


def systems(plan):
    lines = []
    for b in plan.bars:
        if b.line_break or not lines:
            lines.append([])
        lines[-1].append(b.index)
    return lines


@pytest.mark.parametrize("bars,phrase,times", [
    ([A, B] * 4, 2, 4), ([A, B] * 8, 2, 8), ([A, B, C, D] * 4, 4, 4),
    ([A, B, A, B, A, B, A, C] * 2, 8, 2),  # the 8-bar phrase saves more than |: A B :| x3
])
def test_repeats_use_the_phrase_that_saves_the_most_bars(bars, phrase, times):
    plan = plan_layout(spec([{"label": "V", "bars": bars}]))
    assert [len(p) for p in volta_phrases(plan)] == [phrase]
    assert plan.bars[0].volta_times == times


def test_empty_bars_become_one_multi_bar_rest(tmp_path):
    s = spec([{"label": "Intro", "bars": [REST] * 6}, {"label": "Verse", "bars": [A, B]}], tempo=100)
    plan = plan_layout(s)
    assert plan.bars[0].rest_run == 6 and all(b.in_rest for b in plan.bars[1:6])
    assert not any(b.percent for b in plan.bars)
    ly = to_lilypond(s)
    assert "R1*6/1" in ly and "skipBars = ##t" in ly and "\\repeat percent" not in ly
    assert "<multiple-rest>6</multiple-rest>" in to_musicxml(s)
    report = export_all(s, tmp_path, "s")
    assert report.rendering_ok, [c.summary() for c in report.comparisons if not c.ok]


def test_multi_bar_rests_split_at_marks_and_meters_and_never_cross_a_line():
    s = spec([{"label": "Intro", "bars": [REST] * 3 + [{"tempo": 90, **REST}, REST]},
              {"label": "Tacet", "bars": [REST] * 2 + [{"time": "3/4", "hh": "------"}] * 2},
              {"label": "Long", "time": "4/4", "bars": [REST] * 12 + [A]}], tempo=100)
    plan = plan_layout(s)
    runs = [(b.index, b.rest_run) for b in plan.bars if b.rest_run]
    assert runs == [(0, 3), (3, 2), (5, 2), (7, 2), (9, 12)]
    for line in systems(plan):
        assert not plan.bars[[b.index for b in plan.bars].index(line[0])].in_rest
    assert plan.expand() == list(range(len(s.measures)))
    assert not any(b.rest_run for b in plan_layout(s, repeats="none").bars)  # everything written out


@needs_lilypond
def test_multi_bar_rest_inside_a_repeated_phrase_engraves(tmp_path):
    s = spec([{"bars": [A, REST, REST, B] * 2 + [C]}], tempo=100)
    plan = plan_layout(s)
    assert volta_phrases(plan) == [[0, 1, 2, 3]] and plan.bars[1].rest_run == 2
    report = export_all(s, tmp_path, "s")
    assert report.rendering_ok, [c.summary() for c in report.comparisons if not c.ok]


@pytest.mark.parametrize("bar,key", [
    ({"hh": "x-x-x-xo", "sn": "--x---x-", "bd": "x---x---"}, False),  # open hi-hat is still the hi-hat
    ({"xs": "x--x--x---x--x--", "bd": "x--xx--xx--xx--x", "hf": "--x---x---x---x-"}, True),  # 3 instruments
    ({"rd": "x-xxx-xx", "sn": "---x----", "bd": "x---x---"}, True),
    ({"t1": "x-x-x-x-", "ft": "-x-x-x-x", "bd": "x---x---"}, True),
])
def test_drum_key_is_printed_whenever_more_than_kick_snare_and_hihat_is_used(bar, key):
    s = spec([{"bars": [bar]}])
    assert ("Drum Key" in to_lilypond(s)) == key


@needs_lilypond
def test_a_big_kit_drum_key_wraps_inside_the_page(tmp_path):
    import subprocess
    from drum_agent.export.render import find_lilypond
    s = spec([{"bars": [
        {"hh": "x-x-x-xo", "sn": "--x---x-", "bd": "x---x-x-", "cr": "x-------", "hf": "--x---x-"},
        {"rd": "x-x-x-x-", "rb": "-x------", "sn": "--x---x-", "bd": "x---x---", "cn": "-------x"},
        {"t1": "xx------", "t2": "--xx----", "ft": "----xx--", "ft2": "------xx", "bd": "x---x---"},
        {"spl": "x-------", "c2": "----x---", "rs": "--x---x-", "bd": "x---x---", "hh": "-x-h-x--"}]}])
    assert len(s.instruments_used()) == 17
    report = export_all(s, tmp_path, "s")
    assert report.rendering_ok and not report.warnings
    ly = (tmp_path / "s.ly").read_text().replace(
        "\\new Lyrics \\with {", "\\new Lyrics \\with { \\override LyricText.output-attributes = #'((class . \"KeyLabel\"))", 1)
    (tmp_path / "t.ly").write_text(ly)
    subprocess.run([find_lilypond(), "-dbackend=svg", "-o", str(tmp_path / "t"), str(tmp_path / "t.ly")],
                   capture_output=True, check=True)
    svg = (tmp_path / "t.svg").read_text()
    width = float(re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+)', svg).group(1))
    rows: dict[int, list[float]] = {}
    for m in re.finditer(r'class="KeyLabel"', svg):
        x, y = map(float, re.search(r'translate\(([\d.\-]+),\s*([\d.\-]+)\)', svg[m.end():m.end() + 800]).groups())
        rows.setdefault(round(y), []).append(x)
    assert len(rows) >= 2  # wrapped onto a second line
    assert max(max(xs) for xs in rows.values()) < 0.85 * width  # labels start well inside the page


@needs_lilypond
@pytest.mark.parametrize("chart", ["library/grooves/g56_calypso_soca.yaml", "tests/cases/05_hihat_open_closed.yaml"])
def test_section_box_sits_above_the_tempo_mark_it_starts_with(chart, tmp_path):
    # Open hi-hat circles over the first notes lift the tempo mark; the box at the line start
    # then stayed down by the staff, under or beside it (G56 "Soca", case 05 "A"), while
    # every other chart has the box on top.
    import subprocess
    from conftest import ROOT
    from drum_agent.charts import load_any
    from drum_agent.export.render import find_lilypond
    report = export_all(load_any(ROOT / chart), tmp_path, "s")
    assert report.rendering_ok
    ly = (tmp_path / "s.ly").read_text().replace(
        "    \\Score\n", "    \\Score\n"
        "    \\override SectionLabel.output-attributes = #'((class . \"Box\"))\n"
        "    \\override MetronomeMark.output-attributes = #'((class . \"Tempo\"))\n", 1)
    (tmp_path / "t.ly").write_text(ly)
    subprocess.run([find_lilypond(), "-dbackend=svg", "-o", str(tmp_path / "t"), str(tmp_path / "t.ly")],
                   capture_output=True, check=True)
    svg = (tmp_path / "t.svg").read_text()

    def baseline(cls):  # the text baseline of the first grob tagged cls
        group = re.search(rf'<g class="{cls}">(.*?)</a>\s*</g>', svg, re.S).group(1)
        return max(float(y) for y in re.findall(r'translate\([\d.\-]+,\s*([\d.\-]+)\)">\s*<text', group))
    assert baseline("Box") < baseline("Tempo")  # SVG y grows downward


def test_short_eighth_meters_are_beamed_as_one_beat_with_a_dotted_quarter_mark():
    from drum_agent.rhythm import spell_measure
    assert [TimeSig.parse(t).groups() for t in ("2/8", "3/8", "4/8")] == [(2,), (3,), (2, 2)]
    s = spec([{"time": "3/8", "bars": [{"hh": "xxx", "bd": "x--"}]}], tempo=120)
    beams = [dict(t.beams) for t in spell_measure(s.measures[0]).voices[1]]
    assert beams == [{1: "begin"}, {1: "continue"}, {1: "end"}]
    assert "\\tempo 4. = 80" in to_lilypond(s)
    xml = to_musicxml(s)
    assert "<beat-unit-dot />" in xml and "<per-minute>80</per-minute>" in xml
    assert "\\tempo 8. = 160" in to_lilypond(spec([{"time": "6/16", "bars": [{"hh": "xxxxxx"}]}], tempo=120))


def test_a_section_starts_a_new_system_unless_it_is_short():
    fill = {"sn": "xxxxxxxx", "bd": "x-------"}
    hit = {"cr": "x-------", "sn": "x-------", "bd": "x-------"}
    s = spec([{"label": "Intro", "bars": [A, B, A, fill]}, {"label": "Break", "bars": [hit]},
              {"label": "Verse", "bars": [A, B, A, fill]}])
    # The one-bar break joins the end of the intro's line rather than sitting alone on
    # a stretched system, and the verse's phrase is not split.
    assert systems(plan_layout(s)) == [[0, 1, 2, 3, 4], [5, 6, 7, 8]]
    s = spec([{"label": "Intro", "bars": [A, B] * 2}, {"label": "Break", "bars": [hit]},
              {"label": "Verse", "bars": [A, B, A, fill]}])
    assert systems(plan_layout(s))[1:] == [[4], [5, 6, 7, 8]]  # never appended after a repeat
    s = spec([{"label": "Hit", "bars": [{"cr": "x-------", "bd": "x-------"}]},
              {"label": "Tag", "bars": [A, fill]}, {"label": "Out", "bars": [A, B, A, fill]}])
    assert systems(plan_layout(s)) == [[0, 1, 2], [3, 4, 5, 6]]  # the whole short section fits


@needs_lilypond
def test_lower_voice_accents_and_graces_clear_the_stems_and_beams(tmp_path):
    # Under a cymbal voice: accents sat on the stem end, where a beam sloping down from it
    # (G12 "snare8->[ kick8]") or the next 16th rest (G16) ran through them, and the flams'
    # grace notes took the stems-down direction, their slurs crossing stems and beams (G67).
    from conftest import ROOT
    from drum_agent.charts import load_any
    ly = to_lilypond(load_any(ROOT / "library/grooves/g67_flam_tom_fill.yaml"))
    down = ly.split("downMusic = ")[1].split("\n}\n")[0]
    assert down.split("\\autoBeamOff")[1].lstrip().startswith("\\override Script.padding = #0.7")
    assert "\\slashedGrace { \\temporary \\override Stem.direction = #UP snare8 \\revert Stem.direction }" in down
    assert "\\acciaccatura" not in ly and "\\appoggiatura" not in ly
    # A one-voice part (a rudiment sheet: stems up, accents above) keeps the slurred grace
    # notes and the usual accent distance.
    rud = to_lilypond(load_any(ROOT / "library/rudiments/r20_flam.yaml"))
    assert "\\acciaccatura { snare8 }" in rud and "Script.padding" not in rud
    report = export_all(load_any(ROOT / "library/grooves/g67_flam_tom_fill.yaml"), tmp_path, "s")
    assert report.rendering_ok and not report.warnings
