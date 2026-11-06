"""Practice versions (simplify.py): a subset of the transcription's notes, labelled as such,
and a version beside the transcription, never in its place."""

import json
from fractions import Fraction as F
from pathlib import Path

import pytest
from conftest import needs_lilypond

from drum_agent.charts import compile_spec, load_any
from drum_agent.export.lilypond import header
from drum_agent.model import Hit, Measure, Score, TimeSig
from drum_agent.simplify import BEAT, EIGHTH, FINER, SIXTEENTH, place, simplify
from drum_agent.validate import validate_score

ROOT = Path(__file__).parent.parent


def bar(hits, time="4/4", **kw):
    return Measure(time_sig=TimeSig.parse(time), hits=[Hit(pos=F(p), inst=i, **o) for p, i, o in hits], **kw)


def score(*bars, tempo=100):
    bars[0].tempo = tempo
    return Score(measures=list(bars), title="Test", status="unverified_auto", rights="original")


def notes(s):
    return {(i, h.pos, h.inst) for i, _, h in s.iter_hits()}


def test_how_strong_a_place_is():
    m = bar([])
    assert [place(m, F(p)) for p in ("0", "1/4", "1/8", "1/16", "3/16", "1/32")] == [BEAT, BEAT, EIGHTH, SIXTEENTH, SIXTEENTH, FINER]
    assert [place(m, F(p)) for p in ("1/6", "1/12")] == [EIGHTH, FINER]  # shuffled off-beat; middle triplet
    six8 = bar([], "6/8")
    assert [place(six8, F(p)) for p in ("0", "1/8", "1/4", "3/8", "1/16")] == [BEAT, EIGHTH, EIGHTH, BEAT, SIXTEENTH]
    seven8 = Measure(time_sig=TimeSig.parse("7/8", (2, 2, 3)))
    assert [place(seven8, F(p)) for p in ("0", "1/4", "1/2", "5/8", "3/4")] == [BEAT, BEAT, BEAT, EIGHTH, EIGHTH]
    pickup = bar([], length=F(1, 8))  # an 8th before the barline: on the & of 4
    assert place(pickup, F(0)) == EIGHTH


GROOVE = bar([
    ("0", "hihat", {}), ("1/16", "hihat", {}), ("1/8", "hihat", {}), ("3/16", "hihat", {}), ("1/4", "hihat", {}),
    ("1/2", "hihat_open", {}), ("5/8", "hihat", {}),
    ("0", "kick", {}), ("3/16", "kick", {}), ("3/8", "kick", {}), ("1/2", "kick", {}),
    ("1/4", "snare", {"accent": True, "velocity": 118}), ("7/16", "snare", {"ghost": True, "velocity": 30}),
    ("3/4", "snare", {"flam": True}), ("1/32", "snare", {}),
    ("1/4", "hihat_pedal", {}), ("1/8", "hihat_pedal", {}),
    ("0", "crash", {"choke": True}),
])


def test_intermediate_keeps_the_part_without_its_ornaments():
    s = simplify(score(GROOVE), "intermediate")
    m = s.measures[0]
    assert {(h.pos, h.inst) for h in m.hits} == {
        (F(0), "hihat"), (F(1, 8), "hihat"), (F(1, 4), "hihat"), (F(1, 2), "hihat_open"), (F(5, 8), "hihat"),
        (F(0), "kick"), (F(3, 16), "kick"), (F(3, 8), "kick"), (F(1, 2), "kick"),
        (F(1, 4), "snare"), (F(3, 4), "snare"), (F(1, 4), "hihat_pedal"), (F(0), "crash")}
    by = {(h.pos, h.inst): h for h in m.hits}
    assert by[(F(1, 4), "snare")].accent and not by[(F(3, 4), "snare")].flam and by[(F(0), "crash")].choke


def test_beginner_is_the_time_and_the_backbeat():
    s = simplify(score(GROOVE), "beginner")
    m = s.measures[0]
    assert {(h.pos, h.inst) for h in m.hits} == {
        (F(0), "hihat"), (F(1, 8), "hihat"), (F(1, 4), "hihat"), (F(1, 2), "hihat_open"), (F(5, 8), "hihat"),
        (F(0), "kick"), (F(1, 2), "kick"), (F(1, 4), "snare"), (F(3, 4), "snare"), (F(0), "crash")}
    assert not any(h.accent or h.choke or h.flam for h in m.hits)


