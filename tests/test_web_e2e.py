"""Browser end-to-end test: search, a missing source, a corrupt file, failing requests,
and a full-song transcription from upload to print and PDF download (Playwright).

The audio is the Northbound example song synthesized with a band (an original
composition, so the rights basis is "original"). Metadata providers are switched off
so the run doesn't depend on the network; their failure states are unit-tested.
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


@pytest.mark.skipif(not _node_playwright() or not shutil.which("ffmpeg"), reason="needs node with playwright and ffmpeg")
def test_web_app_end_to_end(tmp_path, artifacts):
    from drum_agent.charts import load_any
    from drum_agent.synth import synthesize
    from drum_agent.web.catalog import seed_examples
    from drum_agent.web.jobs import JobRunner
    from drum_agent.web.store import Store

    data = tmp_path / "data"
    store = Store(data)
    seed_examples(store, JobRunner(store, start=False))
    store.close()
    wav = synthesize(load_any(ROOT / "examples/specs/03_full_song_northbound.yaml"), tmp_path / "northbound.wav",
                     accompaniment=True)
    mix = tmp_path / "Northbound band mix.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "192k", str(mix)], check=True)
    corrupt = tmp_path / "corrupt.mp3"
    corrupt.write_bytes(b"not audio " * 500)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DRUM_AGENT_PUBLIC_METADATA": "0"}
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "YOUTUBE_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    server = subprocess.Popen([sys.executable, "-m", "drum_agent", "serve", "--port", str(port), "--data", str(data)],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=2)
                break
            except OSError:
                time.sleep(0.2)
        out = artifacts / "web_e2e"
        out.mkdir(exist_ok=True)
        run = subprocess.run(["node", str(ROOT / "tests/e2e/web.e2e.js")], capture_output=True, text=True, timeout=900, check=False,
                             env={**os.environ, "E2E_BASE": base, "E2E_MIX": str(mix), "E2E_CORRUPT": str(corrupt),
                                  "E2E_OUT": str(out)})
        print(run.stdout)
        assert run.returncode == 0, run.stdout + run.stderr
    finally:
        server.terminate()
        server.wait(10)
