"""The web app: audio preparation, chart validation, providers, Claude, store and API.

Providers and Claude are exercised through their real client code with a mocked HTTP
transport (isolated tests only); nothing here reaches the network.
"""

import io
import json
import shutil
import subprocess
from fractions import Fraction

import httpx
import numpy as np
import pytest
import soundfile as sf
from conftest import needs_fluidsynth, needs_lilypond

from drum_agent.audio.prepare import (
    INTERNAL_CHANNELS,
    INTERNAL_SR,
    AudioError,
    prepare,
    sniff,
)
from drum_agent.charts import compile_spec
from drum_agent.model import Hit
from drum_agent.validate import chart_status, validate_score
from drum_agent.web import claude, providers
from drum_agent.web.store import Store, song_id_for

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}


def song_spec(bars=8, tempo=100):
    return compile_spec({"title": "Test Song", "artist": "Tester", "tempo": tempo, "rights": "original",
                         "sections": [{"label": "A", "bars": [GROOVE] * (bars // 2)},
                                      {"label": "B", "bars": [GROOVE] * (bars - bars // 2)}]})


def tone(path, seconds, sr=22050, channels=1, level=0.3):
    t = np.arange(int(seconds * sr)) / sr
    y = level * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), np.stack([y] * channels, axis=1) if channels > 1 else y, sr)
    return path


# ---- audio preparation ----------------------------------------------------------------

@needs_ffmpeg
def test_prepare_normalizes_to_the_internal_format_and_keeps_the_duration(tmp_path):
    src = tone(tmp_path / "in.wav", 7.25, sr=22050, channels=1)
    out = prepare(src, tmp_path / "out.wav")
    info = sf.info(str(out.path))
    assert (info.samplerate, info.channels) == (INTERNAL_SR, INTERNAL_CHANNELS)
    assert abs(info.frames / info.samplerate - 7.25) < 1e-3
    assert abs(out.duration_s - 7.25) < 1e-3
    assert (out.original_sample_rate, out.original_channels, out.original_codec) == (22050, 1, "pcm_s16le")


@needs_ffmpeg
def test_prepare_keeps_the_duration_of_a_compressed_file(tmp_path):
    wav = tone(tmp_path / "in.wav", 12.0, sr=48000, channels=2)
    mp3 = tmp_path / "in.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
    out = prepare(mp3, tmp_path / "out.wav")
    assert abs(out.duration_s - 12.0) < 0.06  # MP3 encoder padding is trimmed by the decoder


@needs_ffmpeg
@pytest.mark.parametrize("make, code", [
    (lambda p: p.write_bytes(b""), "empty"),
    (lambda p: p.write_bytes(b"this is not audio at all, just text" * 20), "bad_signature"),
    (lambda p: p.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(256)) * 40), "unreadable"),
])
def test_prepare_refuses_corrupt_files(tmp_path, make, code):
    src = tmp_path / "song.mp3"
    make(src)
    with pytest.raises(AudioError) as e:
        prepare(src, tmp_path / "out.wav")
    assert e.value.code in (code, "decode_failed", "no_audio", "unreadable")
    assert not (tmp_path / "out.wav").exists()


@needs_ffmpeg
def test_prepare_refuses_truncated_short_silent_and_unsupported_files(tmp_path):
    wav = tone(tmp_path / "long.wav", 20.0, sr=44100, channels=2)
    data = wav.read_bytes()
    cut = tmp_path / "cut.wav"
    cut.write_bytes(data[: len(data) // 3])  # the header still announces 20 s
    with pytest.raises(AudioError) as e:
        prepare(cut, tmp_path / "o1.wav")
    assert e.value.code == "truncated"
    mp3 = tmp_path / "long.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
    cut_mp3 = tmp_path / "cut.mp3"
    cut_mp3.write_bytes(mp3.read_bytes()[: mp3.stat().st_size // 3])  # the Xing header still says 20 s
    with pytest.raises(AudioError) as e:
        prepare(cut_mp3, tmp_path / "o1b.wav")
    assert e.value.code == "truncated"
    with pytest.raises(AudioError) as e:
        prepare(tone(tmp_path / "short.wav", 2.0), tmp_path / "o2.wav")
    assert e.value.code == "too_short"
    with pytest.raises(AudioError) as e:
        prepare(tone(tmp_path / "quiet.wav", 8.0, level=0.0), tmp_path / "o3.wav")
    assert e.value.code == "silent"
    exe = tmp_path / "song.exe"
    exe.write_bytes(b"MZ" + b"\0" * 100)
    with pytest.raises(AudioError) as e:
        prepare(exe, tmp_path / "o4.wav")
    assert e.value.code == "unsupported_type"


def test_sniff_recognizes_containers():
    assert sniff(b"RIFF\0\0\0\0WAVEfmt ") == "wav"
    assert sniff(b"fLaC\0\0\0\0") == "flac"
    assert sniff(b"ID3\x04") == "mp3"
    assert sniff(b"\0\0\0\x20ftypM4A ") == "m4a"
    assert sniff(b"<html>") is None


# ---- chart validation -----------------------------------------------------------------

def test_a_valid_written_chart_is_complete():
    v = validate_score(song_spec())
    assert v.ok and not v.needs_review
    assert chart_status(v, rendering_ok=True) == "COMPLETE"
    assert chart_status(v, rendering_ok=False) == "NEEDS_CORRECTION"


def test_an_off_grid_stroke_or_a_wrong_bar_length_fails_validation():
    s = song_spec()
    s.measures[2].hits.append(Hit(Fraction(1, 7), "snare"))
    v = validate_score(s)
    assert not v.ok and any(c.name == "subdivisions" and not c.ok for c in v.checks)
    s = song_spec()
    s.measures[3].length = Fraction(1, 2)  # a short bar that is not a pickup
    assert not validate_score(s).ok


def test_uncertain_bars_and_strokes_outside_the_timeline_need_correction():
    s = song_spec()
    s.measures[5].uncertain = True
    v = validate_score(s)
    assert v.ok and v.needs_review and chart_status(v, True) == "NEEDS_CORRECTION"
    s = song_spec(tempo=120)  # bars of 2 s
    for i, m in enumerate(s.measures):
        m.start_time = 2.0 * i
        for h in m.hits:
            h.time = m.start_time + float(h.pos) * 4 * 0.5
    s.measures[-1].hits[0].time = 40.0  # far past the last bar
    v = validate_score(s, audio_duration=17.0)
    cov = next(c for c in v.checks if c.name == "timeline coverage")
    assert not cov.ok and "outside" in cov.detail


# ---- providers ------------------------------------------------------------------------

def test_query_split_and_version_labels():
    assert providers.split_query("American Idiot - Green Day") == ("American Idiot", "Green Day")
    assert providers.split_query("Holiday") == ("Holiday", None)
    assert providers.version_of("American Idiot (Live at Wembley)") == "live"
    assert providers.version_of("Basket Case", "Dookie (Remastered 2009)") == "remaster"
    assert providers.version_of("Basket Case (Demo)") == "demo"
    assert providers.version_of("Basket Case", "Dookie") == "studio"
    assert providers.iso_duration("PT3M15S") == 195.0 and providers.iso_duration("PT1H2S") == 3602.0


def test_spotify_search_uses_client_credentials_and_returns_metadata_only():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.host == "accounts.spotify.com":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.params["type"] == "track"
        return httpx.Response(200, json={"tracks": {"items": [
            {"id": "6nTiIhLmQ3FWhvrGafw2zj", "name": "American Idiot", "duration_ms": 176346,
             "artists": [{"name": "Green Day"}], "external_ids": {"isrc": "USRE10400888"},
             "album": {"name": "American Idiot", "release_date": "2004-09-21"},
             "external_urls": {"spotify": "https://open.spotify.com/track/6nTiIhLmQ3FWhvrGafw2zj"}},
            {"id": "x2", "name": "American Idiot - Live", "duration_ms": 200000, "artists": [{"name": "Green Day"}],
             "album": {"name": "Bullet in a Bible", "release_date": "2005"}}]}})

    sp = providers.Spotify("id", "secret", transport=httpx.MockTransport(handler))
    out = sp.search("American Idiot", "Green Day")
    assert [r["version"] for r in out] == ["studio", "live"]
    assert out[0]["isrc"] == "USRE10400888" and out[0]["duration_s"] == 176.3 and out[0]["year"] == 2004
    assert out[0]["analyzable"] is False and "preview_url" not in json.dumps(out)
    assert out[0]["id"] == song_id_for("American Idiot", "Green Day", "isrc", "USRE10400888")
    sp.search("American Idiot", "Green Day")
    assert calls.count("/api/token") == 1  # the token is reused until it expires


def test_unavailable_providers_are_reported_not_hidden():
    sp = providers.Spotify("id", "secret", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    yt = providers.YouTube(None)
    p = providers.Providers(spotify=sp, youtube=yt, public=False)
    results, states = p.search("Holiday - Green Day")
    assert results == []
    assert {s["provider"]: s["state"] for s in states} == {"spotify": "error", "youtube": "not_configured"}


def test_youtube_results_carry_durations_and_are_not_analyzable():
    def handler(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "Ee_uujKuJMI"}, "snippet": {
                "title": "Green Day - American Idiot [Official Music Video]", "channelTitle": "Green Day",
                "publishedAt": "2009-10-25T00:00:00Z"}}]})
        return httpx.Response(200, json={"items": [{"id": "Ee_uujKuJMI", "contentDetails": {"duration": "PT3M9S"}}]})

    out = providers.YouTube("key", transport=httpx.MockTransport(handler)).search("American Idiot", "Green Day")
    assert out[0]["duration_s"] == 189.0 and out[0]["provider"] == "youtube" and not out[0]["analyzable"]


# ---- Claude ---------------------------------------------------------------------------

class FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        block = type("B", (), {"type": "text", "text": self.text})()
        usage = type("U", (), {"input_tokens": 300, "output_tokens": 80})()
        return type("R", (), {"content": [block], "stop_reason": self.stop_reason, "usage": usage, "model": kw["model"]})()


def test_claude_suggestion_is_structured_and_validated(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DRUM_AGENT_ANTHROPIC_MODEL", "test-model")
    s = song_spec()
    answer = {"sections": [{"first_bar": 1, "name": "Verse 1", "reason": "groove"},
                           {"first_bar": 5, "name": "Chorus", "reason": "same groove, later"}],
              "confidence": "low", "comment": "Two identical sections."}
    fake = type("C", (), {"messages": FakeMessages(json.dumps(answer))})()
    out = claude.suggest_section_names(s, client=fake)
    assert [x["name"] for x in out["sections"]] == ["Verse 1", "Chorus"]
    sent = fake.messages.calls[0]
    assert sent["model"] == "test-model" and sent["output_config"]["format"]["type"] == "json_schema"
    assert "test-key" not in json.dumps(sent)  # the key goes in the client, never in the prompt

    moved = {**answer, "sections": [{**answer["sections"][0]}, {**answer["sections"][1], "first_bar": 4}]}
    fake = type("C", (), {"messages": FakeMessages(json.dumps(moved))})()
    with pytest.raises(claude.ClaudeUnavailable) as e:
        claude.suggest_section_names(s, client=fake)
    assert e.value.code == "invalid_answer"
    bad = {**answer, "sections": [{**answer["sections"][0], "name": "Banana"}, answer["sections"][1]]}
    with pytest.raises(claude.ClaudeUnavailable):
        claude.suggest_section_names(s, client=type("C", (), {"messages": FakeMessages(json.dumps(bad))})())
    with pytest.raises(claude.ClaudeUnavailable) as e:
        claude.suggest_section_names(s, client=type("C", (), {"messages": FakeMessages("", "refusal")})())
    assert e.value.code == "refused"


def test_claude_not_configured_and_api_errors_are_reported(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(claude.ClaudeUnavailable) as e:
        claude.suggest_section_names(song_spec())
    assert e.value.code == "not_configured"
    import anthropic
    httpx2 = pytest.importorskip("httpx2")  # the HTTP client this SDK version is built on
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    monkeypatch.setenv("DRUM_AGENT_ANTHROPIC_MODEL", "test-model")
    for status, code in ((401, "auth"), (404, "bad_model"), (429, "rate_limited"), (500, "api_error")):
        transport = httpx2.MockTransport(lambda r, s=status: httpx2.Response(
            s, json={"type": "error", "error": {"type": "x", "message": "nope"}}))
        client = anthropic.Anthropic(api_key="bad-key", base_url="https://api.anthropic.com", max_retries=0,
                                     http_client=httpx2.Client(transport=transport))
        with pytest.raises(claude.ClaudeUnavailable) as e:
            claude.suggest_section_names(song_spec(), client=client)
        assert e.value.code == code


# ---- store ----------------------------------------------------------------------------

def test_store_versions_and_dedupes(tmp_path):
    st = Store(tmp_path)
    song = st.upsert_song(title="Holiday", artist="Green Day", provider="spotify", provider_id="abc")
    assert st.upsert_song(title="Holiday", artist="Green Day", provider="spotify", provider_id="abc")["id"] == song["id"]
    a = st.add_source(song_id=song["id"], kind="upload", rights="own", sha256="f" * 64, path="/x", original_name="a", info={})
    b = st.add_source(song_id=song["id"], kind="upload", rights="own", sha256="f" * 64, path="/x", original_name="a", info={})
    assert a["id"] == b["id"]
    c1 = st.add_chart(chart_id="ch_" + "1" * 16, song_id=song["id"], status="NEEDS_CORRECTION", origin="transcription",
                      bars=8, validation={}, summary={})
    c2 = st.add_chart(chart_id="ch_" + "2" * 16, song_id=song["id"], status="COMPLETE", origin="correction",
                      bars=8, validation={}, summary={}, parent_id=c1["id"])
    assert (c1["version"], c2["version"]) == (1, 2) and st.latest_chart(song["id"])["id"] == c2["id"]
    assert [s["id"] for s in st.find_songs("holiday green")] == [song["id"]]
    assert st.find_songs("basket case") == []


# ---- API ------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from drum_agent.web.app import create_app
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with TestClient(app) as c:
        c.app_state = app.state
        yield c


def _song(client, title="Test Song", artist="Tester"):
    return client.post("/api/songs", json={"title": title, "artist": artist}).json()


def test_api_health_and_secrets(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    body = client.get("/api/health").json()
    assert body["checks"]["database"]["ok"] and "rights_options" in body
    assert "sk-secret-value" not in json.dumps(body)


def test_api_song_without_a_source_needs_one(client):
    d = _song(client)
    assert d["status"] == "NEEDS_SOURCE" and d["resolution"]["case"] == "NEEDS_SOURCE"
    assert client.post(f"/api/songs/{d['song']['id']}/jobs").status_code == 409
    r = client.get("/api/search", params={"q": "Test Song - Tester"}).json()
    assert [s["id"] for s in r["catalog"]] == [d["song"]["id"]]
    assert {p["provider"]: p["state"] for p in r["providers"]} == {"spotify": "not_configured", "youtube": "not_configured"}


@needs_ffmpeg
def test_api_upload_needs_rights_and_refuses_corrupt_files(client, tmp_path):
    sid = _song(client)["song"]["id"]
    wav = tone(tmp_path / "a.wav", 8.0).read_bytes()
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("a.wav", wav, "audio/wav")}, data={"rights": ""})
    assert r.status_code == 403 and "rights basis" in r.json()["detail"]
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("a.wav", wav, "audio/wav")}, data={"rights": "stolen"})
    assert r.status_code == 403
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("../../etc/x.mp3", b"garbage" * 100, "audio/mpeg")},
                    data={"rights": "own"})
    assert r.status_code == 422 and r.json()["error"] == "bad_signature"
    assert client.get(f"/api/songs/{sid}").json()["status"] == "NEEDS_SOURCE"


def test_api_rejects_bad_ids_and_unlisted_files(client):
    assert client.get("/api/songs/../../etc/passwd").status_code == 404
    assert client.get("/api/songs/s_zzzz").status_code == 404
    assert client.get("/api/charts/ch_0123456789abcdef/files/chart.pdf").status_code == 404
    assert client.get("/api/jobs/job_0123456789abcdef").status_code == 404


@needs_lilypond
@needs_fluidsynth
@needs_ffmpeg
def test_api_upload_transcribe_view_download_review(client, tmp_path):
    from drum_agent.synth import synthesize
    sid = _song(client)["song"]["id"]
    wav = synthesize(song_spec(bars=8, tempo=100), tmp_path / "take.wav", method="fluidsynth")
    data = wav.read_bytes()
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("take.wav", data, "audio/wav")}, data={"rights": "original"})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    done = client.app_state.runner.wait(job["id"], timeout=300)
    assert done["status"] == "succeeded", done
    assert [s["name"] for s in done["stages"]] == ["prepare", "detect", "beats", "measures", "sections", "validate",
                                                   "render", "view", "save"]
    # The same recording again: no second analysis.
    r2 = client.post(f"/api/songs/{sid}/upload", files={"file": ("take.wav", data, "audio/wav")}, data={"rights": "original"})
    assert r2.json()["job"]["id"] == job["id"] and r2.json()["created"] is False

    chart = client.get(f"/api/charts/{done['chart_id']}").json()
    assert chart["status"] in ("COMPLETE", "NEEDS_CORRECTION") and chart["bars"] >= 8
    assert chart["view"]["unmapped_bars"] == 0 and len(chart["view"]["bars"]) >= 1
    assert all(c["ok"] for c in chart["validation"]["checks"] if c["severity"] == "error")
    pdf = client.get(chart["files"]["chart.pdf"], params={"download": 1})
    assert pdf.content[:4] == b"%PDF" and "attachment" in pdf.headers["content-disposition"]
    assert client.get(f"/api/charts/{chart['id']}/files/page-1.svg").headers["content-type"].startswith("image/svg")
    assert client.get(f"/api/charts/{chart['id']}/files/chart.ly").status_code == 404
    assert client.get(f"/api/charts/{chart['id']}/audio").status_code == 200

    # Section names: a new version; the boundaries can't move.
    names = [{"first_bar": s["score_bar"], "name": f"Part {k}"} for k, s in enumerate(chart["view"]["sections"], 1)]
    assert client.post(f"/api/charts/{chart['id']}/sections",
                       json={"sections": [{**names[0], "first_bar": names[0]["first_bar"] + 1}] + names[1:]}).status_code == 422
    v2 = client.post(f"/api/charts/{chart['id']}/sections", json={"sections": names}).json()
    assert v2["version"] == 2 and v2["parent_id"] == chart["id"]
    flagged = [b for bar in chart["view"]["bars"] if bar["uncertain"] for b in bar["score_bars"]]
    if flagged:
        v3 = client.post(f"/api/charts/{v2['id']}/review", json={"bars": flagged}).json()
        assert v3["version"] == 3
        assert not any(b["uncertain"] for b in client.get(f"/api/charts/{v3['id']}").json()["view"]["bars"])
    # Claude isn't configured in tests: a clear 503, not a fake suggestion.
    r = client.post(f"/api/charts/{chart['id']}/suggest-sections")
    assert r.status_code == 503 and r.json()["error"] == "not_configured"


