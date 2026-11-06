"""The server's protections (web/guard.py and the upload's way through a job), tried as an
attacker or a careless client would."""

import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from conftest import studio_client

from drum_agent.web import guard, providers, sources
from drum_agent.web.app import create_app
from drum_agent.web.guard import Buckets, Limit, hostname
from drum_agent.web.store import Store

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
BOUNDARY = "x" * 16


def make_app(tmp_path, **kw):
    return create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False), **kw)


@pytest.fixture
def client(tmp_path):
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        yield c


@pytest.fixture
def personal(monkeypatch):
    monkeypatch.setenv("DRUM_AGENT_MODE", "personal")


def song(c, title="Test Song"):
    return c.post("/api/songs", json={"title": title, "artist": "Tester"}).json()["song"]["id"]


def take(path, seconds=8.0, level=0.3):
    t = np.arange(int(seconds * 22050)) / 22050
    sf.write(str(path), level * np.sin(2 * np.pi * 220 * t), 22050)
    return path


def upload(c, sid, data, name="take.wav", rights="original"):
    return c.post(f"/api/songs/{sid}/upload", files={"file": (name, data, "audio/wav")}, data={"rights": rights})


# ---- who may ask -----------------------------------------------------------------------------

@pytest.mark.parametrize("header, name", [("127.0.0.1:8000", "127.0.0.1"), ("LOCALHOST", "localhost"), ("[::1]:80", "[::1]"),
                                          ("evil.example:8000", "evil.example"), ("", "")])
def test_the_name_in_a_host_header(header, name):
    assert hostname(header.encode()) == name


@pytest.mark.parametrize("host, ok", [("127.0.0.1:8000", True), ("localhost:51234", True), ("[::1]:8000", True), ("127.0.0.1", True),
                                      ("evil.example", False), ("evil.example:8000", False), ("127.0.0.1.evil.example", False),
                                      ("localhost.evil.example:8000", False), ("0.0.0.0:8000", False)])
def test_the_personal_app_answers_only_to_its_own_names(tmp_path, personal, host, ok):
    """A page that points its own domain at 127.0.0.1 (DNS rebinding) gets nothing."""
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        r = c.get("/api/projects", headers={"Host": host})
    assert r.status_code == (200 if ok else 403)
    if not ok:
        assert r.json()["error"] == "bad_host"


def test_a_shared_server_has_a_public_name(client):
    assert client.get("/api/projects", headers={"Host": "studio.example.org"}).status_code == 200


@pytest.mark.parametrize("method, path", [("post", "/api/songs"), ("post", "/api/preview"), ("delete", "/api/projects/s_0123456789abcdef"),
                                          ("put", "/api/projects/s_0123456789abcdef/draft"), ("patch", "/api/projects/s_0123456789abcdef"),
                                          ("post", "/api/charts/ch_0123456789abcdef/explain"), ("post", "/api/songs/s_0123456789abcdef/upload")])
def test_a_write_from_another_site_is_refused(client, method, path):
    """A form or fetch on another site can send a cookie and a body, but not this header."""
    del client.headers["X-Drum-Agent"]
    r = getattr(client, method)(path)
    assert r.status_code == 403 and r.json()["error"] == "cross_site"
    client.headers["X-Drum-Agent"] = "anything"
    assert getattr(client, method)(path).status_code != 403


def test_the_personal_app_guards_writes_too(tmp_path, personal):
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        del c.headers["X-Drum-Agent"]
        assert c.post("/api/songs", json={"title": "x", "artist": "y"}).status_code == 403
        assert c.get("/api/projects").status_code == 200  # reading needs no header


def test_the_page_sends_the_header_on_every_way_it_writes():
    static = Path(guard.__file__).parent / "static" / "js"
    assert '"X-Drum-Agent": "studio"' in (static / "ui.js").read_text(encoding="utf-8")  # api(), all the JSON calls
    assert 'setRequestHeader("X-Drum-Agent", "studio")' in (static / "song.js").read_text(encoding="utf-8")  # the upload


# ---- how much --------------------------------------------------------------------------------

