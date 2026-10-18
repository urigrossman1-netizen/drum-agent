"""Rock Band / Clone Hero drum chart import (drum_agent/gamechart.py).

Every fixture is an original pattern built here: notes.mid files with mido and
notes.chart files as text. Nothing touches the network.
"""

import json
import sys
from collections import namedtuple

import mido
import pytest

from conftest import needs_lilypond
from drum_agent.cli import main
from drum_agent.gamechart import (PAD_TO_KIT, SIMPLIFIED, GameChartError, read_gamechart, section_name)
from drum_agent.model import Score
from drum_agent.pipeline import ExportOptions, export_all

TPB = 480  # MIDI ticks per quarter
BAR = 4 * TPB
EIGHTH, SIXTEENTH = TPB // 2, TPB // 4
RES = 192  # .chart ticks per quarter
CBAR = 4 * RES

KICK, RED, YELLOW, BLUE, GREEN = 96, 97, 98, 99, 100  # Expert
TOM_Y, TOM_B, TOM_G = 110, 111, 112
PRO = [(100 * BAR, 100 * BAR + 10, TOM_Y)]  # a tom marker over no note: makes a file a pro chart


# ---- fixtures ---------------------------------------------------------------------

def rb_midi(path, notes, *, markers=(), texts=(), events=(), tempos=((0, 120),), meters=((0, 4, 4),),
            tpb=TPB, drum_track="PART DRUMS"):
    """A Rock Band style notes.mid: conductor track, the drum track, an EVENTS track.

    `notes`: (tick, note) or (tick, note, velocity); `markers`: (start, end, note)
    tom markers; `texts`: drum-track text events; `events`: EVENTS-track texts.
    """
    def track(name, timed):
        tr = mido.MidiTrack()
        if name:
            tr.append(mido.MetaMessage("track_name", name=name, time=0))
        prev = 0
        for tick, _, msg in sorted(timed, key=lambda e: (e[0], e[1])):
            tr.append(msg.copy(time=tick - prev))
            prev = tick
        return tr

    conductor = [(t, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))) for t, bpm in tempos]
    conductor += [(t, 1, mido.MetaMessage("time_signature", numerator=n, denominator=d)) for t, n, d in meters]
    drums = [(t, 0, mido.MetaMessage("text", text=x)) for t, x in texts]
    for item in notes:
        tick, note, vel = (*item, 100)[:3]
        drums.append((tick, 2, mido.Message("note_on", note=note, velocity=vel)))
        drums.append((tick + tpb // 8, 1, mido.Message("note_off", note=note, velocity=0)))
    for start, end, note in markers:
        drums.append((start, 2, mido.Message("note_on", note=note, velocity=100)))
        drums.append((end, 1, mido.Message("note_off", note=note, velocity=0)))
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    mid.tracks += [track(None, conductor), track(drum_track, drums),
                   track("EVENTS", [(t, 0, mido.MetaMessage("text", text=x)) for t, x in events])]
    mid.save(str(path))
    return path


def chart_file(path, tracks, *, sync=("0 = TS 4", "0 = B 120000"), events=(), song=None, resolution=RES):
    """A Clone Hero notes.chart. `tracks`: {"ExpertDrums": [(tick, lane), ...]}."""
    head = {"Resolution": resolution, "Offset": 0, **(song or {})}
    lines = ["[Song]", "{"] + [f'  {k} = {json.dumps(v) if isinstance(v, str) else v}' for k, v in head.items()]
    lines += ["}", "[SyncTrack]", "{"] + [f"  {s}" for s in sync] + ["}"]
    lines += ["[Events]", "{"] + [f'  {t} = E "{x}"' for t, x in events] + ["}"]
    for name, notes in tracks.items():
        lines += [f"[{name}]", "{"]
        for item in sorted(notes, key=lambda n: (n[0], str(n[1]))):
            tick, what = item
            lines.append(f"  {tick} = E {what[2:]}" if isinstance(what, str) else f"  {tick} = N {what} 0")
        lines += ["}"]
    path.write_text("\n".join(lines) + "\n")
    return path


def bar(score, i, flags=False):
    """Bar i (0-based) as sorted (position, instrument[, accent/ghost]) tuples."""
    out = []
    for h in sorted(score.measures[i].hits, key=lambda h: (h.pos, h.inst)):
        item = (str(h.pos), h.inst)
        if flags:
            item += ("accent" if h.accent else "ghost" if h.ghost else "",)
        out.append(item)
    return out


def rock_bar(start=0, kick=KICK, snare=RED, hat=YELLOW):
    """8th hats, snare on 2 and 4, kick on 1 and 3."""
    notes = [(start + k * EIGHTH, hat) for k in range(8)]
    notes += [(start + TPB, snare), (start + 3 * TPB, snare), (start, kick), (start + 2 * TPB, kick)]
    return notes


ROCK = [("0", "hihat"), ("0", "kick"), ("1/8", "hihat"), ("1/4", "hihat"), ("1/4", "snare"),
        ("3/8", "hihat"), ("1/2", "hihat"), ("1/2", "kick"), ("5/8", "hihat"), ("3/4", "hihat"),
        ("3/4", "snare"), ("7/8", "hihat")]


# ---- MIDI lanes: cymbals, tom markers, pro drums ------------------------------------

def tom_fill_bar(start):
    """Two 8ths on each tom (yellow, blue, green, each under its marker), then the blue cymbal."""
    notes, markers = [], []
    for beat, (note, marker) in enumerate([(YELLOW, TOM_Y), (BLUE, TOM_B), (GREEN, TOM_G)]):
        t = start + beat * TPB
        notes += [(t, note), (t + EIGHTH, note)]
        markers.append((t, t + TPB - 10, marker))  # one marker spans both strokes
    notes += [(start + 3 * TPB, BLUE), (start + 3 * TPB, KICK)]
    return notes, markers


def test_midi_pro_drums_cymbals_unless_a_tom_marker_sounds(tmp_path):
    fill, markers = tom_fill_bar(BAR)
    notes = rock_bar() + [(0, GREEN)] + fill
    score, rep = read_gamechart(rb_midi(tmp_path / "notes.mid", notes, markers=markers))
    assert rep.pro and "tom markers" in rep.pro_reason
    assert bar(score, 0) == [("0", "crash")] + ROCK
    assert bar(score, 1) == [("0", "tom1"), ("1/8", "tom1"), ("1/4", "tom2"), ("3/8", "tom2"),
                             ("1/2", "floor_tom"), ("5/8", "floor_tom"), ("3/4", "kick"), ("3/4", "ride")]
    assert (score.chart_type, score.status) == ("full_transcription", "unverified_import")
    assert score.analysis["notes"][0] == SIMPLIFIED


def test_pad_table_uses_kit_instruments():
    from drum_agent.kit import DEFAULT_KIT
    assert set(PAD_TO_KIT.values()) <= set(DEFAULT_KIT.ids())
    assert PAD_TO_KIT["yellow_cymbal"] == "hihat" and PAD_TO_KIT["green_tom"] == "floor_tom"


def test_midi_without_markers_is_a_non_pro_chart_of_toms(tmp_path):
    notes = rock_bar() + [(0, GREEN), (3 * TPB + EIGHTH, BLUE)]
    score, rep = read_gamechart(rb_midi(tmp_path / "notes.mid", notes))
    assert not rep.pro and "no tom markers" in rep.pro_reason
    assert {i for _, i in bar(score, 0)} == {"tom1", "snare", "kick", "floor_tom", "tom2"}
    assert any("relabel" in w for w in rep.warnings)


def test_no_pro_reads_toms_even_with_markers(tmp_path):
    fill, markers = tom_fill_bar(0)
    path = rb_midi(tmp_path / "notes.mid", rock_bar(BAR) + fill, markers=markers)
    score, rep = read_gamechart(path, pro=False)
    assert not rep.pro and "--no-pro" in rep.pro_reason
    assert {i for _, i in bar(score, 1)} == {"tom1", "snare", "kick"}
    assert ("3/4", "tom2") in bar(score, 0)  # the unmarked blue is a tom too
    assert not any("relabel" in w for w in rep.warnings)  # the user chose this reading


def test_song_ini_pro_drums_reads_cymbals_without_markers(tmp_path):
    rb_midi(tmp_path / "notes.mid", rock_bar())
    (tmp_path / "song.ini").write_text("[song]\nname = Ini Groove\npro_drums = True\n")
    score, rep = read_gamechart(tmp_path)
    assert rep.pro and "song.ini" in rep.pro_reason
    assert bar(score, 0) == ROCK


def test_markers_and_animation_notes_are_not_strokes(tmp_path):
    # Animation notes (24-51), solo (103), overdrive (116), fill lanes (120-124) and the
    # drum-roll lane (126) share the track with the gems; none of them is a stroke.
    extra = [(0, n) for n in (24, 36, 51, 103, 116, 120, 121, 122, 123, 124, 126)]
    path = rb_midi(tmp_path / "notes.mid", rock_bar() + extra, markers=PRO, texts=[(0, "[idle]"), (0, "[play]")])
    score, rep = read_gamechart(path)
    assert bar(score, 0) == ROCK and rep.difficulties == ["expert"]


def test_chart_star_power_events_and_flam_flags_are_skipped(tmp_path):
    notes = [(0, 0), (0, 1), (0, 109), (RES, 1)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes})
    text = path.read_text().replace("[ExpertDrums]\n{\n", "[ExpertDrums]\n{\n  0 = S 2 768\n  0 = E solo\n")
    path.write_text(text)
    score, rep = read_gamechart(path)
    assert bar(score, 0) == [("0", "kick"), ("0", "snare"), ("1/4", "snare")]
    assert any("[109]" in w for w in rep.warnings)


# ---- .chart lanes and flags -------------------------------------------------------

def test_chart_lanes_are_toms_unless_a_cymbal_flag_is_set(tmp_path):
    q = RES
    notes = [(0, 0), (0, 2), (0, 66), (q, 1), (q, 3), (q, 67), (2 * q, 4), (2 * q, 68),
             (3 * q, 2), (3 * q, 1), (3 * q + q // 2, 3), (3 * q + q // 2, 4), (3 * q + q // 2, 0)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes})
    score, rep = read_gamechart(path)
    assert rep.pro and "cymbal flags" in rep.pro_reason and rep.format == "chart"
    assert bar(score, 0) == [("0", "hihat"), ("0", "kick"), ("1/4", "ride"), ("1/4", "snare"),
                             ("1/2", "crash"), ("3/4", "snare"), ("3/4", "tom1"),
                             ("7/8", "floor_tom"), ("7/8", "kick"), ("7/8", "tom2")]
    score, rep = read_gamechart(path, pro=False)
    assert {i for _, i in bar(score, 0)} == {"tom1", "tom2", "floor_tom", "snare", "kick"}


def test_chart_accent_and_ghost_flags(tmp_path):
    q = RES
    notes = [(0, 1), (0, 34), (q, 1), (q, 40), (2 * q, 2), (2 * q, 66), (2 * q, 35),
             (3 * q, 3), (3 * q, 42), (3 * q, 0), (3 * q + q // 2, 1)]
    score, _ = read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}))
    assert bar(score, 0, flags=True) == [("0", "snare", "accent"), ("1/4", "snare", "ghost"),
                                         ("1/2", "hihat", "accent"), ("3/4", "kick", ""),
                                         ("3/4", "tom2", "ghost"), ("7/8", "snare", "")]


# ---- Expert+ kick -----------------------------------------------------------------

def test_expert_plus_kick_is_a_kick_in_both_formats(tmp_path):
    notes = [(0, KICK), (0, 95), (EIGHTH, 95), (TPB, RED)]
    score, _ = read_gamechart(rb_midi(tmp_path / "notes.mid", notes))
    assert bar(score, 0) == [("0", "kick"), ("1/8", "kick"), ("1/4", "snare")]
    assert score.analysis["merged_duplicates"] == 1  # 95 and 96 together are one stroke
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": [(0, 0), (0, 32), (RES // 2, 32), (RES, 1)]})
    score, _ = read_gamechart(path)
    assert bar(score, 0) == [("0", "kick"), ("1/8", "kick"), ("1/4", "snare")]


# ---- dynamics ---------------------------------------------------------------------

def test_midi_dynamics_need_the_enable_event(tmp_path):
    notes = [(0, KICK, 127), (0, RED, 127), (TPB, RED, 1), (2 * TPB, RED, 100), (3 * TPB, YELLOW, 127)]
    plain = rb_midi(tmp_path / "plain.mid", notes)
    score, rep = read_gamechart(plain)
    assert not rep.dynamics
    assert all(not h.accent and not h.ghost for m in score.measures for h in m.hits)

    dyn = rb_midi(tmp_path / "dyn.mid", notes, texts=[(0, "[ENABLE_CHART_DYNAMICS]")])
    score, rep = read_gamechart(dyn, pro=False)
    assert rep.dynamics
    assert bar(score, 0, flags=True) == [("0", "kick", ""), ("0", "snare", "accent"), ("1/4", "snare", "ghost"),
                                         ("1/2", "snare", ""), ("3/4", "tom1", "accent")]


# ---- disco flip -------------------------------------------------------------------

def test_disco_flip_swaps_red_and_the_yellow_cymbal_for_its_difficulty(tmp_path):
    # In the flipped bar the hi-hat pattern is charted on red and the snare on yellow.
    notes = rock_bar() + rock_bar(BAR, snare=YELLOW, hat=RED) + rock_bar(2 * BAR)
    texts = [(BAR, "[mix 3 drums0d]"), (2 * BAR, "[mix 3 drums0]"), (0, "[mix 2 drums0d]")]
    path = rb_midi(tmp_path / "notes.mid", notes, texts=texts, markers=PRO)
    score, rep = read_gamechart(path)
    assert rep.pro
    assert bar(score, 0) == bar(score, 1) == bar(score, 2) == ROCK
    # The Hard flip (mix 2) leaves Expert alone; "dnoflip" doesn't flip either.
    path = rb_midi(tmp_path / "noflip.mid", rock_bar(), texts=[(0, "[mix 3 drums0dnoflip]")], markers=PRO)
    score, _ = read_gamechart(path)
    assert bar(score, 0) == ROCK


def test_disco_flip_is_left_alone_without_pro_drums(tmp_path):
    path = rb_midi(tmp_path / "notes.mid", rock_bar(), texts=[(0, "[mix 3 drums0d]")])
    score, rep = read_gamechart(path)
    assert {i for _, i in bar(score, 0)} == {"tom1", "snare", "kick"}
    assert any("disco" in w for w in rep.warnings)


# ---- tempo and meter --------------------------------------------------------------

def test_tempo_and_meter_changes_come_from_the_conductor_track(tmp_path):
    three = BAR * 3 // 4
    notes = rock_bar() + [(BAR + k * TPB, KICK) for k in range(3)]  # a 3/4 bar of kicks
    notes += [(BAR + three + k * EIGHTH, YELLOW) for k in range(6)]  # then 6/8 (no markers: toms)
    notes += [(BAR + three, KICK), (BAR + three + 3 * EIGHTH, RED)]
    meters = [(0, 4, 4), (BAR, 3, 4), (BAR + three, 6, 8)]
    tempos = [(0, 120), (BAR + three, 90)]
    score, _ = read_gamechart(rb_midi(tmp_path / "notes.mid", notes, meters=meters, tempos=tempos))
    assert [str(m.time_sig) for m in score.measures] == ["4/4", "3/4", "6/8"]
    assert [m.tempo for m in score.measures] == [120.0, None, 90.0]
    assert bar(score, 1) == [("0", "kick"), ("1/4", "kick"), ("1/2", "kick")]
    assert bar(score, 2) == [("0", "kick"), ("0", "tom1"), ("1/8", "tom1"), ("1/4", "tom1"),
                             ("3/8", "snare"), ("3/8", "tom1"), ("1/2", "tom1"), ("5/8", "tom1")]


def test_tempo_change_inside_a_beat_keeps_the_subdivision(tmp_path):
    # A beat-mapped chart: the tempo drops a 16th into beat 1. The 8th stays an 8th.
    notes = [(0, KICK), (EIGHTH, RED), (TPB, KICK), (2 * TPB, KICK)]
    score, rep = read_gamechart(rb_midi(tmp_path / "notes.mid", notes, tempos=[(0, 200), (SIXTEENTH, 50)]))
    assert bar(score, 0) == [("0", "kick"), ("1/8", "snare"), ("1/4", "kick"), ("1/2", "kick")]
    assert any("inside bars" in w for w in rep.warnings)


def test_chart_sync_track_tempo_and_compound_meter(tmp_path):
    q = RES
    six = 3 * q  # a 6/8 bar is three quarters long
    notes = [(k * q, 0) for k in range(4)] + [(CBAR + k * q // 2, 2) for k in range(6)] + [(CBAR, 0),
                                                                                         (CBAR + 3 * q // 2, 1)]
    notes += [(CBAR + six, 0), (CBAR + six + q // 2, 1)]
    sync = ["0 = TS 4", "0 = B 100000", f"{CBAR} = TS 6 3", f"{CBAR} = B 150000", f"{CBAR + six} = TS 3"]
    score, _ = read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}, sync=sync))
    assert [str(m.time_sig) for m in score.measures] == ["4/4", "6/8", "3/4"]
    assert [m.tempo for m in score.measures] == [100.0, 150.0, 150.0]  # 6/8 -> 3/4: a new beat unit, a new mark
    assert bar(score, 1) == [("0", "kick"), ("0", "tom1"), ("1/8", "tom1"), ("1/4", "tom1"), ("3/8", "snare"),
                             ("3/8", "tom1"), ("1/2", "tom1"), ("5/8", "tom1")]
    assert bar(score, 2) == [("0", "kick"), ("1/8", "snare")]


def test_meter_event_inside_a_bar_cuts_it_short(tmp_path):
    q = RES
    notes = [(0, 0), (q, 1), (2 * q, 0), (3 * q, 0), (4 * q, 1)]
    sync = ["0 = TS 4", "0 = B 120000", f"{3 * q} = TS 4"]  # charted three beats into bar 1
    score, rep = read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}, sync=sync))
    assert [str(m.time_sig) for m in score.measures] == ["3/4", "4/4"]
    assert bar(score, 1) == [("0", "kick"), ("1/4", "snare")]
    assert any("written as a 3/4 bar" in w for w in rep.warnings)


# ---- sections ---------------------------------------------------------------------

def test_section_names():
    assert section_name("[section Verse 1]") == "Verse 1"
    assert section_name("[prc_chorus_2a]") == "Chorus 2a"
    assert section_name('"section gtr_solo"') == "Gtr solo"
    assert section_name("[music_start]") is None and section_name("[mix 3 drums0d]") is None


def test_midi_sections_from_the_events_track(tmp_path):
    # Two bars of count-in before the drums; the intro section is charted at tick 0.
    notes = sum((rock_bar(k * BAR) for k in range(2, 6)), [])
    events = [(0, "[section Intro]"), (3 * BAR, "[prc_verse_1]"), (5 * BAR - SIXTEENTH, "[section Chorus]"),
              (0, "[music_start]")]
    score, rep = read_gamechart(rb_midi(tmp_path / "notes.mid", notes, events=events, markers=PRO))
    assert rep.trimmed_leading_bars == 2
    assert [m.section for m in score.measures] == ["Intro", "Verse 1", None, "Chorus"]
    assert any("bar 1 here is bar 3" in w for w in rep.warnings)
    assert any("'Chorus'" in w and "not on a barline" in w for w in rep.warnings)


def test_chart_sections_from_the_events_block(tmp_path):
    notes = [(k * CBAR, 0) for k in range(3)]
    events = [(0, "section Intro"), (CBAR, "section Verse 1")]
    score, _ = read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}, events=events))
    assert [m.section for m in score.measures] == ["Intro", "Verse 1", None]