@needs_ffmpeg
def test_jobs_cancel_retry_and_recover(tmp_path):
    from drum_agent.web.jobs import JobRunner
    st = Store(tmp_path)
    runner = JobRunner(st, start=False)
    song = st.upsert_song(title="X", artist="Y")
    src = st.add_source(song_id=song["id"], kind="upload", rights="own", sha256="a" * 64,
                        path=str(tmp_path / "missing.wav"), original_name="x.wav", info={})
    job, created = runner.submit(song["id"], src["id"])
    assert created and runner.submit(song["id"], src["id"])[0]["id"] == job["id"]
    assert runner.cancel(job["id"])["status"] == "cancelled"
    retry = runner.retry(job["id"])
    assert retry["id"] != job["id"] and retry["status"] == "queued"
    failed = runner.run(retry["id"])  # the prepared audio is missing
    assert failed["status"] == "failed" and failed["error_code"] == "source_missing"
    assert failed["stages"][-1]["status"] == "failed"
    # A job left running by a crash is queued again on start-up.
    again = runner.retry(failed["id"])
    st.update_job(again["id"], status="running", attempts=1)
    JobRunner(st, start=False).recover()
    assert st.get_job(again["id"])["status"] == "queued"


# ---- studio: original beats, previews, drafts, versions, library ------------------------

