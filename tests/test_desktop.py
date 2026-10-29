"""The app on a person's own computer (`drum_agent/desktop.py`): where its data and tools
are, yt-dlp kept where it can update itself, and the studio it serves (headless here)."""

import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest
from conftest import ROOT

from drum_agent import desktop

pytest.importorskip("fastapi")


def _tools(tmp_path):
    t = tmp_path / "tools"
    (t / "lilypond" / "bin").mkdir(parents=True)
    (t / "lilypond" / "bin" / f"lilypond{desktop.EXE}").write_text("")
    (t / "ffmpeg" / "bin").mkdir(parents=True)
    (t / "deno").mkdir()
    (t / "yt-dlp").mkdir()
    (t / "yt-dlp" / f"yt-dlp{desktop.EXE}").write_text("shipped v1")
    return t


def test_configure_puts_the_shipped_tools_first_and_turns_on_personal_mode(tmp_path, monkeypatch):
    for k in ("DRUM_AGENT_MODE", "DRUM_AGENT_DATA_DIR", "DRUM_AGENT_LILYPOND", "NUMBA_CACHE_DIR",
              "DRUM_AGENT_AUDIO_CACHE"):
        monkeypatch.setenv(k, "")  # registered, so whatever configure() sets is undone after the test
        monkeypatch.delenv(k)
    monkeypatch.setenv("PATH", "/usr/bin")
    tools = _tools(tmp_path)
    desktop.configure(tmp_path / "data", tools)
    assert os.environ["DRUM_AGENT_MODE"] == "personal"
    assert os.environ["DRUM_AGENT_DATA_DIR"] == str(tmp_path / "data" / "studio")
    assert os.environ["DRUM_AGENT_LILYPOND"] == str(tools / "lilypond" / "bin" / f"lilypond{desktop.EXE}")
    path = os.environ["PATH"].split(os.pathsep)
    assert path[:3] == [str(tmp_path / "data" / "bin"), str(tools / "ffmpeg" / "bin"), str(tools / "deno")]
    assert path[-1] == "/usr/bin"


def test_yt_dlp_is_copied_once_and_an_updated_copy_is_kept(tmp_path):
    tools, data = _tools(tmp_path), tmp_path / "data"
    exe = desktop.install_ytdlp(data, tools)
    assert exe == data / "bin" / f"yt-dlp{desktop.EXE}" and exe.read_text() == "shipped v1"
    exe.write_text("self-updated v2")  # `yt-dlp -U` replaced it: newer than the shipped one
    os.utime(exe, (time.time() + 60, time.time() + 60))
    assert desktop.install_ytdlp(data, tools).read_text() == "self-updated v2"
    shipped = tools / "yt-dlp" / f"yt-dlp{desktop.EXE}"
    shipped.write_text("shipped v3, a newer installer")  # an app update ships a newer one
    os.utime(shipped, (time.time() + 120, time.time() + 120))
    assert desktop.install_ytdlp(data, tools).read_text() == "shipped v3, a newer installer"
    assert desktop.install_ytdlp(tmp_path / "other", None) is None  # nothing shipped, nothing copied


def test_the_window_is_maximized_on_a_small_screen():
    class Screen:
        def __init__(self, width, height):
            self.width, self.height = width, height

    assert desktop.window_size([Screen(1920, 1080)]) == {"width": 1360, "height": 900, "maximized": False}
    for small in (Screen(1366, 768), Screen(1536, 864), Screen(1024, 768)):
        assert desktop.window_size([small])["maximized"]
    assert desktop.window_size([])["maximized"]  # no screen information


def test_an_example_that_fails_to_engrave_leaves_no_song_behind(tmp_path, monkeypatch):
    from drum_agent.web.catalog import seed_examples
    from drum_agent.web.jobs import JobRunner
    from drum_agent.web.store import Store

    store = Store(tmp_path)
    runner = JobRunner(store, start=False)

    def broken(*args, **kwargs):
        raise RuntimeError("LilyPond failed")

    monkeypatch.setattr(runner, "_save_chart", broken)
    with pytest.raises(RuntimeError):
        seed_examples(store, runner)
    assert store.list_songs() == []  # not a song "ready to chart" from YouTube
    store.close()


def test_headless_app_serves_the_personal_studio_once(tmp_path):
    data = tmp_path / "data"
    port = desktop.free_port()
    env = {**os.environ, "DRUM_AGENT_DATA_DIR": str(data), "DRUM_AGENT_PUBLIC_METADATA": "0"}
    env.pop("DRUM_AGENT_MODE", None)
    proc = subprocess.Popen([sys.executable, "-m", "drum_agent", "app", "--headless", "--no-update", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        assert desktop.wait_ready(url, 60), "the app did not start"
        with urllib.request.urlopen(url + "/api/health") as r:
            health = json.loads(r.read())
        assert health["mode"] == "personal" and "personal" in health["rights_options"]
        assert json.loads((data / "app.json").read_text())["port"] == port
        assert desktop.running_instance(data) == url  # a second launch opens this one instead
        assert (data / "studio").is_dir() and (data / "logs" / "drum-agent.log").is_file()
    finally:
        proc.terminate()
        proc.wait(15)
    assert desktop.running_instance(data) is None