# ---- difficulty -------------------------------------------------------------------

def test_difficulty_selection(tmp_path):
    hard = [(0, 84), (TPB, 85), (2 * TPB, 86)]
    path = rb_midi(tmp_path / "notes.mid", rock_bar() + hard + [(0, 72)])
    score, rep = read_gamechart(path, difficulty="hard")
    assert bar(score, 0) == [("0", "kick"), ("1/4", "snare"), ("1/2", "tom1")]
    assert rep.difficulties == ["expert", "hard", "medium"] and "Hard drums" in score.source
    with pytest.raises(GameChartError, match="no easy drum notes; it has: expert, hard, medium"):
        read_gamechart(path, difficulty="easy")

    chart = chart_file(tmp_path / "notes.chart", {"ExpertDrums": [(0, 0), (RES, 1), (2 * RES, 0)],
                                                  "HardDrums": [(0, 0), (RES, 1)]})
    score, _ = read_gamechart(chart, difficulty="hard")
    assert bar(score, 0) == [("0", "kick"), ("1/4", "snare")]
    with pytest.raises(GameChartError, match="no medium drum notes"):
        read_gamechart(chart, difficulty="medium")


# ---- rejections and errors --------------------------------------------------------

def test_five_lane_charts_are_rejected(tmp_path):
    with pytest.raises(GameChartError, match="five-lane"):
        read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": [(0, 0), (RES, 5)]}))
    with pytest.raises(GameChartError, match="five-lane"):
        read_gamechart(rb_midi(tmp_path / "five.mid", [(0, KICK), (TPB, 101)]))
    folder = tmp_path / "b"
    folder.mkdir()
    chart_file(folder / "notes.chart", {"ExpertDrums": [(0, 0)]})
    (folder / "song.ini").write_text("[song]\nfive_lane_drums = True\n")
    with pytest.raises(GameChartError, match="five_lane_drums"):
        read_gamechart(folder)