@needs_lilypond
def test_studio_beat_lifecycle(client):
    r = client.post("/api/beats", json={"prompt": "A pop-punk beat at 165 BPM, 8 bars, with a tom fill at the end",
                                        "request_id": "req-1"}).json()
    assert r["created"] and r["project"]["kind"] == "beat"
    again = client.post("/api/beats", json={"prompt": "x", "request_id": "req-1"}).json()
    assert again["job"]["id"] == r["job"]["id"] and not again["created"]  # a double click is one beat
    job = client.app_state.runner.wait(r["job"]["id"], timeout=180)
    assert job["status"] == "succeeded", job
    assert [s["name"] for s in job["stages"]] == ["interpret", "arrange", "validate", "render", "view", "save"]
    pid = r["project"]["id"]
    project = client.get(f"/api/projects/{pid}").json()
    assert (project["title"], project["status"], project["versions"]) == ("Pop-Punk Beat", "COMPLETE", 1)
    chart = client.get(f"/api/charts/{job['chart_id']}").json()
    assert chart["validation"]["ok"] and chart["summary"]["generator"]["spec"]["bpm"] == 165
    score = client.get(f"/api/charts/{job['chart_id']}/files/chart.json").json()
    assert len(score["measures"]) == 8 and score["chart_type"] == "original_beat"

    # A working copy: preview, transform, command.
    pv = client.post("/api/preview", json={"score": score}).json()
    assert pv["view"]["pages"] and pv["validation"]["ok"]
    page = client.get(f"/api/previews/{pv['key']}/page-1.svg")
    assert page.status_code == 200 and page.headers["content-type"].startswith("image/svg")
    assert client.get(f"/api/previews/{pv['key']}/../../drum_agent.sqlite3").status_code == 404
    busier = client.post("/api/beats/transform", json={"score": score, "action": "more_complex"}).json()
    assert busier["score"]["measures"] != score["measures"]
    cmd = client.post("/api/beats/command", json={"score": score, "command": "replace the final bar with a tom fill"}).json()
    assert cmd["applied"] and cmd["interpreter"]["interpreter"] == "rules"
    bad = client.post("/api/beats/command", json={"score": score, "command": "make it sound expensive"})
    assert bad.status_code == 422 and bad.json()["examples"]

    # Drafts survive a reload; a version clears the draft.
    assert client.put(f"/api/projects/{pid}/draft", json={"score": cmd["score"], "base_chart_id": job["chart_id"]}).status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["draft"]["score"]["measures"] == cmd["score"]["measures"]
    v2 = client.post(f"/api/projects/{pid}/versions", json={"score": cmd["score"], "note": "Tom fill ending",
                                                             "base_chart_id": job["chart_id"]}).json()
    assert (v2["version"], v2["note"], v2["origin"]) == (2, "Tom fill ending", "edit")
    assert client.get(f"/api/projects/{pid}").json()["draft"] is None
    v3 = client.post(f"/api/charts/{job['chart_id']}/restore").json()
    assert v3["version"] == 3

    # Library: rename, duplicate, search, delete.
    assert client.patch(f"/api/projects/{pid}", json={"title": "Skate Park"}).json()["title"] == "Skate Park"
    dup = client.post(f"/api/projects/{pid}/duplicate").json()
    assert dup["title"] == "Skate Park (copy)" and dup["versions"] == 1
    found = client.get("/api/projects", params={"q": "skate"}).json()["projects"]
    assert {p["id"] for p in found} == {pid, dup["id"]}
    assert client.get("/api/projects", params={"kind": "song"}).json()["projects"] == []
    chart_dir = client.app_state.store.chart_dir(dup["chart"]["id"])
    assert chart_dir.is_dir()
    assert client.delete(f"/api/projects/{dup['id']}").json()["deleted"] == dup["id"]
    assert client.get(f"/api/projects/{dup['id']}").status_code == 404 and not chart_dir.exists()


