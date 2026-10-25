"""The web app: audio preparation, chart validation, providers, Claude, store and API.

Providers and Claude are exercised through their real client code with a mocked HTTP
transport (isolated tests only); nothing here reaches the network.
"""

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
