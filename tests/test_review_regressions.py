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