def test_studio_rejects_malformed_scores(client):
    for bad in ({"measures": []}, {"measures": [{"time": "4/4", "hits": [{"pos": "5/4", "inst": "snare"}]}]},
                {"measures": [{"time": "4/4", "hits": [{"pos": "0", "inst": "theremin"}]}]}, {"nope": 1}):
        r = client.post("/api/preview", json={"score": bad})
        assert r.status_code == 422 and "not valid" in r.json()["detail"]
    assert client.post("/api/beats", json={"prompt": "  "}).status_code == 400


def test_kit_endpoint_lists_the_kit_in_staff_order(client):
    kit = client.get("/api/kit").json()
    ids = [i["id"] for i in kit["instruments"]]
    assert ids.index("crash") < ids.index("hihat") < ids.index("snare") < ids.index("kick")
    assert client.get("/api/kit/samples/theremin.wav").status_code == 404
    assert client.get("/api/kit/samples/../../x.wav").status_code == 404


@needs_fluidsynth
def test_kit_samples_are_rendered_from_the_soundfont(client):
    r = client.get("/api/kit/samples/snare.wav")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    info = sf.info(io.BytesIO(r.content))
    assert info.samplerate == 44100 and 0.5 < info.duration < 3


def test_store_migrates_a_v1_database(tmp_path):
    import sqlite3
    db = sqlite3.connect(str(tmp_path / "drum_agent.sqlite3"))
    db.executescript("""
    CREATE TABLE songs (id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL, album TEXT, year INTEGER,
      duration_s REAL, isrc TEXT, version TEXT, provider TEXT, provider_ids TEXT NOT NULL DEFAULT '{}',
      urls TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
    CREATE TABLE sources (id TEXT PRIMARY KEY, song_id TEXT NOT NULL, kind TEXT NOT NULL, rights TEXT NOT NULL,
      sha256 TEXT NOT NULL, original_name TEXT, path TEXT NOT NULL, info TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
    CREATE TABLE jobs (id TEXT PRIMARY KEY, song_id TEXT NOT NULL, source_id TEXT NOT NULL, engine TEXT NOT NULL,
      idempotency_key TEXT NOT NULL, status TEXT NOT NULL, stage TEXT, stages TEXT NOT NULL DEFAULT '[]', error TEXT,
      error_code TEXT, attempts INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0, chart_id TEXT,
      created_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE charts (id TEXT PRIMARY KEY, song_id TEXT NOT NULL, version INTEGER NOT NULL, parent_id TEXT,
      job_id TEXT, source_id TEXT, status TEXT NOT NULL, origin TEXT NOT NULL, bars INTEGER NOT NULL,
      validation TEXT NOT NULL DEFAULT '{}', summary TEXT NOT NULL DEFAULT '{}', dir TEXT NOT NULL, created_at REAL NOT NULL,
      UNIQUE(song_id, version));
    INSERT INTO songs VALUES ('s_0000000000000001', 'Old', 'Band', NULL, NULL, NULL, NULL, NULL, NULL, '{}', '{}', 1);
    INSERT INTO jobs VALUES ('job_0000000000000001', 's_0000000000000001', 'src_x', 'e', 'k', 'failed', NULL, '[]',
      NULL, NULL, 1, 0, NULL, 1, 1);
    """)
    db.commit()
    db.close()
    st = Store(tmp_path)
    assert st.get_job("job_0000000000000001")["kind"] == "transcribe"
    assert st.list_projects()[0]["kind"] == "song"
    j = st.create_job(song_id="s_0000000000000001", source_id=None, engine="g", key="k2", kind="generate")
    assert j["source_id"] is None and j["kind"] == "generate"