def test_unreadable_inputs_are_clear_errors(tmp_path):
    with pytest.raises(GameChartError, match="no 'PART DRUMS' track.*PART GUITAR"):
        read_gamechart(rb_midi(tmp_path / "notes.mid", [(0, KICK)], drum_track="PART GUITAR"))
    (tmp_path / "junk.mid").write_bytes(b"not a midi file")
    with pytest.raises(GameChartError, match="not a readable MIDI file"):
        read_gamechart(tmp_path / "junk.mid")
    (tmp_path / "empty").mkdir()
    with pytest.raises(GameChartError, match="no notes.mid or notes.chart"):
        read_gamechart(tmp_path / "empty")
    with pytest.raises(GameChartError, match="no drum notes"):
        read_gamechart(chart_file(tmp_path / "x.chart", {"ExpertSingle": [(0, 0)]}))


# ---- song folder and metadata -----------------------------------------------------

def test_song_folder_reads_song_ini_metadata(tmp_path):
    folder = tmp_path / "My Song Folder"
    folder.mkdir()
    chart_file(folder / "notes.chart", {"ExpertDrums": [(0, 0), (RES, 1)]},
               song={"Name": "Chart Name", "Artist": "Chart Artist", "Charter": "Chart Charter", "Offset": 0.25})
    score, rep = read_gamechart(folder)
    assert (score.title, score.artist, score.transcriber) == ("Chart Name", "Chart Artist",
                                                              "Chart Charter (game chart)")
    assert score.analysis["audio_offset_s"] == 0.25
    (folder / "song.ini").write_text("﻿[Song]\nname = <color=#ff8800>Ini Name</color>\nartist = Ini Artist\n"
                                     "charter = Ini Charter\n")
    score, rep = read_gamechart(folder)
    assert (score.title, score.artist, score.transcriber) == ("Ini Name", "Ini Artist", "Ini Charter (game chart)")
    assert rep.path.name == "notes.chart" and "Clone Hero .chart notes.chart, Expert drums" == score.source
    score, _ = read_gamechart(folder / "notes.chart", title="Given", artist="Someone")
    assert (score.title, score.artist) == ("Given", "Someone")


