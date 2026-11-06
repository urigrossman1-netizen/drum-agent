"""The recording for listening along (web/listen.py): compressed, and at other speeds with its
pitch kept, with every stroke where the player expects it."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from conftest import needs_lilypond

from drum_agent.web import listen, providers

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
SR = 44100
CLICKS = (1.0, 2.5, 4.0, 5.5, 7.0)


@pytest.fixture
def take(tmp_path):
    """Eight seconds: a steady 440 Hz tone (for the pitch) with loud clicks at known times."""
    t = np.arange(8 * SR) / SR
    y = 0.05 * np.sin(2 * np.pi * 440 * t)
    rng = np.random.default_rng(0)
    for c in CLICKS:
        i = int(c * SR)
        y[i:i + 220] += 0.9 * rng.standard_normal(220) * np.linspace(1, 0, 220)
    path = tmp_path / "take.wav"
    sf.write(path, np.stack([y, y], axis=1).astype(np.float32), SR, subtype="PCM_16")
    return path


def decoded(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def click_times(y: np.ndarray) -> list[float]:
    """The start of each click: where the level first jumps, then a second of silence for it."""
    env = np.abs(y)
    out, i = [], 0
    while i < len(env):
        if env[i] > 0.3:
            out.append(i / SR)
            i += SR
        else:
            i += 1
    return out


def test_at_normal_speed_only_the_size_changes(take, tmp_path):
    out = listen.rendition(tmp_path / "r", take, 1.0)
    assert out.name == "100.ogg" and out.stat().st_size < take.stat().st_size / 4
    y = decoded(out)
    assert abs(len(y) / SR - 8) < 0.05
    assert click_times(y) == pytest.approx(list(CLICKS), abs=0.006)  # nothing shifted: the player relies on it


@pytest.mark.parametrize("speed", [0.5, 0.75, 1.25])
def test_other_speeds_keep_the_pitch_and_scale_the_time(take, tmp_path, speed):
    y = decoded(listen.rendition(tmp_path / "r", take, speed))
    assert abs(len(y) / SR - 8 / speed) < 0.1
    assert click_times(y) == pytest.approx([c / speed for c in CLICKS], abs=0.03)
    quiet = y[int(0.1 * SR / speed):int(0.8 * SR / speed)]  # the tone alone
    spectrum = np.abs(np.fft.rfft(quiet * np.hanning(len(quiet))))
    assert abs(np.argmax(spectrum) * SR / len(quiet) - 440) < 5


def test_a_rendition_is_made_once_and_only_a_few_are_kept(take, tmp_path, monkeypatch):
    first = listen.rendition(tmp_path / "r", take, 0.75)
    stamp = first.read_bytes()

    def nope(*a, **k):
        raise AssertionError("made again")
    monkeypatch.setattr(subprocess, "run", nope)
    assert listen.rendition(tmp_path / "r", take, 0.75).read_bytes() == stamp
    monkeypatch.undo()
    monkeypatch.setattr(listen, "KEEP", 2)
    listen.rendition(tmp_path / "r", take, 0.8)
    listen.rendition(tmp_path / "r", take, 0.85)
    assert sorted(p.name for p in (tmp_path / "r").glob("*.ogg")) == ["080.ogg", "085.ogg"]
    with pytest.raises(ValueError, match="speed must be"):
        listen.rendition(tmp_path / "r", take, 0.33)


def test_a_failure_says_why_and_leaves_nothing_behind(take, tmp_path, monkeypatch):
    with pytest.raises(listen.ListenError, match="could not prepare"):
        listen.rendition(tmp_path / "r", tmp_path / "missing.wav", 1.0)
    assert not list((tmp_path / "r").glob("*"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(listen.ListenError, match="not installed"):
        listen.rendition(tmp_path / "r", take, 1.0)


@needs_lilypond
def test_the_studio_serves_it_to_the_chart_only_and_removes_it_with_the_song(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from drum_agent.audio import separate
    from drum_agent.charts import compile_spec
    from drum_agent.synth import synthesize
    from drum_agent.web.app import create_app
    monkeypatch.setattr(separate, "available", lambda: False)
    groove = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
    spec = compile_spec({"title": "Listen", "tempo": 100, "rights": "original",
                         "sections": [{"label": "A", "bars": [groove] * 4}]})
    wav = synthesize(spec, tmp_path / "take.wav", method="numpy").read_bytes()
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with TestClient(app) as c:
        sid = c.post("/api/songs", json={"title": "Listen", "artist": "Tester"}).json()["song"]["id"]
        r = c.post(f"/api/songs/{sid}/upload", files={"file": ("t.wav", wav, "audio/wav")}, data={"rights": "original"})
        done = app.state.runner.wait(r.json()["job"]["id"], timeout=300)
        assert done["status"] == "succeeded", (done["error_code"], done["error"], done["stage"])
        cid = done["chart_id"]
        r = c.get(f"/api/charts/{cid}/listen", params={"speed": 0.75})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/ogg" and r.content[:4] == b"OggS"
        assert "no-store" in r.headers["cache-control"]
        assert c.get(f"/api/charts/{cid}/listen", params={"speed": 0.7777}).status_code == 422
        assert c.get("/api/charts/ch_0123456789abcdef/listen").status_code == 404
        folder = next((tmp_path / "data" / "listen").iterdir())
        assert list(folder.glob("*.ogg"))
        assert c.delete(f"/api/projects/{sid}").status_code == 200
        assert not folder.exists()