# ---- a song from its name: the personal app finds the recording ------------------------

from test_song import FAKE_YTDLP, video_infos  # noqa: E402 - the song tests' stand-in for yt-dlp


@pytest.fixture
def personal(monkeypatch):
    monkeypatch.setenv("DRUM_AGENT_MODE", "personal")


@pytest.fixture
def fake_ytdlp(tmp_path, monkeypatch):
    """The song tests' fake yt-dlp first on PATH: it answers searches and "downloads" a synthesized take."""
    import os
    import sys

    from drum_agent.synth import synthesize
    wav = synthesize(song_spec(bars=8, tempo=100), tmp_path / "groove.wav", method="numpy")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "yt-dlp"
    exe.write_text(FAKE_YTDLP.replace("{python}", sys.executable))
    exe.chmod(0o755)
    log = tmp_path / "ytdlp.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    monkeypatch.setenv("FAKE_YTDLP_WAV", str(wav))
    monkeypatch.setenv("FAKE_YTDLP_VIDEOS", json.dumps(video_infos(sf.info(str(wav)).duration)))
    return {"wav": wav, "seconds": sf.info(str(wav)).duration,
            "calls": lambda: [json.loads(line) for line in log.read_text().splitlines()]}


def test_rights_personal_basis_is_accepted_only_where_one_person_uses_it():
    from drum_agent import rights
    rights.require_rights("personal", "song.mp3")  # the command line: the user's own computer
    with pytest.raises(rights.RightsError, match="own computer"):
        rights.require_rights("personal", "song.mp3", personal_ok=False)
    assert not rights.shareable("personal") and rights.shareable("original") and not rights.shareable(None)


