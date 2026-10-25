"""Browser end-to-end tests of the studio (Playwright, through node).

- Create a Beat (tests/e2e/beat.e2e.js): describe a beat, generate it, check the strokes
  and the validation, play it (the scheduled strokes and timing are compared with the
  chart), edit the grid and see the notation re-engraved, change the tempo, undo and redo,
  edit with words, save, reload, restore a draft, reopen from My Charts, download and read
  the PDF, print, keyboard, reduced motion and a phone-sized screen.
- Song to Chart (tests/e2e/song.e2e.js): a stored chart, a failed search, a song with no
  source, refused uploads (no rights basis, a corrupt file, a failed request), then a
  full-song transcription of an authorized recording (the Northbound example song
  synthesized with a band: an original composition, so the rights basis is "original"),
  its review, playback and PDF.

Metadata providers and Claude are switched off so the runs don't depend on the network;
their failure states are unit-tested in test_web.py.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from conftest import ROOT, needs_fluidsynth, needs_lilypond

pytestmark = [pytest.mark.slow, needs_lilypond, needs_fluidsynth]


def _node_playwright() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, check=False).returncode == 0


needs_browser = pytest.mark.skipif(not _node_playwright() or not shutil.which("ffmpeg") or not shutil.which("pdftotext"),
                                   reason="needs node with playwright, ffmpeg and poppler (pdftotext)")


@pytest.fixture
def server(tmp_path):
    from drum_agent.web.catalog import seed_examples
    from drum_agent.web.jobs import JobRunner
    from drum_agent.web.store import Store

    data = tmp_path / "data"
    store = Store(data)
    seed_examples(store, JobRunner(store, start=False))
    store.close()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DRUM_AGENT_PUBLIC_METADATA": "0"}
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "YOUTUBE_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "-m", "drum_agent", "serve", "--port", str(port), "--data", str(data)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=2)
            break
        except OSError:
            time.sleep(0.25)
    try:
        yield base
    finally:
        proc.terminate()
        proc.wait(10)


def _run(script: str, base: str, out, **env) -> None:
    out.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(["node", str(ROOT / "tests" / "e2e" / script)], capture_output=True, text=True, timeout=1200,
                         check=False, env={**os.environ, "E2E_BASE": base, "E2E_OUT": str(out), **env})
    print(run.stdout)
    assert run.returncode == 0, run.stdout + run.stderr


@needs_browser
def test_create_a_beat_end_to_end(server, artifacts):
    _run("beat.e2e.js", server, artifacts / "web_e2e")


@needs_browser
def test_song_to_chart_end_to_end(server, tmp_path, artifacts):
    from drum_agent.charts import load_any
    from drum_agent.synth import synthesize
    wav = synthesize(load_any(ROOT / "examples/specs/03_full_song_northbound.yaml"), tmp_path / "northbound.wav",
                     accompaniment=True)
    mix = tmp_path / "Northbound band mix.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "192k", str(mix)], check=True)
    corrupt = tmp_path / "corrupt.mp3"
    corrupt.write_bytes(b"not audio " * 500)
    _run("song.e2e.js", server, artifacts / "web_e2e", E2E_MIX=str(mix), E2E_CORRUPT=str(corrupt))