def test_a_declared_size_over_the_limit_is_refused_before_anything_is_read(client, monkeypatch):
    monkeypatch.setattr(guard, "MAX_BODY", 1000)
    r = client.post("/api/songs", content=b"x" * 2000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "too_large"


def test_a_body_without_a_size_is_cut_off_when_it_passes_the_limit(client, monkeypatch):
    monkeypatch.setattr(guard, "MAX_BODY", 1000)
    sent = []

    def endless():
        for k in range(100):
            sent.append(k)
            yield b"x" * 100

    r = client.post("/api/songs", content=endless(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and "limit" in r.json()["detail"]


def test_a_chunked_upload_is_cut_off_too(client, monkeypatch):
    monkeypatch.setattr(guard, "MAX_BYTES", 1000)
    monkeypatch.setattr(guard, "MULTIPART_SLACK", 100)
    sid = song(client)
    head = (f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n").encode()

    def body():
        yield head
        for _ in range(100):
            yield b"x" * 100

    r = client.post(f"/api/songs/{sid}/upload", content=body(),
                    headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
    assert r.status_code == 413
    uploads = Path(client.app.state.store.root) / "uploads"
    assert not list(uploads.iterdir())


def test_an_upload_may_be_far_bigger_than_any_other_request(client, monkeypatch):
    monkeypatch.setattr(guard, "MAX_BODY", 1000)
    sid = song(client)
    r = upload(client, sid, b"garbage" * 1000)  # past MAX_BODY: reaches the route, which judges the file
    assert r.status_code == 422 and r.json()["error"] == "bad_signature"


# ---- how often -------------------------------------------------------------------------------

def test_a_bucket_empties_and_refills():
    now = [0.0]
    b = Buckets(clock=lambda: now[0])
    limit = Limit(burst=2, per_hour=3600)  # one a second
    assert b.take(limit, [("a", 1)]) == 0 and b.take(limit, [("a", 1)]) == 0
    assert b.take(limit, [("a", 1)]) == pytest.approx(1.0)
    assert b.take(limit, [("other", 1)]) == 0
    now[0] = 1.0
    assert b.take(limit, [("a", 1)]) == 0
    now[0] = 1000.0
    assert b.take(limit, [("a", 1)]) == 0 and b.take(limit, [("a", 1)]) == 0  # never more than the burst
    assert b.take(limit, [("a", 1)]) > 0


def test_a_refused_request_takes_nothing_from_the_other_bucket():
    b = Buckets(clock=lambda: 0.0)
    limit = Limit(burst=1, per_hour=1)
    assert b.take(limit, [("visitor", 1), ("address", 2)]) == 0
    assert b.take(limit, [("visitor", 1), ("address", 2)]) > 0
    assert b.take(limit, [("new visitor", 1), ("address", 2)]) == 0  # the address had room for one more


def test_idle_buckets_are_forgotten(monkeypatch):
    monkeypatch.setattr(guard, "MAX_TRACKED", 3)
    now = [0.0]
    b = Buckets(clock=lambda: now[0])
    limit = Limit(burst=1, per_hour=1)
    for k in range(3):
        b.take(limit, [(k, 1)])
    now[0] = guard.IDLE_S + 1
    b.take(limit, [("new", 1)])
    assert list(b.state) == ["new"]


def test_a_crowd_of_new_visitors_doesnt_cost_a_sweep_on_every_request(monkeypatch):
    monkeypatch.setattr(guard, "MAX_TRACKED", 1)
    now = [100.0]
    b = Buckets(clock=lambda: now[0])
    limit = Limit(burst=1, per_hour=1)
    for k in range(3):
        b.take(limit, [(k, 1)])
    assert b.pruned == 100.0  # nothing swept yet: the last sweep was just now
    now[0] += guard.PRUNE_EVERY_S + 1
    b.take(limit, [(9, 1)])
    assert b.pruned == now[0]


def test_every_limit_refills_within_the_idle_time():
    assert all(limit.burst / limit.per_hour * 3600 <= guard.IDLE_S for limit in guard.LIMITS.values())


@pytest.mark.parametrize("method, path, name", [
    ("POST", "/api/charts/ch_1/explain", "claude"), ("POST", "/api/charts/ch_1/suggest-sections", "claude"),
    ("POST", "/api/beats/command", "words"), ("GET", "/api/search", "search"), ("POST", "/api/songs/s_1/upload", "jobs"),
    ("POST", "/api/songs/s_1/jobs", "jobs"), ("POST", "/api/jobs/job_1/retry", "jobs"), ("POST", "/api/beats", "jobs"),
    ("POST", "/api/preview", "preview"), ("POST", "/api/projects/s_1/versions", "save"),
    ("POST", "/api/charts/ch_1/rechart", "save"), ("GET", "/api/charts/ch_1/listen", "listen"),
    ("GET", "/api/charts/ch_1", None), ("GET", "/api/jobs/job_1", None), ("POST", "/api/beats/transform", None)])
def test_which_requests_are_limited(method, path, name):
    assert guard.bucket_for(method, path) == name


def test_a_visitor_is_slowed_down_with_a_time_to_wait(client, monkeypatch):
    monkeypatch.setitem(guard.LIMITS, "search", Limit(2, 3600))
    assert [client.get("/api/search", params={"q": "x"}).status_code for _ in range(2)] == [200, 200]
    r = client.get("/api/search", params={"q": "x"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1 and "Try again" in r.json()["detail"]


def test_dropping_the_cookie_doesnt_escape_the_address_limit(client, monkeypatch):
    monkeypatch.setitem(guard.LIMITS, "search", Limit(2, 1))
    codes = []
    for _ in range(guard.ADDRESS_FACTOR * 2 + 1):
        client.cookies.clear()  # a new visitor every time
        codes.append(client.get("/api/search", params={"q": "x"}).status_code)
    assert codes.count(200) == 2 * guard.ADDRESS_FACTOR and codes[-1] == 429


def test_one_person_on_their_own_computer_is_not_limited(tmp_path, personal, monkeypatch):
    monkeypatch.setitem(guard.LIMITS, "search", Limit(1, 1))
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        assert {c.get("/api/search", params={"q": "x"}).status_code for _ in range(5)} == {200}


# ---- https -----------------------------------------------------------------------------------

def test_https_is_remembered_only_when_it_is_https(client):
    assert "strict-transport-security" not in client.get("/api/songs").headers
    r = client.get("/api/songs", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"] == "max-age=31536000"
    r = client.get("/api/songs", headers={"X-Forwarded-Proto": "https, http"})
    assert "strict-transport-security" in r.headers


def test_a_refusal_gets_the_security_headers_too(client):
    del client.headers["X-Drum-Agent"]
    r = client.post("/api/songs")
    assert r.status_code == 403 and r.headers["x-content-type-options"] == "nosniff"


# ---- an upload waits for its job -------------------------------------------------------------

def store_with_song(tmp_path, title="Test Song"):
    store = Store(tmp_path / "data")
    return store, store.upsert_song(title=title, artist="Tester")


def uploaded(store, song, path, name="take.wav"):
    """As the route does it: a temporary file in uploads/ handed to add_upload."""
    tmp = store.root / "uploads" / "upload-test"
    shutil.copy(path, tmp)
    try:
        return sources.add_upload(store, song, tmp, name, "original")
    finally:
        tmp.unlink(missing_ok=True)


def test_nothing_is_decoded_in_the_request(tmp_path, monkeypatch):
    def nope(*a, **k):
        raise AssertionError("decoded in the request")
    monkeypatch.setattr(sources, "prepare", nope)
    store, s = store_with_song(tmp_path)
    src = uploaded(store, s, take(tmp_path / "a.wav"))
    waiting = store.root / "uploads" / src["info"]["waiting"]
    assert waiting.is_file() and waiting.suffix == ".wav" and not Path(src["path"]).exists()
    again = uploaded(store, s, tmp_path / "a.wav")
    assert again["id"] == src["id"] and len(list((store.root / "uploads").iterdir())) == 1


@pytest.mark.parametrize("data, name, code", [
    (b"", "a.wav", "empty"), (b"not audio at all, no", "a.wav", "bad_signature"), (b"RIFF", "a.txt", "unsupported_type")])
def test_what_needs_no_decoder_is_still_refused_at_once(tmp_path, data, name, code):
    from drum_agent.audio.prepare import AudioError
    store, s = store_with_song(tmp_path)
    (tmp_path / "f").write_bytes(data)
    with pytest.raises(AudioError) as exc:
        uploaded(store, s, tmp_path / "f", name)
    assert exc.value.code == code and not store.sources_for(s["id"])
    assert not list((store.root / "uploads").iterdir())


@needs_ffmpeg
def test_the_job_decodes_it_and_keeps_only_the_audio(tmp_path):
    store, s = store_with_song(tmp_path)
    src = sources.decode_source(store, uploaded(store, s, take(tmp_path / "a.wav")))
    assert Path(src["path"]).is_file() and src["info"]["duration_s"] == pytest.approx(8.0, abs=0.01)
    assert "waiting" not in src["info"] and not list((store.root / "uploads").iterdir())
    assert sources.decode_source(store, src) == src  # nothing left to do


@needs_ffmpeg
def test_the_same_recording_for_another_song_is_decoded_once(tmp_path, monkeypatch):
    store, a = store_with_song(tmp_path)
    b = store.upsert_song(title="Another", artist="Tester")
    first = sources.decode_source(store, uploaded(store, a, take(tmp_path / "a.wav")))
    second = uploaded(store, b, tmp_path / "a.wav")

    def nope(*a, **k):
        raise AssertionError("decoded twice")
    monkeypatch.setattr(sources, "prepare", nope)
    second = sources.decode_source(store, second)
    assert second["path"] == first["path"] and second["info"] == first["info"]
    assert not list((store.root / "uploads").iterdir())


@needs_ffmpeg
@pytest.mark.parametrize("damage, code", [
    (lambda p: p.write_bytes(p.read_bytes()[:len(p.read_bytes()) // 2]), "truncated"),
    (lambda p: take(p, level=0.0), "silent"),
    (lambda p: take(p, seconds=2.0), "too_short")])
def test_a_file_that_only_decoding_can_judge_fails_its_job_and_isnt_kept(tmp_path, damage, code):
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        runner, store = c.app.state.runner, c.app.state.store
        sid = song(c)
        path = take(tmp_path / "a.wav")
        damage(path)
        r = upload(c, sid, path.read_bytes())
        assert r.status_code == 200, r.text  # it looks like audio
        job = r.json()["job"]
        done = runner.run(job["id"])
        assert done["status"] == "failed" and done["error_code"] == code and done["stage"] != "detect"
        assert done["source_id"] is None and not store.sources_for(sid)
        assert not list((store.root / "uploads").iterdir()) and not list((store.root / "sources").iterdir())
        assert c.get(f"/api/songs/{sid}").json()["status"] == "FAILED"
        r = c.post(f"/api/jobs/{job['id']}/retry")
        assert r.status_code == 409 and "upload it again" in r.json()["detail"]
        # A good recording goes through afterwards.
        good = take(tmp_path / "b.wav")
        r = upload(c, sid, good.read_bytes())
        assert r.status_code == 200 and r.json()["created"] is True


@needs_ffmpeg
def test_a_job_queued_on_a_refused_upload_says_so(tmp_path):
    with studio_client(make_app(tmp_path, start_worker=False)) as c:
        runner, sid = c.app.state.runner, song(c)
        silent = take(tmp_path / "a.wav", level=0.0).read_bytes()
        files = {"file": ("take.wav", silent, "audio/wav")}
        first = c.post(f"/api/songs/{sid}/upload", files=files, data={"rights": "original"}).json()["job"]
        second = c.post(f"/api/songs/{sid}/upload", files=files, data={"rights": "original", "bpm": "100"}).json()["job"]
        assert first["id"] != second["id"] and first["source_id"] == second["source_id"]
        assert runner.run(first["id"])["error_code"] == "silent"
        done = runner.run(second["id"])
        assert done["status"] == "failed" and done["error_code"] == "source_missing"


@needs_ffmpeg
def test_uploading_a_recording_whose_audio_has_gone_brings_it_back(tmp_path):
    store, s = store_with_song(tmp_path)
    from drum_agent.web.jobs import JobRunner
    runner = JobRunner(store, start=False)
    src = sources.decode_source(store, uploaded(store, s, take(tmp_path / "a.wav")))
    job, _ = runner.submit(s["id"], src["id"])
    store.update_job(job["id"], status="succeeded")
    assert runner.submit(s["id"], src["id"])[1] is False  # asked again: the same job
    Path(src["path"]).unlink()
    again = uploaded(store, s, tmp_path / "a.wav")
    assert again["id"] == src["id"] and again["info"].get("waiting")
    new, created = runner.submit(s["id"], again["id"])
    assert created and new["id"] != job["id"]
    assert Path(sources.decode_source(store, again)["path"]).is_file()


@needs_ffmpeg
def test_a_crash_after_decoding_cant_lose_the_recording(tmp_path, monkeypatch):
    store, s = store_with_song(tmp_path)
    src = uploaded(store, s, take(tmp_path / "a.wav"))
    real = Path.unlink

    def dies(self, *a, **k):
        if self.parent.name == "uploads":
            raise KeyboardInterrupt
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", dies)
    with pytest.raises(KeyboardInterrupt):
        sources.decode_source(store, src)
    monkeypatch.undo()
    assert "waiting" not in store.get_source(src["id"])["info"] and Path(src["path"]).is_file()


def test_the_song_is_the_transcription_not_its_practice_version(tmp_path):
    store, s = store_with_song(tmp_path)
    for k, origin in enumerate(("transcription", "simplified")):
        store.add_chart(chart_id=f"ch_{k}", song_id=s["id"], status="COMPLETE", origin=origin, bars=1, validation={}, summary={})
    assert sources.resolve(store, s)["chart_id"] == "ch_0"


@needs_ffmpeg
def test_deleting_a_project_takes_what_was_waiting(client, tmp_path):
    sid = song(client)
    assert upload(client, sid, take(tmp_path / "a.wav").read_bytes()).status_code == 200
    store = client.app.state.store
    assert len(list((store.root / "uploads").iterdir())) == 1
    job = store.jobs_for(sid)[0]
    client.post(f"/api/jobs/{job['id']}/cancel")
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    assert not list((store.root / "uploads").iterdir())


# ---- one recording, many songs ---------------------------------------------------------------

def song_with_audio(c):
    """A song with a chart and its recording on disk, as a finished job leaves them."""
    store = c.app.state.store
    sid = song(c)
    wav = store.root / "sources" / ("a" * 64 + ".wav")
    wav.write_bytes(b"RIFF....WAVE")
    src = store.add_source(song_id=sid, kind="upload", rights="own", sha256="a" * 64, path=str(wav), original_name="a", info={})
    cid = "ch_" + "0" * 16
    store.chart_dir(cid).mkdir(parents=True)
    (store.chart_dir(cid) / "view.json").write_text("{}", encoding="utf-8")
    store.add_chart(chart_id=cid, song_id=sid, status="COMPLETE", origin="transcription", bars=4, validation={}, summary={},
                    source_id=src["id"])
    return sid, cid, wav


def test_a_copy_keeps_the_recording_when_the_original_goes(client):
    """It used to answer 404: only the original had a source row, so deleting it took the audio."""
    sid, cid, wav = song_with_audio(client)
    copy = client.post(f"/api/projects/{sid}/duplicate").json()
    copy_chart = copy["chart"]["id"]
    assert client.get(f"/api/charts/{copy_chart}/audio").status_code == 200
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    assert wav.is_file() and client.get(f"/api/charts/{copy_chart}/audio").status_code == 200
    assert client.delete(f"/api/projects/{copy['id']}").status_code == 200
    assert not wav.exists()  # the last one takes it


def test_a_copy_made_before_this_gets_its_source_when_the_server_starts(tmp_path):
    store, a = store_with_song(tmp_path)
    b = store.upsert_song(title="A copy", artist="Tester")
    src = store.add_source(song_id=a["id"], kind="upload", rights="own", sha256="b" * 64, path="/x.wav", original_name="x", info={"duration_s": 9})
    store.add_chart(chart_id="ch_copy", song_id=b["id"], status="COMPLETE", origin="duplicate", bars=1, validation={}, summary={},
                    source_id=src["id"])
    store.close()
    store = Store(tmp_path / "data")
    mine = store.sources_for(b["id"])
    assert len(mine) == 1 and mine[0]["sha256"] == "b" * 64 and mine[0]["id"] != src["id"] and mine[0]["info"] == {"duration_s": 9}
    assert store.get_chart("ch_copy")["source_id"] == mine[0]["id"]
    store.close()
    assert Store(tmp_path / "data").sources_for(b["id"]) == mine  # once


def test_a_chart_whose_recording_is_gone_doesnt_offer_it(client):
    sid, cid, wav = song_with_audio(client)
    assert client.get(f"/api/charts/{cid}").json()["has_audio"] is True
    wav.unlink()
    assert client.get(f"/api/charts/{cid}").json()["has_audio"] is False


# ---- assets ----------------------------------------------------------------------------------

def test_a_shared_server_refuses_a_personal_asset(tmp_path, monkeypatch):
    with wave.open(str(tmp_path / "a.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\0\0" * 8000)
    (tmp_path / "b.wav").write_bytes((tmp_path / "a.wav").read_bytes())
    (tmp_path / "assets.json").write_text(json.dumps([
        {"file": "a.wav", "title": "Mine", "artist": "Me", "rights": "personal"},
        {"file": "b.wav", "title": "Ours", "artist": "Us", "rights": "own"},
        {"file": "b.wav", "title": "Odd", "artist": "Us", "rights": ["own"]}]), encoding="utf-8")
    monkeypatch.setenv("DRUM_AGENT_ASSET_DIR", str(tmp_path))
    monkeypatch.delenv("DRUM_AGENT_MODE", raising=False)
    assert [e["title"] for e in sources.asset_manifest()] == ["Ours"]
    monkeypatch.setenv("DRUM_AGENT_MODE", "personal")
    assert [e["title"] for e in sources.asset_manifest()] == ["Mine", "Ours"]