@needs_ffmpeg
def test_shared_server_never_fetches_songs_or_accepts_personal_charts(client, tmp_path, fake_ytdlp):
    body = client.get("/api/health").json()
    assert body["mode"] == "shared" and "personal" not in body["rights_options"]
    assert body["online"] == {"available": False, "reason": "shared_server", "detail": body["online"]["detail"]}
    d = _song(client, "Test Groove", "The Placeholders")
    sid = d["song"]["id"]
    assert d["status"] == "NEEDS_SOURCE" and d["resolution"]["case"] == "NEEDS_SOURCE"
    assert client.get(f"/api/songs/{sid}/videos").status_code == 403
    assert client.post(f"/api/songs/{sid}/find", json={"personal": True}).status_code == 403
    wav = tone(tmp_path / "a.wav", 8.0).read_bytes()
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("a.wav", wav, "audio/wav")}, data={"rights": "personal"})
    assert r.status_code == 403 and "own computer" in r.json()["detail"]
    assert fake_ytdlp["calls"]() == []  # yt-dlp was never run


def test_personal_app_without_yt_dlp_says_so(client, personal, monkeypatch):
    monkeypatch.setattr("drum_agent.song.fetch.find_ytdlp", lambda: None)
    body = client.get("/api/health").json()
    assert body["mode"] == "personal" and "personal" in body["rights_options"]
    assert body["online"]["available"] is False and body["online"]["reason"] == "no_ytdlp"
    sid = _song(client)["song"]["id"]
    r = client.post(f"/api/songs/{sid}/find", json={"personal": True})
    assert r.status_code == 503 and "yt-dlp" in r.json()["detail"]


