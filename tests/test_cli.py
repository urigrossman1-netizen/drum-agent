"""Command-line interface, driven in-process through drum_agent.cli.main.

Covers every subcommand's happy path (render, midi, edit, verify, evaluate,
doctor, and analyze/transcribe on synthesized audio), the rights gate, and
the promise that user mistakes end in a one-line error and a non-zero exit
code, never a traceback.
"""

import json
import re
import sys
from collections import namedtuple
from pathlib import Path

import mido
import pytest
import yaml

from conftest import needs_fluidsynth, needs_lilypond
from drum_agent import __version__
from drum_agent import edit as E
from drum_agent.charts import compile_spec, load_any
from drum_agent.cli import main
from drum_agent.model import RIGHTS, Score

FAST = "musicxml,midi,json"  # every format that doesn't need LilyPond

GROOVES = {
    "hat": {"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-------x-x-----"},
    "ride": {"rd": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-------x-x-----"},
}

CHART = {
    "title": "CLI Groove",
    "artist": "Drum Agent test suite (original)",
    "chart_type": "pattern_study",
    "rights": "original",
    "tempo": 112,
    "patterns": GROOVES,
    "sections": [
        {"label": "Verse", "bars": ["hat", "hat", "ride", "ride"]},
        {"label": "Chorus", "bars": [{"cr": "x---------------", "sn": "----x-------x---",
                                      "bd": "x-------x-x-----"}, "ride"]},
    ],
}

# An automatic-looking score to correct: two bars flagged for review.
EDIT_CHART = dict(CHART, title="Edit Me", chart_type="full_transcription", status="unverified_auto", sections=[
    {"label": "Verse", "bars": ["hat", "hat", {"pattern": "ride", "uncertain": True, "notes": ["ride or hat?"]},
                                "ride"]},
    {"label": "Chorus", "bars": [{"cr": "x---------------", "sn": "----x-------x---", "bd": "x-------x-x-----",
                                  "uncertain": True}, "ride"]},
])

Run = namedtuple("Run", "rc out err")


@pytest.fixture
def cli(capsys, monkeypatch):
    """Call main(argv) and return (exit code, stdout, stderr)."""
    monkeypatch.delenv("DRUM_AGENT_DEBUG", raising=False)

    def run(*argv):
        capsys.readouterr()
        try:
            rc = main([str(a) for a in argv])
        except SystemExit as exc:  # argparse, --version, SystemExit("message"): as the interpreter reports them
            if isinstance(exc.code, str):
                print(exc.code, file=sys.stderr)
                rc = 1
            else:
                rc = exc.code or 0
        out, err = capsys.readouterr()
        return Run(rc, out, err)

    return run


def clean_error(r, *fragments):
    """Non-zero exit, a message on stderr naming the problem, and no traceback."""
    assert r.rc != 0, r
    assert "Traceback" not in r.err + r.out
    assert r.err.strip(), "no error message"
    for f in fragments:
        assert f in r.err, (f, r.err)


def write_chart(path: Path, spec=CHART) -> Path:
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return path


def write_score(path: Path, spec=EDIT_CHART) -> Path:
    compile_spec(spec).save(path)
    return path


def gm_drum_midi(path: Path, channel: int = 9, bars: int = 2, bpm: int = 100, extra=()) -> Path:
    """A General MIDI drum track: 8th hi-hats, snare on 2 and 4, kick on 1, 3 and the "and" of 3.

    `channel` is 0-based (9 is GM channel 10); `extra` adds (tick, note) strokes.
    """
    tpb = 480
    strokes = []
    for b in range(bars):
        start = b * 4 * tpb
        strokes += [(start + k * tpb // 2, 42) for k in range(8)]
        strokes += [(start + tpb, 38), (start + 3 * tpb, 38)]
        strokes += [(start, 36), (start + 2 * tpb, 36), (start + 5 * tpb // 2, 36)]
    strokes += list(extra)
    events = []
    for tick, note in strokes:
        events.append((tick, 1, mido.Message("note_on", channel=channel, note=note, velocity=96)))
        events.append((tick + 60, 0, mido.Message("note_off", channel=channel, note=note, velocity=0)))
    events.sort(key=lambda e: (e[0], e[1]))
    mid = mido.MidiFile(ticks_per_beat=tpb)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="Test Drums", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    prev = 0
    for tick, _, msg in events:
        track.append(msg.copy(time=tick - prev))
        prev = tick
    mid.save(str(path))
    return path


def gm_expected(bars: int = 2, bpm: int = 100) -> Score:
    rock = {"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x---xx--"}
    return compile_spec({"tempo": bpm, "patterns": {"rock": rock}, "sections": [{"bars": [f"rock*{bars}"]}]})


def onset_f(text: str) -> float:
    return float(re.search(r"Onset accuracy .*?: F=([\d.]+)", text).group(1))


def notation_f(text: str) -> float:
    return float(re.search(r"Notation accuracy .*?: F=([\d.]+)", text).group(1))


# ---- global options ---------------------------------------------------------------

def test_version(cli):
    r = cli("--version")
    assert r.rc == 0 and f"drum-agent {__version__}" in r.out


def test_no_command_is_a_usage_error(cli):
    r = cli()
    assert r.rc == 2 and "usage" in r.err


@needs_lilypond
def test_doctor(cli):
    r = cli("doctor")
    assert r.rc == 0, r.out
    assert "LilyPond" in r.out and "All required dependencies present." in r.out


# ---- render -----------------------------------------------------------------------

@needs_lilypond
def test_render_chart_writes_every_format_and_a_report(cli, tmp_path):
    chart = write_chart(tmp_path / "groove.yaml")
    out = tmp_path / "out"
    r = cli("render", chart, "-o", out)
    assert r.rc == 0, r.out + r.err
    assert f"files to {out}" in r.out
    for name in ("engraved score (LilyPond MIDI)", "MusicXML", "MIDI"):
        assert f"check: {name}: OK" in r.out
    for suffix in (".pdf", ".png", ".ly", ".midi", ".musicxml", ".mid", ".json", ".report.md", ".report.json"):
        f = out / f"groove{suffix}"
        assert f.exists() and f.stat().st_size > 0, f
    rep = json.loads((out / "groove.report.json").read_text())
    assert rep["rendering_ok"] and rep["bars"] == 6 and rep["title"] == "CLI Groove"
    assert rep["events"] == len(load_any(chart).event_list())
    assert not rep["musicxml_errors"]
    assert "# Drum chart report: CLI Groove" in (out / "groove.report.md").read_text()
    assert load_any(out / "groove.json").event_list() == load_any(chart).event_list()
    # The exports pass `verify`, including the MIDI LilyPond wrote from the engraved .ly.
    r = cli("verify", out / "groove.json", "--musicxml", out / "groove.musicxml", "--midi", out / "groove.mid",
            "--ly-midi", out / "groove.midi")
    assert r.rc == 0, r.out
    assert "engraved score (LilyPond MIDI): OK" in r.out and "MusicXML schema: valid" in r.out


def test_render_without_lilypond_formats_stem_and_title(cli, tmp_path):
    chart = write_chart(tmp_path / "groove.yaml")
    out = tmp_path / "out"
    r = cli("render", chart, "-o", out, "--formats", FAST, "--stem", "take2", "--title", "Renamed")
    assert r.rc == 0, r.out + r.err
    assert "check: MusicXML: OK" in r.out and "check: MIDI: OK" in r.out
    assert sorted(p.name for p in out.iterdir()) == sorted(
        f"take2{s}" for s in (".json", ".musicxml", ".mid", ".report.md", ".report.json"))
    assert Score.load(out / "take2.json").title == "Renamed"
    assert json.loads((out / "take2.report.json").read_text())["title"] == "Renamed"


def test_render_ly_only_does_not_run_lilypond(cli, tmp_path):
    out = tmp_path / "out"
    r = cli("render", write_chart(tmp_path / "groove.yaml"), "-o", out, "--formats", "ly")
    assert r.rc == 0, r.out + r.err
    ly = (out / "groove.ly").read_text()
    assert "\\version" in ly and "Verse" in ly
    assert not (out / "groove.pdf").exists()


def test_render_reports_bars_to_verify(cli, tmp_path):
    score = write_score(tmp_path / "auto.json")
    r = cli("render", score, "-o", tmp_path / "out", "--formats", "json")
    assert r.rc == 0
    assert "bars to verify by ear" in r.out
    assert "as score.json bar numbers (for `edit`): [3, 5]" in r.out


def test_render_ir_json_round_trips(cli, tmp_path):
    chart = write_chart(tmp_path / "groove.yaml")
    assert cli("render", chart, "-o", tmp_path / "a", "--formats", "json").rc == 0
    assert cli("render", tmp_path / "a" / "groove.json", "-o", tmp_path / "b", "--formats", "json").rc == 0
    assert json.loads((tmp_path / "b" / "groove.json").read_text()) == \
        json.loads((tmp_path / "a" / "groove.json").read_text())


def test_render_with_kit_override(cli, tmp_path):
    kit = tmp_path / "kit.json"
    kit.write_text(json.dumps({"instruments": {"snare": {"midi": 40, "name": "Piccolo"}}}))
    out = tmp_path / "out"
    r = cli("render", write_chart(tmp_path / "groove.yaml"), "-o", out, "--formats", "midi,json", "--kit", kit)
    assert r.rc == 0, r.out + r.err
    notes = {m.note for tr in mido.MidiFile(str(out / "groove.mid")).tracks for m in tr if m.type == "note_on"}
    assert 40 in notes and 38 not in notes


# ---- midi -------------------------------------------------------------------------

def test_midi_drums_on_channel_10(cli, tmp_path):
    src = gm_drum_midi(tmp_path / "beat.mid")
    out = tmp_path / "out"
    r = cli("midi", src, "-o", out, "--formats", FAST)
    assert r.rc == 0, r.out + r.err
    assert "check: MIDI: OK" in r.out
    s = Score.load(out / "beat.json")
    assert s.event_list() == gm_expected().event_list()
    assert s.measures[0].tempo == 100 and str(s.measures[0].time_sig) == "4/4"
    assert s.title == "Test Drums" and s.source == "MIDI file beat.mid"


def test_midi_other_channel_needs_channel_option(cli, tmp_path):
    src = gm_drum_midi(tmp_path / "beat.mid", channel=2)
    r = cli("midi", src, "-o", tmp_path / "out", "--formats", FAST)
    clean_error(r, "channel 10", "--channel")
    assert not (tmp_path / "out").exists()
    r = cli("midi", src, "-o", tmp_path / "out", "--formats", FAST, "--channel", 3)
    assert r.rc == 0, r.out + r.err
    assert Score.load(tmp_path / "out" / "beat.json").event_list() == gm_expected().event_list()
    clean_error(cli("midi", src, "-o", tmp_path / "x", "--channel", 5), "no notes on channel 5")


def test_midi_metadata_and_sections(cli, tmp_path):
    src = gm_drum_midi(tmp_path / "beat.mid", bars=4)
    out = tmp_path / "out"
    r = cli("midi", src, "-o", out, "--formats", "json", "--stem", "song", "--title", "Song", "--artist", "Band",
            "--transcriber", "Me", "--rights", "own", "--sections", "Intro:1,Groove:3")
    assert r.rc == 0, r.out + r.err
    s = Score.load(out / "song.json")
    assert (s.title, s.artist, s.transcriber, s.rights) == ("Song", "Band", "Me", "own")
    assert [m.section for m in s.measures] == ["Intro", None, "Groove", None]


def test_midi_unmapped_notes_are_reported(cli, tmp_path):
    src = gm_drum_midi(tmp_path / "beat.mid", extra=[(240, 81), (1200, 81)])  # 81 = open triangle
    r = cli("midi", src, "-o", tmp_path / "out", "--formats", "json")
    assert r.rc == 0
    assert "unmapped MIDI notes skipped: {81: 2}" in r.err
    assert Score.load(tmp_path / "out" / "beat.json").event_list() == gm_expected().event_list()


# ---- edit -------------------------------------------------------------------------

def test_edit_relabel_in_bars_writes_a_new_file(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    original = src.read_bytes()
    dst = tmp_path / "fixed.json"
    r = cli("edit", src, "--relabel", "ride=hihat", "--bars", "4", "-o", dst)
    assert r.rc == 0, r.err
    assert "relabel ride=hihat in bars 4: 8 hits" in r.out and f"saved {dst}" in r.out
    assert src.read_bytes() == original
    before, after = Score.load(src), Score.load(dst)
    for i, (a, b) in enumerate(zip(before.measures, after.measures)):
        if i == 3:
            assert {h.inst for h in b.hits} == {"hihat", "snare", "kick"}
            assert sorted((h.pos, h.inst.replace("ride", "hihat")) for h in a.hits) == \
                sorted((h.pos, h.inst) for h in b.hits)
        else:
            assert a.to_dict() == b.to_dict()


def test_edit_combined_corrections_match_the_library(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    dst = tmp_path / "out.json"
    r = cli("edit", src, "-o", dst,
            "--relabel", "ride=hihat", "--bars", "3-4",
            "--delete", "2:5/8:kick", "--delete", "6:0:ride",
            "--add", "2:3/8:snare:ghost", "--add", "6:0:crash:choke", "--add", "4:7/8:sn:flam",
            "--set", "5:3/4:snare:roll=1/4", "--set", "1:1/4:snare:accent",
            "--sections", "Intro:1,Chorus:5",
            "--tempo", "5:120",
            "--title", "Fixed", "--status", "draft")
    assert r.rc == 0, r.err
    assert r.out.splitlines() == [
        "relabel ride=hihat in bars 3-4: 16 hits",
        "deleted 2:5/8:kick", "deleted 6:0:ride",
        "added 2:3/8:snare:ghost", "added 6:0:crash:choke", "added 4:7/8:sn:flam",
        "set 5:3/4:snare:roll=1/4", "set 1:1/4:snare:accent",
        "sections Intro:1,Chorus:5",
        "tempo 5:120",
        "title = Fixed", "status = draft",
        f"saved {dst}",
    ]
    expected = load_any(src)
    E.relabel(expected, "ride=hihat", "3-4")
    E.delete(expected, "2:5/8:kick")
    E.delete(expected, "6:0:ride")
    E.add(expected, "2:3/8:snare:ghost")
    E.add(expected, "6:0:crash:choke")
    E.add(expected, "4:7/8:sn:flam")
    E.set_flags(expected, "5:3/4:snare:roll=1/4")
    E.set_flags(expected, "1:1/4:snare:accent")
    E.set_sections(expected, "Intro:1,Chorus:5")
    E.set_tempo(expected, "5:120")
    expected.title, expected.status = "Fixed", "draft"
    assert json.loads(dst.read_text()) == expected.to_dict()


def test_edit_overwrites_in_place_without_output(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    r = cli("edit", src, "--artist", "Someone", "--chart-type", "performance_chart", "--transcriber", "Ear")
    assert r.rc == 0 and f"saved {src}" in r.out
    s = Score.load(src)
    assert (s.artist, s.chart_type, s.transcriber) == ("Someone", "performance_chart", "Ear")


def test_edit_verified_everything(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    r = cli("edit", src, "--verified")
    assert r.rc == 0, r.err
    assert "marked 2 flagged bar(s) verified" in r.out
    s = Score.load(src)
    assert s.status == "verified" and not any(m.uncertain for m in s.measures)
    assert s.measures[2].notes == ["ride or hat?", "verified by ear"]


def test_edit_verified_bar_range_keeps_status(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    r = cli("edit", src, "--verified", "3", "-o", tmp_path / "v.json")
    assert r.rc == 0, r.err
    assert "marked 1 flagged bar(s) verified" in r.out
    s = Score.load(tmp_path / "v.json")
    assert s.status == "unverified_auto"
    assert [m.uncertain for m in s.measures] == [False, False, False, False, True, False]


@needs_lilypond
def test_edit_and_render(cli, tmp_path):
    src = write_score(tmp_path / "score.json")
    out = tmp_path / "pdf"
    r = cli("edit", src, "--add", "4:7/8:snare:flam", "--verified", "-o", tmp_path / "fixed.json", "--render", out)
    assert r.rc == 0, r.out + r.err
    assert "check: engraved score (LilyPond MIDI): OK" in r.out and "check: MusicXML: OK" in r.out
    assert "bars to verify" not in r.out
    for suffix in (".pdf", ".musicxml", ".mid", ".json", ".report.md"):
        assert (out / f"fixed{suffix}").exists(), suffix
    assert Score.load(out / "fixed.json").to_dict() == Score.load(tmp_path / "fixed.json").to_dict()


@pytest.mark.parametrize("args,message", [
    (["--delete", "2:1/8:snare"], "no snare at 1/8 in bar 2"),
    (["--delete", "9:0:kick"], "bar 9 does not exist"),
    (["--add", "2:1/4:snare"], "already has snare at 1/4"),
    (["--add", "2:1:snare"], "outside the bar"),
    (["--add", "2:3/8:snare:loud"], "unknown flags"),
    (["--add", "2:3/8:gong"], "unknown instrument"),
    (["--set", "2:3/8:snare:accent"], "no snare at 3/8 in bar 2"),
    (["--relabel", "ride=snare"], "snare already at 1/4"),
    (["--relabel", "ride=hihat", "--bars", "9"], "outside 1-6"),
    (["--relabel", "ride"], "FROM=TO"),
    (["--sections", "Intro:99"], "bad section entry 'Intro:99'"),
    (["--tempo", "9:120"], "bar 9 does not exist"),
    (["--tempo", "1:1000"], "outside 20-400"),
    (["--verified", "0-2"], "outside 1-6"),
])
def test_edit_errors_leave_the_score_untouched(cli, tmp_path, args, message):
    src = write_score(tmp_path / "score.json")
    original = src.read_bytes()
    r = cli("edit", src, *args, "-o", tmp_path / "out.json")
    clean_error(r, message)
    assert r.err.startswith("error: ")
    assert src.read_bytes() == original
    assert not (tmp_path / "out.json").exists()
    r = cli("edit", src, *args)  # in place: still nothing written
    clean_error(r, message)
    assert src.read_bytes() == original


# ---- verify -----------------------------------------------------------------------

def test_verify_matching_and_mismatching_exports(cli, tmp_path):
    out = tmp_path / "out"
    assert cli("render", write_chart(tmp_path / "groove.yaml"), "-o", out, "--formats", FAST).rc == 0
    xml, mid = out / "groove.musicxml", out / "groove.mid"
    r = cli("verify", out / "groove.json", "--musicxml", xml, "--midi", mid)
    assert r.rc == 0, r.out
    assert "MusicXML: OK" in r.out and "MIDI: OK" in r.out and "MusicXML schema: valid" in r.out
    # A score that no longer matches the files (one kick removed) is reported.
    s = Score.load(out / "groove.json")
    E.delete(s, "2:1/2:kick")
    s.save(tmp_path / "changed.json")
    r = cli("verify", tmp_path / "changed.json", "--musicxml", xml, "--midi", mid)
    assert r.rc == 2
    assert "MusicXML: MISMATCH" in r.out and "MIDI: MISMATCH" in r.out and "extra" in r.out


# ---- evaluate ---------------------------------------------------------------------

def test_evaluate_identical_scores_is_perfect(cli, tmp_path):
    chart = write_chart(tmp_path / "groove.yaml")
    r = cli("evaluate", chart, chart)
    assert r.rc == 0, r.err
    assert onset_f(r.out) == 1.0 and notation_f(r.out) == 1.0
    assert "Onset accuracy (tolerance 50 ms): F=1.000 P=1.000 R=1.000" in r.out
    assert "Notation accuracy (same bar, same position, same instrument): F=1.000 P=1.000 R=1.000" in r.out
    # The rendered IR of the same chart is identical too.
    assert cli("render", chart, "-o", tmp_path / "out", "--formats", "json").rc == 0
    r = cli("evaluate", chart, tmp_path / "out" / "groove.json", "--tolerance", "0.02")
    assert "tolerance 20 ms" in r.out
    assert onset_f(r.out) == 1.0 and notation_f(r.out) == 1.0


def test_evaluate_missing_stroke_lowers_recall(cli, tmp_path):
    chart = write_chart(tmp_path / "groove.yaml")
    est = load_any(chart)
    n = len(est.event_list())
    E.delete(est, "3:1/4:snare")
    est.save(tmp_path / "est.json")
    r = cli("evaluate", chart, tmp_path / "est.json")
    assert r.rc == 0
    recall = f"R={(n - 1) / n:.3f}"
    assert re.search(rf"Onset accuracy .*P=1\.000 {recall}", r.out)
    assert re.search(rf"Notation accuracy .*P=1\.000 {recall}", r.out)
    assert notation_f(r.out) < 1.0


# ---- rights gate ------------------------------------------------------------------

@pytest.fixture
def no_audio(monkeypatch):
    """Record (and refuse) any attempt to read or transcribe audio."""
    import drum_agent.audio.transcribe as T
    touched = []

    def refuse(name):
        def f(*a, **k):
            touched.append(name)
            raise AssertionError(f"{name} called")
        return f

    for name in ("load_audio", "transcribe_file", "transcribe_audio", "analyze_file"):
        monkeypatch.setattr(T, name, refuse(name))
    return touched


@pytest.mark.parametrize("exists", [True, False])
def test_transcribe_without_rights_fails_before_touching_audio(cli, tmp_path, no_audio, exists):
    wav = tmp_path / "song.wav"
    if exists:
        wav.write_bytes(b"RIFF....not really audio")
    r = cli("transcribe", wav, "-o", tmp_path / "out")
    clean_error(r, "needs a rights basis", "--rights", "analyze")
    assert "FileNotFoundError" not in r.err
    assert no_audio == []
    assert not (tmp_path / "out").exists()


def test_transcribe_rejects_an_unknown_rights_basis(cli, tmp_path, no_audio):
    r = cli("transcribe", tmp_path / "song.wav", "--rights", "found_it_online", "-o", tmp_path / "out")
    assert r.rc == 2 and "invalid choice" in r.err
    assert no_audio == []


@pytest.mark.parametrize("rights", sorted(RIGHTS))
def test_transcribe_passes_options_through(cli, tmp_path, monkeypatch, rights):
    import drum_agent.audio.transcribe as T
    seen = {}

    def fake(path, opts):
        seen["path"], seen["opts"] = path, opts
        return compile_spec(dict(EDIT_CHART, title="auto", rights=None))

    monkeypatch.setattr(T, "transcribe_file", fake)
    out = tmp_path / "out"
    r = cli("transcribe", tmp_path / "take.wav", "--rights", rights, "-o", out, "--formats", "json",
            "--bpm", 96, "--time-signature", "4/4", "--downbeat", 0.5, "--feel", "straight", "--drums-only",
            "--sensitivity", 1.5, "--no-32nds", "--start", 2, "--end", 30, "--title", "Take",
            "--sections", "A:1,B:5", "--chart-type", "performance_chart")
    assert r.rc == 0, r.err
    o = seen["opts"]
    assert Path(seen["path"]).name == "take.wav"
    assert (o.bpm, o.time_signature, o.downbeat, o.feel, o.drums_only, o.sensitivity, o.allow_32nds,
            o.start, o.end) == (96, "4/4", 0.5, "straight", True, 1.5, False, 2, 30)
    s = Score.load(out / "take.json")
    assert (s.title, s.rights, s.transcriber, s.chart_type) == ("Take", rights, "Drum Agent (automatic)",
                                                                "performance_chart")
    assert [m.section for m in s.measures] == ["A", None, None, None, "B", None]


def test_analyze_needs_no_rights(cli, tmp_path, monkeypatch):
    import drum_agent.audio.transcribe as T
    monkeypatch.setattr(T, "analyze_file", lambda path, bpm=None, time_signature=None, detector="auto":
                        {"file": str(path), "tempo": "100 BPM", "bpm_hint": bpm, "meter_hint": time_signature,
                         "detector": detector})
    r = cli("analyze", tmp_path / "song.wav", "--bpm", 100, "--time-signature", "3/4")
    assert r.rc == 0, r.err
    info = json.loads(r.out)
    assert info["bpm_hint"] == 100 and info["meter_hint"] == "3/4" and info["detector"] == "auto"
    assert "rights" not in r.err


# ---- clear errors -----------------------------------------------------------------

@pytest.mark.parametrize("command", [
    ["render", "{missing}.yaml", "-o", "{out}"],
    ["render", "{missing}.json", "-o", "{out}"],
    ["midi", "{missing}.mid", "-o", "{out}"],
    ["edit", "{missing}.json", "--title", "x"],
    ["verify", "{missing}.json"],
    ["evaluate", "{missing}.yaml", "{chart}"],
    ["evaluate", "{chart}", "{missing}.json"],
    ["synth", "{missing}.yaml", "-o", "{out}.wav"],
    ["analyze", "{missing}.wav"],
    ["transcribe", "{missing}.wav", "--rights", "own", "-o", "{out}"],
])
def test_missing_input_file(cli, tmp_path, command):
    chart = write_chart(tmp_path / "groove.yaml")
    names = {"missing": tmp_path / "nope", "out": tmp_path / "out", "chart": chart}
    r = cli(*[a.format(**names) for a in command])
    clean_error(r, "error: ", "nope")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("text,suffix,message", [
    ("sections:\n  - bars: [{sn: 'x?--'}]\n", ".yaml", "unknown symbol"),
    ("sections:\n  - bars: [{sn: 'x|x|x'}]\n", ".yaml", "beat segments"),
    ("sections:\n  - bars: [{gong: 'x---'}]\n", ".yaml", "unknown instrument"),
    ("sections:\n  - bars: [verse]\n", ".yaml", "unknown pattern 'verse'"),
    ("title: no sections\n", ".yaml", "needs a 'sections' list"),
    ("- just\n- a list\n", ".yaml", "top level must be a mapping"),
    ("title: [unclosed\n", ".yaml", "error: "),
    ("chart_type: poster\nsections:\n  - bars: [{sn: 'x---'}]\n", ".yaml", "chart_type must be one of"),
    ('{"sections": [{"bars": [{"sn": "x---", "tempo": 9999}]}]}', ".json", "outside 20-400"),
    ('{"sections": ', ".json", "error: "),
])
def test_bad_chart_spec(cli, tmp_path, text, suffix, message):
    chart = tmp_path / f"bad{suffix}"
    chart.write_text(text)
    r = cli("render", chart, "-o", tmp_path / "out", "--formats", FAST)
    clean_error(r, message)
    assert r.rc == 1 and r.err.startswith("error: ")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("sections,message", [
    ("Intro:99", "Intro:99"),
    ("Intro:1,Verse:0", "Verse:0"),
    (":1", ":1"),
    ("Intro", "Intro"),
])
def test_bad_sections_option(cli, tmp_path, sections, message):
    src = gm_drum_midi(tmp_path / "beat.mid")
    r = cli("midi", src, "-o", tmp_path / "out", "--sections", sections)
    clean_error(r, message)
    assert not (tmp_path / "out").exists()
    r = cli("edit", write_score(tmp_path / "score.json"), "--sections", sections)
    clean_error(r, message)


def test_bad_sections_on_transcribe(cli, tmp_path, monkeypatch):
    import drum_agent.audio.transcribe as T
    monkeypatch.setattr(T, "transcribe_file", lambda path, opts: compile_spec(EDIT_CHART))
    r = cli("transcribe", tmp_path / "x.wav", "--rights", "own", "-o", tmp_path / "out", "--sections", "Intro:42")
    clean_error(r, "Intro:42")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("kit,message", [
    (None, "nokit.json"),
    ({"instruments": {"gong": {"midi": 60}}}, "unknown instrument 'gong'"),
    ({"instruments": {"snare": {"colour": "red"}}}, "unsupported fields"),
    ({"instruments": {"snare": {"voice": 3}}}, "voice must be 1 (hands"),
    # Fields are written into the LilyPond source; a kit file is data, never Scheme.
    ({"instruments": {"tom1": {"position": ',(begin (system "touch PWNED") 3)'}}}, "position must be a whole number"),
    ({"instruments": {"tom1": {"notehead": "cross) (system"}}}, "notehead must be one of"),
    ({"instruments": {"tom1": {"midi": True}}}, "midi must be a note number"),
    ({"instruments": {"tom1": {"articulation": "#(system)"}}}, "articulation must be one of"),
    ({"instruments": ["tom1"]}, "expected"),
])
def test_bad_kit_file(cli, tmp_path, kit, message):
    path = tmp_path / "nokit.json"
    if kit is not None:
        path.write_text(json.dumps(kit))
    chart = write_chart(tmp_path / "groove.yaml")
    clean_error(cli("render", chart, "-o", tmp_path / "out", "--kit", path), message)
    assert not (tmp_path / "out").exists()
    clean_error(cli("midi", gm_drum_midi(tmp_path / "b.mid"), "-o", tmp_path / "out", "--kit", path), message)
    clean_error(cli("edit", write_score(tmp_path / "s.json"), "--title", "x", "--kit", path), message)
    assert not (tmp_path / "out").exists()


# ---- audio end to end (slow) ------------------------------------------------------

AUDIO_CHART = {
    "title": "CLI Audio Groove",
    "tempo": 120,
    "chart_type": "pattern_study",
    "rights": "original",
    "patterns": {"rock": {"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-------x-x-----"}},
    "sections": [{"label": "A", "bars": ["rock*5"]}],
}


@pytest.fixture(scope="module")
def groove_audio(tmp_path_factory):
    from drum_agent.synth import synthesize
    d = tmp_path_factory.mktemp("audio")
    chart = write_chart(d / "groove.yaml", AUDIO_CHART)
    wav = synthesize(load_any(chart), d / "groove.wav", method="fluidsynth")
    return chart, wav


@pytest.mark.slow
@needs_fluidsynth
def test_analyze_synthesized_audio(cli, groove_audio):
    _, wav = groove_audio
    r = cli("analyze", wav)  # no --rights: high-level analysis is always allowed
    assert r.rc == 0, r.err
    info = json.loads(r.out)
    assert info["meter"].startswith("4/4")
    bpm = float(re.match(r"[\d.]+", info["tempo"]).group())
    assert abs(bpm - 120) < 6, info["tempo"]
    assert 4 <= info["bars"] <= 6
    assert not {"measures", "hits", "events"} & set(info)  # no note-level output


@pytest.mark.slow
@needs_fluidsynth
def test_transcribe_synthesized_audio(cli, groove_audio, tmp_path):
    chart, wav = groove_audio
    out = tmp_path / "tx"
    r = cli("transcribe", wav, "--rights", "original", "-o", out, "--formats", FAST,
            "--bpm", 120, "--time-signature", "4/4", "--title", "Heard", "--sections", "Groove:1")
    assert r.rc == 0, r.out + r.err
    assert "check: MusicXML: OK" in r.out and "check: MIDI: OK" in r.out
    s = Score.load(out / "groove.json")
    assert (s.title, s.rights, s.status) == ("Heard", "original", "unverified_auto")
    assert s.transcriber == "Drum Agent (automatic)"
    assert s.measures[0].section == "Groove"
    assert "groove.wav" in s.source
    r = cli("evaluate", chart, out / "groove.json")
    assert r.rc == 0
    assert onset_f(r.out) >= 0.9, r.out


def test_verify_defaults_to_the_files_next_to_the_score(tmp_path, capsys):
    from drum_agent.cli import main
    spec = tmp_path / "g.yaml"
    spec.write_text('title: g\nsections:\n  - bars: [{hh: "x-x-x-x-", sn: "--x---x-", bd: "x---x---"}]\n')
    assert main(["render", str(spec), "-o", str(tmp_path / "out"), "--formats", "json,musicxml,midi"]) == 0
    capsys.readouterr()
    assert main(["verify", str(tmp_path / "out" / "g.json")]) == 0
    out = capsys.readouterr().out
    assert "MusicXML: OK" in out and "MIDI: OK" in out
    lonely = tmp_path / "lonely.json"
    lonely.write_text((tmp_path / "out" / "g.json").read_text())
    assert main(["verify", str(lonely)]) == 2
    assert "nothing to verify" in capsys.readouterr().err


# --- robustness (second review): the user's files and odd but valid input --------------

def test_outputs_never_replace_the_input(cli, tmp_path):
    take = gm_drum_midi(tmp_path / "drums.mid")
    before = take.read_bytes()
    clean_error(cli("midi", take, "-o", tmp_path, "--formats", "json,midi"), "overwrite the input")
    assert take.read_bytes() == before
    assert cli("midi", take, "-o", tmp_path, "--stem", "drums_chart", "--formats", "json,midi").rc == 0
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(CHART))
    clean_error(cli("render", spec, "-o", tmp_path, "--formats", "json"), "overwrite the input")
    assert json.loads(spec.read_text()) == CHART
    # Re-rendering a score.json in place (the edit-then-render loop) is allowed.
    score = write_score(tmp_path / "take.json")
    assert cli("render", score, "-o", tmp_path, "--formats", "json").rc == 0
    assert load_any(score).title == "Edit Me"


def test_edit_never_writes_json_over_a_chart_spec(cli, tmp_path):
    chart = write_chart(tmp_path / "chart.yaml")
    text = chart.read_text()
    clean_error(cli("edit", chart, "--title", "x"), "not a .json file")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(CHART))
    clean_error(cli("edit", spec, "--title", "x"), "chart spec")
    assert chart.read_text() == text and json.loads(spec.read_text()) == CHART
    assert cli("edit", chart, "--title", "x", "--output", tmp_path / "edited.json").rc == 0
    assert load_any(tmp_path / "edited.json").title == "x"


@needs_lilypond
def test_rendering_keeps_other_charts_pages_and_takes_brackets_in_names(cli, tmp_path):
    a, b = write_chart(tmp_path / "groove_fill.yaml"), write_chart(tmp_path / "groove.yaml")
    assert cli("render", a, "-o", tmp_path / "out", "--formats", "pdf").rc == 0
    assert cli("render", b, "-o", tmp_path / "out", "--formats", "pdf").rc == 0
    assert {p.name for p in (tmp_path / "out").glob("*.png")} == {"groove.png", "groove_fill.png"}
    live = write_chart(tmp_path / "My Song [Live].yaml")
    assert cli("render", live, "-o", tmp_path / "out", "--formats", "pdf").rc == 0
    assert (tmp_path / "out" / "My Song [Live].png").exists()


@needs_lilypond
def test_verify_takes_the_kit_the_files_were_rendered_with(cli, tmp_path):
    kit = tmp_path / "kit.json"
    kit.write_text(json.dumps({"instruments": {"snare": {"midi": 40}}}))
    assert cli("render", write_chart(tmp_path / "g.yaml"), "-o", tmp_path / "out", "--kit", kit).rc == 0
    assert cli("verify", tmp_path / "out" / "g.json").rc == 2  # wrong kit: the notes differ
    assert cli("verify", tmp_path / "out" / "g.json", "--kit", kit).rc == 0


@pytest.mark.parametrize("pickup,message", [("1", "shorter than the first bar"), ("5/4", "shorter than the first bar"),
                                            ("1/3", "32nd notes")])
def test_impossible_pickups_are_refused_not_dropped(cli, tmp_path, pickup, message):
    clean_error(cli("midi", gm_drum_midi(tmp_path / "b.mid"), "-o", tmp_path / "out", "--pickup", pickup), message)


def test_midi_channel_must_exist(cli, tmp_path):
    r = cli("midi", gm_drum_midi(tmp_path / "b.mid"), "-o", tmp_path / "out", "--channel", "17")
    assert r.rc == 2 and "1-16" in r.err


@pytest.mark.parametrize("size", ["0", "-20", "nan", "inf", "big"])
def test_staff_size_must_be_a_positive_number(cli, tmp_path, size):
    r = cli("midi", gm_drum_midi(tmp_path / "b.mid"), "-o", tmp_path / "out", "--staff-size", size)
    assert r.rc == 2 and "positive number" in r.err


def test_yaml_text_fields_keep_what_was_written(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text('title: 1999\nartist: Yes\ntranscriber: 311\ntempo: 100\nsections:\n'
                 '  - label: 2\n    tempo_text: 1.10\n    bars: [{sn: "x-x-"}]\n  - label: ~\n    bars: [{sn: "x-x-"}]\n')
    s = load_any(p)
    assert (s.title, s.artist, s.transcriber) == ("1999", "Yes", "311")
    assert (s.measures[0].section, s.measures[0].tempo_text, s.measures[1].section) == ("2", "1.10", None)
    assert compile_spec(dict(CHART, title=1999)).title == "1999"  # JSON has numbers, not unquoted text
    with pytest.raises(ValueError, match="must be text"):
        compile_spec(dict(CHART, artist=True))


@pytest.mark.parametrize("spec,message", [
    ({"title": "t", "sections": 5}, "'sections' list"),
    ({"title": "t", "sections": [{"bars": 5}]}, "'bars' must be a list"),
    ({"title": "t", "patterns": 5, "sections": [{"bars": ["g"]}]}, "'patterns' must map"),
    ({"title": "t", "tempo": "fast", "sections": [{"bars": [{"sn": "x-x-"}]}]}, "tempo 'fast'"),
    ({"title": "t", "sections": [{"repeat": "two", "bars": [{"sn": "x-x-"}]}]}, "'repeat' must be"),
])
def test_malformed_specs_say_what_is_wrong(cli, tmp_path, spec, message):
    clean_error(cli("render", write_chart(tmp_path / "bad.yaml", spec), "-o", tmp_path / "out"), message)


def test_any_script_in_titles_and_sections_survives_midi(tmp_path):
    from drum_agent.export.midi import write_midi
    from drum_agent.io_midi import read_midi
    s = compile_spec(dict(CHART, title="紅蓮華 – Don’t", sections=[{"label": "Chorus – out", "bars": ["hat"]}]))
    write_midi(s, tmp_path / "u.mid")
    back, _ = read_midi(tmp_path / "u.mid")
    assert back.measures[0].section == "Chorus – out"
    legacy = mido.MidiFile()  # older files: Latin-1 text
    legacy.tracks.append(mido.MidiTrack([mido.MetaMessage("marker", text="Café", time=0),
                                         mido.Message("note_on", channel=9, note=38, velocity=90, time=0),
                                         mido.Message("note_off", channel=9, note=38, velocity=0, time=240)]))
    legacy.save(tmp_path / "l.mid")
    assert read_midi(tmp_path / "l.mid")[0].measures[0].section == "Café"


@needs_lilypond
def test_text_is_printed_never_executed(tmp_path):
    from drum_agent.pipeline import export_all
    marker = tmp_path / "PWNED"
    for k, text in enumerate([f'#(system "touch {marker}")', f'$(system "touch {marker}")', 'Quote " and \\ back',
                              '} \\score { c }', "NUL\x00 and \x01 controls"]):
        s = compile_spec(dict(CHART, title=text, artist=text,
                              sections=[{"label": text, "tempo_text": text, "bars": ["hat"]}]))
        report = export_all(s, tmp_path / str(k), "s")
        assert report.rendering_ok and not report.musicxml_errors
    assert not marker.exists()
