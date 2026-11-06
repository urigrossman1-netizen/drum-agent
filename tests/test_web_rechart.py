"""The studio: hints given with an upload, and a chart charted again from its detection log."""

import shutil
from pathlib import Path

import pytest
from conftest import needs_lilypond, studio_client

from drum_agent.charts import compile_spec
from drum_agent.web import providers

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}


@pytest.fixture
def client(tmp_path):
    from drum_agent.web.app import create_app
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with studio_client(app) as c:
        c.app_state = app.state
        yield c


@pytest.fixture
def take(tmp_path):
    from drum_agent.synth import synthesize
    spec = compile_spec({"title": "Hints", "tempo": 100, "rights": "original",
                         "sections": [{"label": "A", "bars": [GROOVE] * 6}]})
    return synthesize(spec, tmp_path / "take.wav", method="numpy").read_bytes()


def _song(client):
    return client.post("/api/songs", json={"title": "Hints", "artist": "Tester"}).json()["song"]["id"]


@needs_lilypond
@needs_ffmpeg
def test_upload_hints_and_charting_again(client, take, monkeypatch):
    from drum_agent.audio import separate
    monkeypatch.setattr(separate, "available", lambda: False)  # the numpy take is drums only: no separation
    sid = _song(client)
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("take.wav", take, "audio/wav")},
                    data={"rights": "original", "time_signature": "7/8"})
    assert r.status_code == 422 and "7/8" in r.json()["detail"]  # checked before any work
    r = client.post(f"/api/songs/{sid}/upload", files={"file": ("take.wav", take, "audio/wav")},
                    data={"rights": "original", "bpm": "100", "time_signature": "4/4"})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    done = client.app_state.runner.wait(job["id"], timeout=300)
    assert done["status"] == "succeeded", done
    store = client.app_state.store
    assert store.get_job(job["id"])["params"] == {"hints": {"bpm": 100.0, "time_signature": "4/4"}}
    # The same recording with other hints is another job; with the same hints, the same one.
    again = client.post(f"/api/songs/{sid}/upload", files={"file": ("take.wav", take, "audio/wav")},
                        data={"rights": "original", "bpm": "100", "time_signature": "4/4"}).json()
    assert again["job"]["id"] == job["id"] and again["created"] is False

    chart = client.get(f"/api/charts/{done['chart_id']}").json()
    assert chart["can_rechart"] and chart["summary"]["time_signature"] == "4/4"
    assert client.post(f"/api/charts/{chart['id']}/rechart", json={}).status_code == 422  # nothing given
    assert client.post(f"/api/charts/{chart['id']}/rechart", json={"time_signature": "5/8"}).status_code == 422
    r = client.post(f"/api/charts/{chart['id']}/rechart", json={"time_signature": "3/4"})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["parent_id"] == chart["id"] and new["version"] == chart["version"] + 1
    assert new["origin"] == "rechart" and new["note"] == "Charted again: 3/4"
    redone = client.get(f"/api/charts/{new['id']}").json()
    assert redone["summary"]["time_signature"] == "3/4" and redone["summary"]["rights"] == "original"
    assert "chart.detections.json" in redone["files"]  # its own log: it can be charted again too

    # A log from before version 2 can't be charted again, and the studio says so up front.
    log = Path(store.get_chart(new["id"])["dir"]) / "chart.detections.json"
    log.write_text(log.read_text(encoding="utf-8").replace('"version":2', '"version":1', 1), encoding="utf-8")
    assert client.get(f"/api/charts/{new['id']}").json()["can_rechart"] is False
    r = client.post(f"/api/charts/{new['id']}/rechart", json={"bpm": 120})
    assert r.status_code == 422 and "version 1" in r.json()["detail"]
    # Without a detection log (a generated beat) there is nothing to chart again.
    log.unlink()
    assert client.get(f"/api/charts/{new['id']}").json()["can_rechart"] is False
    assert client.post(f"/api/charts/{new['id']}/rechart", json={"bpm": 120}).status_code == 409