@needs_lilypond
@needs_ffmpeg
def test_personal_app_finds_the_song_downloads_it_and_charts_it(client, personal, fake_ytdlp, tmp_path):
    d = client.post("/api/songs", json={"title": "Test Groove", "artist": "The Placeholders",
                                        "duration_s": fake_ytdlp["seconds"]}).json()
    sid = d["song"]["id"]
    assert d["status"] == "READY" and d["resolution"]["case"] == "FIND_ONLINE"

    found = client.get(f"/api/songs/{sid}/videos").json()
    assert found["query"] == "The Placeholders Test Groove"
    assert [v["id"] for v in found["videos"]][0] == "tg-official" and found["videos"][0]["length_ok"]
    live = next(v for v in found["videos"] if v["id"] == "tg-live")
    assert not live["length_ok"] and live["length_off"] == pytest.approx(0.4, abs=0.01)
    assert not [c for c in fake_ytdlp["calls"]() if "-o" in c]  # a search downloads nothing

    assert client.post(f"/api/songs/{sid}/find", json={}).status_code == 403  # not confirmed: personal practice
    r = client.post(f"/api/songs/{sid}/find", json={"personal": True})
    assert r.status_code == 200 and r.json()["created"] and r.json()["job"]["kind"] == "find"
    plan = [s["name"] for s in r.json()["job"]["plan"]]
    assert plan[:3] == ["search", "download", "prepare"]
    done = client.app_state.runner.wait(r.json()["job"]["id"], timeout=300)
    assert done["status"] == "succeeded", done
    assert [s["name"] for s in done["stages"]][:3] == ["search", "download", "prepare"]
    again = client.post(f"/api/songs/{sid}/find", json={"personal": True}).json()
    assert again["job"]["id"] == done["id"] and again["created"] is False  # asked twice: one job

    downloads = [c for c in fake_ytdlp["calls"]() if "-o" in c]
    assert len(downloads) == 1 and downloads[0][-1] == "https://www.youtube.com/watch?v=tg-official"
    detail = client.get(f"/api/songs/{sid}").json()
    src = detail["sources"][0]
    assert src["kind"] == "video" and src["rights"] == "personal" and src["shareable"] is False
    assert src["video"]["id"] == "tg-official" and src["video"]["title"].endswith("(Official Audio)")
    assert detail["resolution"]["case"] == "EXISTING_CHART" and detail["status"] in ("COMPLETE", "NEEDS_CORRECTION")
    store_root = client.app_state.store.root
    assert not any((store_root / "downloads").glob("*")), "the download is decoded, then removed"

    chart = client.get(f"/api/charts/{done['chart_id']}").json()
    assert chart["shareable"] is False and chart["summary"]["rights"] == "personal"
    score = client.get(chart["files"]["chart.json"]).json()
    assert score["copyright"] == "Transcribed for personal practice. Not for distribution."
    assert score["source"].startswith("YouTube: The Placeholders - Test Groove (Official Audio)")
    assert client.get(chart["files"]["chart.pdf"]).content[:4] == b"%PDF"

    # An edited version stays a personal-practice chart, whatever the page sends.
    edited = {**score, "rights": "original", "copyright": None}
    v2 = client.post(f"/api/projects/{sid}/versions", json={"score": edited, "base_chart_id": chart["id"]})
    assert v2.status_code == 200, v2.text
    assert v2.json()["shareable"] is False and v2.json()["summary"]["rights"] == "personal"
    assert client.get(f"/api/charts/{v2.json()['id']}/files/chart.json").json()["copyright"] == score["copyright"]