def test_a_fast_song_keeps_a_beginner_on_the_beats():
    s = simplify(score(GROOVE, tempo=160), "beginner")
    assert {h.pos for h in s.measures[0].hits if h.inst.startswith("hihat")} == {F(0), F(1, 4), F(1, 2)}


def test_a_fill_is_thinned_to_the_8ths():
    fill = bar([(f"{k}/16", "snare", {}) for k in range(16)], cue="Fill")
    plain = bar([(f"{k}/16", "snare", {}) for k in range(16)])
    s = simplify(score(fill, plain), "intermediate")
    assert len(s.measures[0].hits) == 8 and len(s.measures[1].hits) == 16
    assert s.measures[0].cue == "Fill"


def test_a_played_bar_never_goes_silent():
    off = bar([("1/16", "snare", {}), ("3/16", "tom1", {}), ("7/16", "kick", {})])
    empty = bar([])
    ghosts = bar([("1/32", "snare", {"ghost": True, "velocity": 30})])
    s = simplify(score(off, empty, ghosts), "beginner")
    assert [(h.pos, h.inst) for h in s.measures[0].hits] == [(F(1, 16), "snare")]
    assert s.measures[1].hits == []
    assert [(h.pos, h.ghost) for h in s.measures[2].hits] == [(F(1, 32), False)]


def test_it_is_labelled_and_the_transcription_is_untouched():
    src = score(GROOVE)
    src.measures[0].uncertain = True
    src.analysis = {"detected_onsets": 20, "instrument_counts": {"snare": 4}, "feel": "straight"}
    before = json.dumps(src.to_dict(), sort_keys=True)
    s = simplify(src, "beginner")
    assert json.dumps(src.to_dict(), sort_keys=True) == before
    assert (s.chart_type, s.status) == ("practice_beginner", "simplified")
    assert s.analysis["feel"] == "straight" and "detected_onsets" not in s.analysis and "instrument_counts" not in s.analysis
    assert s.analysis["simplified"] == {"level": "beginner", "kept": 10, "of": 18}
    assert not s.measures[0].uncertain
    text = header(s)
    assert "Practice Version: Beginner" in text and "Simplified from the transcription, not what was played" in text
    with pytest.raises(ValueError, match="already a practice version"):
        simplify(s, "intermediate")
    with pytest.raises(ValueError, match="level must be"):
        simplify(src, "expert")


GROOVES = sorted((ROOT / "library" / "grooves").glob("*.yaml"))


def test_the_library_is_there_to_try_it_on():
    assert len(GROOVES) == 73


@pytest.mark.parametrize("path", GROOVES, ids=[p.stem for p in GROOVES])
def test_on_every_groove_in_the_library_it_only_ever_leaves_notes_out(path):
    src = load_any(path)
    easy, easier = simplify(src, "intermediate"), simplify(src, "beginner")
    assert notes(easier) <= notes(src) and notes(easy) <= notes(src)
    assert len(easier.event_list()) <= len(easy.event_list()) <= len(src.event_list())
    for s in (easy, easier):
        assert validate_score(s).ok
        for m, was in zip(s.measures, src.measures):
            assert bool(m.hits) == bool(was.hits)  # no played bar goes silent
            for h in m.hits:
                assert not (h.ghost or h.flam or h.drag or h.roll)
            old = {(h.pos, h.inst): h for h in was.hits}
            assert all(h.velocity == old[(h.pos, h.inst)].velocity for h in m.hits)


# ---- in the studio ---------------------------------------------------------------------------