def test_folder_without_metadata_is_named_after_the_folder_and_prefers_notes_mid(tmp_path):
    folder = tmp_path / "Untitled Groove"
    folder.mkdir()
    rb_midi(folder / "notes.mid", rock_bar(), markers=PRO)
    chart_file(folder / "notes.chart", {"ExpertDrums": [(0, 0)]})
    score, rep = read_gamechart(folder)
    assert score.title == "Untitled Groove" and score.artist is None and score.transcriber is None
    assert rep.format == "midi" and any("both notes.mid and notes.chart" in w for w in rep.warnings)


# ---- spelling: sloppy ticks still land on a spellable grid ------------------------

def test_off_grid_ticks_snap_to_spellable_positions(tmp_path):
    from drum_agent.rhythm import spell_measure
    # A hat 7 ticks late, a snare 4 ticks early plus a 64th-note double of it (a charted
    # flam), and a ride on a triplet 8th.
    notes = [(0, KICK), (EIGHTH + 7, YELLOW), (TPB - 4, RED), (TPB + TPB // 16, RED), (2 * TPB + TPB // 3, BLUE)]
    score, _ = read_gamechart(rb_midi(tmp_path / "notes.mid", notes, markers=PRO))
    assert bar(score, 0) == [("0", "kick"), ("1/8", "hihat"), ("1/4", "snare"), ("7/12", "ride")]
    assert score.analysis["merged_duplicates"] == 1
    spell_measure(score.measures[0])  # every position has a written value


# ---- CLI --------------------------------------------------------------------------

Run = namedtuple("Run", "rc out err")


@pytest.fixture
def cli(capsys, monkeypatch):
    monkeypatch.delenv("DRUM_AGENT_DEBUG", raising=False)

    def run(*argv):
        capsys.readouterr()
        try:
            rc = main([str(a) for a in argv])
        except SystemExit as exc:
            if isinstance(exc.code, str):
                print(exc.code, file=sys.stderr)
                rc = 1
            else:
                rc = exc.code or 0
        out, err = capsys.readouterr()
        return Run(rc, out, err)

    return run


def test_cli_gamechart_folder(cli, tmp_path):
    folder = tmp_path / "Cli Song"
    folder.mkdir()
    rb_midi(folder / "notes.mid", rock_bar() + rock_bar(BAR) + [(BAR, 84)], markers=PRO,
            events=[(0, "[section Intro]")])
    (folder / "song.ini").write_text("[song]\nname = Cli Song\nartist = Test Players\ncharter = Test Charter\n")
    out = tmp_path / "out"
    r = cli("gamechart", folder, "-o", out, "--formats", "musicxml,midi,json", "--rights", "own")
    assert r.rc == 0, r.out + r.err
    assert "notes.mid: expert drums (2 bars" in r.out and "check: MIDI: OK" in r.out
    s = Score.load(out / "Cli Song.json")
    assert (s.title, s.artist, s.rights, s.status) == ("Cli Song", "Test Players", "own", "unverified_import")
    assert [m.section for m in s.measures] == ["Intro", None] and bar(s, 0) == ROCK
    assert SIMPLIFIED in (out / "Cli Song.report.md").read_text()

    r = cli("gamechart", folder, "-o", tmp_path / "hard", "--formats", "json", "--difficulty", "hard",
            "--no-pro", "--sections", "Fill:1", "--title", "Other", "--transcriber", "Me")
    assert r.rc == 0, r.out + r.err
    s = Score.load(tmp_path / "hard" / "Cli Song.json")
    assert (s.title, s.transcriber, s.measures[0].section) == ("Other", "Me", "Fill")
    assert bar(s, 0) == [("0", "kick")]


def test_cli_gamechart_never_overwrites_the_chart(cli, tmp_path):
    src = rb_midi(tmp_path / "notes.mid", rock_bar())
    before = src.read_bytes()
    r = cli("gamechart", src, "-o", tmp_path, "--stem", "notes", "--formats", "midi,json")
    assert r.rc != 0 and "overwrite the input" in r.err and "Traceback" not in r.err
    assert src.read_bytes() == before
    r = cli("gamechart", tmp_path / "missing", "-o", tmp_path / "out")
    assert r.rc == 1 and "does not exist" in r.err and "Traceback" not in r.err


def test_cli_gamechart_writes_no_chart_into_the_song_folder(cli, tmp_path):
    # A chart under another name is the input too (the default stem overwrote it), in any case.
    other = rb_midi(tmp_path / "MySong.mid", rock_bar())
    before = other.read_bytes()
    for argv in ([], ["--stem", "mysong"]):
        r = cli("gamechart", other, "-o", tmp_path, "--formats", "midi,json", *argv)
        assert r.rc != 0 and "overwrite the input" in r.err, r.out + r.err
    assert other.read_bytes() == before
    # A notes.mid beside notes.chart is read instead of it (re-import then failed), and on
    # macOS or Windows Notes.mid is notes.mid. The folder's own name is the default stem.
    folder = tmp_path / "notes"
    folder.mkdir()
    chart_file(folder / "notes.chart", {"ExpertDrums": [(0, 0), (RES, 1)]})
    for argv in ([], ["--stem", "Notes"]):
        r = cli("gamechart", folder, "-o", folder, "--formats", "midi,json", *argv)
        assert r.rc != 0 and "into the song folder" in r.err and "Traceback" not in r.err, r.out + r.err
    assert [f.name for f in folder.iterdir()] == ["notes.chart"]
    r = cli("gamechart", folder, "-o", folder, "--stem", "Groove", "--formats", "midi,json")
    assert r.rc == 0 and (folder / "Groove.mid").exists() and read_gamechart(folder)[1].format == "chart"


# ---- end to end: engrave with every check ------------------------------------------

@needs_lilypond
def test_gamechart_engraves_with_every_check_ok(tmp_path):
    fill, markers = tom_fill_bar(3 * BAR)
    three = BAR * 3 // 4
    notes = [(0, GREEN, 127), (0, KICK)] + rock_bar() + rock_bar(BAR) + rock_bar(2 * BAR) + fill
    notes += [(4 * BAR, GREEN), (4 * BAR, KICK), (4 * BAR + TPB, RED, 1), (4 * BAR + 2 * TPB, RED),
              (4 * BAR + 2 * TPB + EIGHTH, RED, 127)]
    meters = [(0, 4, 4), (4 * BAR, 3, 4), (4 * BAR + three, 4, 4)]
    notes += rock_bar(4 * BAR + three)
    path = rb_midi(tmp_path / "notes.mid", notes, markers=markers, meters=meters,
                   tempos=[(0, 104), (4 * BAR, 96)], texts=[(0, "[ENABLE_CHART_DYNAMICS]")],
                   events=[(0, "[section Intro]"), (3 * BAR, "[section Fill]"), (4 * BAR, "[prc_verse]")])
    score, rep = read_gamechart(path, title="Engraved Game Chart")
    score.rights = "original"
    report = export_all(score, tmp_path / "out", "engraved", options=ExportOptions())
    assert report.rendering_ok, [c.summary() for c in report.comparisons]
    names = {c.name: c for c in report.comparisons}
    assert set(names) == {"engraved score (LilyPond MIDI)", "engraved score tempo map", "MusicXML",
                          "MusicXML articulations", "MusicXML meters", "MIDI", "MIDI tempo map", "MIDI barlines"}
    assert all(c.ok for c in report.comparisons)
    assert names["MusicXML"].expected == len(score.event_list()) > 40
    assert not report.musicxml_errors
    assert not [w for w in report.warnings if w.startswith("LilyPond")]
    assert report.files["pdf"].stat().st_size > 0
    text = report.files["report"].read_text()
    assert "Game charts are simplified" in text and "Imported" in text


# ---- review regressions: exact ticks and corrupt files ----------------------------

def test_exact_ticks_stay_exact_at_a_fast_tempo(tmp_path):
    # At 240 BPM a 32nd is closer in time to a sextuplet than a player's timing error;
    # chart ticks are exact, so 32nd, 32nd, 16th, 8th stay that.
    snare = [(t, 1) for t in (0, 24, 48, 96, 192, 384, 576)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": snare}, sync=("0 = TS 4", "0 = B 240000"))
    score, _ = read_gamechart(path, pro=False)
    assert [p for p, _ in bar(score, 0)] == ["0", "1/32", "1/16", "1/8", "1/4", "1/2", "3/4"]


@pytest.mark.parametrize("res,late", [(192, 2), (192, 3), (480, 2), (480, 3)])
def test_one_stray_tick_keeps_the_exact_figure(tmp_path, res, late):
    # The same figure with the 16th a few ticks late: up to the slack (2 ticks) it is on
    # the grid, past it a stray of that grid, and the other gems still say 32nds.
    q = res // 8  # a 32nd
    snare = [(t, 1) for t in (0, q, 2 * q + late, 4 * q, 8 * q, 16 * q, 24 * q)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": snare}, sync=("0 = TS 4", "0 = B 240000"),
                      resolution=res)
    score, _ = read_gamechart(path, pro=False)
    assert [p for p, _ in bar(score, 0)] == ["0", "1/32", "1/16", "1/8", "1/4", "1/2", "3/4"]


@pytest.mark.parametrize("notes,written,merged", [
    ([0, 58, 96, 144], ["0", "1/16", "1/8", "3/16"], 0),  # a 16th 10 ticks late
    ([0, 74, 128], ["0", "1/12", "1/6"], 0),  # a triplet 8th 10 ticks late
    ([0, 12], ["0"], 1),  # a 64th-note double (a charted flam), as test_off_grid_ticks_snap...
])
def test_a_gem_near_no_grid_is_placed_by_its_timing(tmp_path, notes, written, merged):
    # At 192 ticks a beat the 12-grid has a slot within 8 ticks of every tick, but a gem
    # 4 or more ticks from it is no stray of it: these were written as 32nd sextuplets.
    snare = [(t, 1) for t in notes] + [(RES * k, 1) for k in (1, 2, 3)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": snare}, sync=("0 = TS 4", "0 = B 240000"))
    score, _ = read_gamechart(path, pro=False)
    assert [p for p, _ in bar(score, 0)] == written + ["1/4", "1/2", "3/4"]
    assert score.analysis["merged_duplicates"] == merged


@pytest.mark.parametrize("res,late", [(192, 3), (480, 7)])
def test_slack_scales_with_a_dotted_quarter_beat(tmp_path, res, late):
    # In 6/8 the grid positions are 1.5 times as far apart, and so is the slack (3 ticks at
    # 192): a 32nd that late is still a 32nd, not the 16th 21 ticks away.
    q = res // 8
    notes = [(0, 1), (q + late, 1), (4 * q, 1), (8 * q, 1), (12 * q, 0)]
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}, sync=("0 = TS 6 3", "0 = B 90000"),
                      resolution=res)
    score, _ = read_gamechart(path, pro=False)
    assert [p for p, _ in bar(score, 0)] == ["0", "1/32", "1/8", "1/4", "3/8"]


@pytest.mark.parametrize("late", [-2, 2])
def test_a_swung_offbeat_off_by_the_slack_stays_a_swung_8th(tmp_path, late):
    # The swung grid's offbeat is measured where it sits in the beat (2/3), so a tom 2
    # ticks early or late is a swung 8th, not the triplet the warp would make of it.
    notes = [(t + d, 2) for t in range(0, 8 * RES, RES) for d in (0, 128)]
    notes += [(t, 0 if t % (2 * RES) == 0 else 1) for t in range(0, 8 * RES, RES)]
    notes += [(8 * RES, 3), (8 * RES + 128 + late, 3)]
    score, _ = read_gamechart(chart_file(tmp_path / "notes.chart", {"ExpertDrums": notes}), pro=False)
    assert score.swing and bar(score, 2) == [("0", "tom2"), ("1/8", "tom2")]


@pytest.mark.parametrize("sync,message", [
    (("0 = TS 4 100000000000", "0 = B 120000"), "meter"),
    (("0 = TS 1000000", "0 = B 120000"), "meter"),
    (("0 = TS 4", "0 = B 1"), "tempo"),
    (("0 = TS 4", "0 = B 99999999999999999999"), "tempo"),
])
def test_corrupt_sync_track_is_refused(tmp_path, sync, message):
    path = chart_file(tmp_path / "notes.chart", {"ExpertDrums": [(0, 0)]}, sync=sync)
    with pytest.raises(GameChartError, match=message):
        read_gamechart(path)


def test_corrupt_resolution_offset_and_far_ticks(tmp_path):
    with pytest.raises(GameChartError, match="Resolution"):
        read_gamechart(chart_file(tmp_path / "a.chart", {"ExpertDrums": [(0, 0)]}, resolution="1e400"))
    score, _ = read_gamechart(chart_file(tmp_path / "b.chart", {"ExpertDrums": [(0, 0)]}, song={"Offset": "nan"}))
    json.dumps(score.to_dict(), allow_nan=False)  # no NaN in score.json
    with pytest.raises(GameChartError, match="corrupt"):
        read_gamechart(chart_file(tmp_path / "c.chart", {"ExpertDrums": [(0, 0), (768_000_000_000, 0)]}))


def test_bars_shorter_than_a_tick_or_too_many_are_refused(tmp_path):
    # A 1/8 bar at 1 tick per quarter is half a tick: the bar loop never ended.
    coarse = chart_file(tmp_path / "a.chart", {"ExpertDrums": [(0, 0), (4, 1)]},
                        sync=("0 = TS 1 3", "0 = B 120000"), resolution=1)
    with pytest.raises(GameChartError, match="resolution 1 is too coarse for a 1/8 bar"):
        read_gamechart(coarse)
    with pytest.raises(GameChartError, match="resolution 1 is too coarse for a 1/8 bar"):
        read_gamechart(rb_midi(tmp_path / "notes.mid", [(0, KICK), (4, RED)], meters=((0, 1, 8),), tpb=1))
    # A 1/32 meter makes eight bars of every beat, so bars are capped as beats are.
    tiny = chart_file(tmp_path / "b.chart", {"ExpertDrums": [(0, 0), (RES // 8 * 20_001, 1)]},
                      sync=("0 = TS 1 5", "0 = B 120000"))
    with pytest.raises(GameChartError, match="more than 20000 bars"):
        read_gamechart(tiny)


def test_midi_without_ticks_per_beat_is_refused(tmp_path):
    path = rb_midi(tmp_path / "notes.mid", rock_bar(), markers=PRO)
    data = bytearray(path.read_bytes())
    data[12:14] = b"\x00\x00"  # header division: 0 ticks per quarter note
    path.write_bytes(bytes(data))
    with pytest.raises(GameChartError, match="ticks per quarter"):
        read_gamechart(path)


def test_section_names_are_cleaned():
    assert section_name("[section ]") is None and section_name("[prc_]") is None
    assert section_name("[section <color=red>Intro</color>]") == "Intro"
    assert section_name("[prc_verse_1]") == "Verse 1"


def test_export_never_overwrites_the_other_chart_file_in_the_folder(tmp_path, capsys):
    folder = tmp_path / "Both"
    folder.mkdir()
    rb_midi(folder / "notes.mid", rock_bar(), markers=PRO)
    chart_file(folder / "notes.chart", {"ExpertDrums": [(0, 0), (RES, 1)]})
    before = (folder / "notes.mid").read_bytes()
    with pytest.raises(SystemExit):
        main(["gamechart", str(folder / "notes.chart"), "-o", str(folder), "--stem", "notes",
              "--formats", "midi,json", "--rights", "own", "--no-32nds"])
    assert (folder / "notes.mid").read_bytes() == before