def test_a_picked_video_must_be_a_video_page(client, personal, fake_ytdlp):
    sid = _song(client)["song"]["id"]
    for url in ("https://example.com/song.mp3", "https://open.spotify.com/track/abc", "ftp://x.org/v"):
        r = client.post(f"/api/songs/{sid}/find", json={"personal": True, "video": {"url": url}})
        assert r.status_code == 422, url
    assert fake_ytdlp["calls"]() == []


def test_serve_personal_listens_only_on_this_computer(capsys):
    from drum_agent.cli import main
    assert main(["serve", "--personal", "--host", "0.0.0.0"]) == 2
    assert "own computer" in capsys.readouterr().err


def test_band_mix_is_separated_first_when_demucs_is_there(monkeypatch):
    """The separation step and its note, with a stand-in for HTDemucs (the real model is measured on
    MDB Drums: docs/MODELS.md). A drum-only recording is never separated; "on" without demucs fails."""
    from drum_agent.audio import separate
    from drum_agent.audio.transcribe import TranscribeOptions, transcribe_audio, use_separation
    from drum_agent.synth import synthesize

    calls = []
    monkeypatch.setattr(separate, "available", lambda: True)
    monkeypatch.setattr(separate, "separate_drums", lambda y, sr: calls.append(len(y)) or y)
    assert use_separation(TranscribeOptions()) and not use_separation(TranscribeOptions(drums_only=True))
    assert not use_separation(TranscribeOptions(separate="off"))
    import tempfile
    from pathlib import Path

    import soundfile
    with tempfile.TemporaryDirectory() as d:
        wav = synthesize(song_spec(bars=4), Path(d) / "take.wav", method="numpy")
        y, sr = soundfile.read(str(wav), dtype="float32")
    y = y.mean(axis=1) if y.ndim > 1 else y
    import librosa
    y = librosa.resample(y, orig_sr=sr, target_sr=44100) if sr != 44100 else y
    stages = []
    score = transcribe_audio(y, TranscribeOptions(), progress=stages.append)
    assert stages[:2] == ["separate", "detect"] and calls == [len(y)]
    assert score.analysis["separation"] == separate.MODEL
    assert score.analysis["notes"][0].startswith("The drums were separated from the band")
    stages.clear()
    score = transcribe_audio(y, TranscribeOptions(drums_only=True), progress=stages.append)
    assert stages[0] == "detect" and score.analysis["separation"] is None and calls == [len(y)]
    monkeypatch.setattr(separate, "available", lambda: False)
    with pytest.raises(ValueError, match="demucs"):
        use_separation(TranscribeOptions(separate="on"))