@pytest.fixture
def studio(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from drum_agent.audio import separate
    from drum_agent.synth import synthesize
    from drum_agent.web import providers
    from drum_agent.web.app import create_app
    monkeypatch.setattr(separate, "available", lambda: False)
    groove = {"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x--x-x--"}
    spec = compile_spec({"title": "Practice", "tempo": 100, "rights": "original",
                         "sections": [{"label": "A", "bars": [groove] * 4}]})
    wav = synthesize(spec, tmp_path / "take.wav", method="numpy").read_bytes()
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with TestClient(app) as c:
        sid = c.post("/api/songs", json={"title": "Practice", "artist": "Tester"}).json()["song"]["id"]
        r = c.post(f"/api/songs/{sid}/upload", files={"file": ("t.wav", wav, "audio/wav")}, data={"rights": "original"})
        done = app.state.runner.wait(r.json()["job"]["id"], timeout=300)
        assert done["status"] == "succeeded", (done["error_code"], done["error"], done["stage"])
        c.song_id, c.chart_id, c.store = sid, done["chart_id"], app.state.store
        yield c


@needs_lilypond
def test_a_practice_version_stands_beside_the_transcription(studio):
    c, cid = studio, studio.chart_id
    original = c.get(f"/api/charts/{cid}/files/chart.json").content
    r = c.post(f"/api/charts/{cid}/simplify", json={"level": "beginner"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["origin"], p["parent_id"], p["note"]) == ("simplified", cid, "Beginner practice version")
    assert p["version"] == 2 and p["summary"]["chart_type"] == "practice_beginner"
    # The song's chart is still the transcription, and it hasn't changed.
    assert c.store.latest_chart(c.song_id)["id"] == cid
    assert c.get(f"/api/charts/{cid}/files/chart.json").content == original
    assert c.get(f"/api/projects/{c.song_id}").json()["charts"][0]["id"] == p["id"]
    assert [x["chart"]["id"] for x in c.get("/api/projects").json()["projects"]] == [cid]
    # Asked again it's the same version, not another copy; it listens along like the transcription.
    assert c.post(f"/api/charts/{cid}/simplify", json={"level": "beginner"}).json()["id"] == p["id"]
    assert c.get(f"/api/charts/{p['id']}").json()["has_audio"] is True
    assert c.post(f"/api/charts/{cid}/simplify", json={"level": "expert"}).status_code == 422
    r = c.get(f"/api/charts/{p['id']}/files/chart.pdf", params={"download": 1})
    assert "beginner%20practice" in r.headers["content-disposition"]


@needs_lilypond
def test_it_stays_a_practice_version_whatever_is_done_to_it(studio):
    c, cid = studio, studio.chart_id
    p = c.post(f"/api/charts/{cid}/simplify", json={"level": "intermediate"}).json()
    assert c.post(f"/api/charts/{p['id']}/simplify", json={"level": "beginner"}).status_code == 409
    info = c.get(f"/api/charts/{p['id']}").json()
    assert info["can_rechart"] is False
    assert c.post(f"/api/charts/{p['id']}/rechart", json={"bpm": 120}).status_code == 409
    # An edit is a new practice version; a restored one too. Neither becomes the song's chart.
    score = c.get(f"/api/charts/{p['id']}/files/chart.json").json()
    score["measures"][0]["hits"].pop()
    e = c.post(f"/api/projects/{c.song_id}/versions", json={"score": score, "note": "Edited", "base_chart_id": p["id"]})
    assert e.status_code == 200 and e.json()["origin"] == "simplified", e.text
    r = c.post(f"/api/charts/{p['id']}/restore")
    assert r.status_code == 200 and r.json()["origin"] == "simplified"
    assert c.store.latest_chart(c.song_id)["id"] == cid


@needs_lilypond
def test_a_beat_is_not_a_transcription(tmp_path):
    from fastapi.testclient import TestClient

    from drum_agent.web import providers
    from drum_agent.web.app import create_app
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with TestClient(app) as c:
        job = c.post("/api/beats", json={"prompt": "a rock beat at 120 BPM, 4 bars"}).json()["job"]
        done = app.state.runner.wait(job["id"], timeout=120)
        assert done["status"] == "succeeded", done["error"]
        assert c.post(f"/api/charts/{done['chart_id']}/simplify", json={"level": "beginner"}).status_code == 409


@needs_lilypond
def test_the_command_line_writes_one_from_a_chart_file(tmp_path, capsys):
    from drum_agent.cli import main
    src = score(GROOVE)
    path = tmp_path / "groove.json"
    src.save(path)
    assert main(["simplify", str(path), "--level", "beginner", "--out", str(tmp_path / "out")]) == 0
    made = Score.load(tmp_path / "out" / "groove-beginner.json")
    assert made.status == "simplified" and notes(made) <= notes(src)
    assert (tmp_path / "out" / "groove-beginner.pdf").is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "unverified_auto"
