"""MIDI import and the shared quantizer."""

import random

import mido
import pytest

from drum_agent.charts import compile_spec
from drum_agent.export.midi import write_midi
from drum_agent.io_midi import read_midi
from drum_agent.quantize import BarDef, Onset, QuantizeOptions, detect_feel, quantize
from drum_agent.model import TimeSig

GROOVES = {
    "rock": {"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-------x-x-----"},
    "funk": {"hh": "xxxxxxxxxxxxxxxx", "sn": "----x--x-x--x--x", "bd": "x-x----x--x-----"},
    "trip": {"sn": "xxx|x-x|xxxx|xxxx", "bd": "x--|x--|x---|x---"},
}


def chart(bars, **kw):
    spec = {"tempo": 112, "patterns": GROOVES, "sections": [{"label": "A", "bars": bars}]}
    spec.update(kw)
    return compile_spec(spec)


def test_round_trip_is_exact(tmp_path):
    s = chart(["rock", "funk", "trip", {"time": "7/8", "hh": "xxxxxxx", "bd": "x-x-x--"},
               {"time": "6/8", "hh": "x-x-x-x-x-x-", "bd": "x-----------"}, {"time": "4/4", "pattern": "rock"}])
    write_midi(s, tmp_path / "a.mid")
    s2, rep = read_midi(tmp_path / "a.mid")
    assert s2.event_list() == s.event_list()
    assert [str(m.time_sig) for m in s2.measures] == [str(m.time_sig) for m in s.measures]
    assert s2.measures[0].tempo == 112


def _humanize(src, dst, jitter_ticks, seed=1):
    rng = random.Random(seed)
    mid = mido.MidiFile(str(src))
    for track in mid.tracks:
        tick = 0
        absolute = []
        for msg in track:
            tick += msg.time
            absolute.append([tick, msg])
        for item in absolute:
            if item[1].type == "note_on" and item[1].velocity > 0:
                item[0] = max(0, item[0] + rng.randint(-jitter_ticks, jitter_ticks))
        absolute.sort(key=lambda x: x[0])
        prev = 0
        track.clear()
        for t, msg in absolute:
            track.append(msg.copy(time=t - prev))
            prev = t
    mid.save(str(dst))


def test_humanized_timing_snaps_back_to_the_grid(tmp_path):
    s = chart(["rock", "funk", "rock", "funk", "trip", "rock"])
    write_midi(s, tmp_path / "a.mid")
    # +-25 ticks at 960 ppq and 112 BPM is about +-14 ms: a tight but human drummer.
    _humanize(tmp_path / "a.mid", tmp_path / "h.mid", 25)
    s2, _ = read_midi(tmp_path / "h.mid")
    assert s2.event_list() == s.event_list()
    offsets = [abs(h.offset_ms) for m in s2.measures for h in m.hits]
    assert max(offsets) < 20 and max(offsets) > 0


def test_swing_is_written_as_straight_eighths_with_swing_mark():
    beat = 0.5
    onsets, beats = [], [k * beat for k in range(17)]
    for k in range(16):
        onsets.append(Onset(k * beat, "ride"))
        onsets.append(Onset(k * beat + beat * 2 / 3, "ride"))
        if k % 2 == 1:
            onsets.append(Onset(k * beat, "snare"))
    bars = [BarDef(4 * i, TimeSig(4, 4), 4) for i in range(4)]
    res = quantize(onsets, beats, bars)
    assert res.feel == "swing" and abs(res.swing_ratio - 2 / 3) < 0.02
    ride = sorted(h.pos for h in res.measures[0].hits if h.inst == "ride")
    assert [str(p) for p in ride] == ["0", "1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8"]
    assert res.measures[0].tempo_text == "Swing"


def test_triplet_feel_detection():
    rels = [0.0, 1 / 3, 2 / 3] * 10
    assert detect_feel(rels)[0] == "triplet"
    assert detect_feel([0.0, 0.25, 0.5, 0.75] * 10)[0] == "straight"


def test_tempo_change_creates_new_mark():
    beats, t = [], 0.0
    for k in range(33):
        beats.append(t)
        t += 0.5 if k < 16 else 0.4  # 120 BPM then 150 BPM
    onsets = [Onset(b, "kick") for b in beats[:-1]]
    bars = [BarDef(4 * i, TimeSig(4, 4), 4) for i in range(8)]
    res = quantize(onsets, beats, bars)
    marks = [(i, m.tempo) for i, m in enumerate(res.measures) if m.tempo]
    assert marks[0] == (0, 120.0)
    assert any(abs(t - 150) < 2 for _, t in marks[1:])


def test_no_drum_channel_is_an_error(tmp_path):
    mid = mido.MidiFile()
    tr = mido.MidiTrack()
    tr.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
    mid.tracks.append(tr)
    mid.save(str(tmp_path / "piano.mid"))
    with pytest.raises(ValueError, match="channel 10"):
        read_midi(tmp_path / "piano.mid")
