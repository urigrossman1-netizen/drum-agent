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
