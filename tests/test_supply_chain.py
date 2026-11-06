"""What the builds download and run is pinned: an exact file, checked, never "latest"."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"[0-9a-f]{64}")


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fetch_tools():
    spec = importlib.util.spec_from_file_location("fetch_tools", ROOT / "packaging" / "fetch_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_tools_are_pinned_files():
    tools = fetch_tools()
    pins = [p for plat in tools.TOOLS.values() for p in plat.values() if p]
    pins += [*tools.FLUIDSYNTH.values(), tools.SOUNDFONT_DEB]
    assert len(pins) == 5
    for url, sha256 in pins:
        assert url.startswith("https://") and "latest" not in url and SHA256.fullmatch(sha256), url


def test_a_download_that_isnt_the_pinned_file_is_refused(tmp_path, monkeypatch):
    tools = fetch_tools()
    bad = tmp_path / "tool.zip"
    bad.write_bytes(b"not it")
    monkeypatch.setattr(tools, "download", lambda url: bad)
    try:
        tools.verified("https://example.org/tool.zip", "0" * 64)
    except SystemExit as exc:
        assert "not the pinned" in str(exc)
    else:
        raise AssertionError("accepted")
    assert not bad.exists()


def test_the_lilypond_installer_checks_what_it_downloads():
    script = text("scripts/install_lilypond.sh")
    assert len(SHA256.findall(script)) == 2 and "-c -" in script


def test_the_tests_run_on_linux_and_windows_and_in_a_browser():
    flow = text(".github/workflows/tests.yml")
    assert "os: [ubuntu-latest, windows-latest]" in flow and 'pytest -q -m "not slow"' in flow
    assert "tests/test_web_e2e.py" in flow and re.search(r"playwright@\d+\.\d+\.\d+", flow)


def test_the_live_studio_pins_its_tunnel_and_keeps_nothing_from_visitors():
    flow = text(".github/workflows/live-studio.yml")
    assert "releases/latest" not in flow and "sha256sum -c" in flow and SHA256.search(flow)
    assert "actions/cache" not in flow  # visitors' uploads never go into a cache


def test_the_separation_pins_are_the_same_everywhere():
    extra = re.search(r"^separation = \[(.*)\]$", text("pyproject.toml"), re.MULTILINE).group(1)
    pins = dict(p.strip(' "').split("==") for p in extra.split(","))
    assert set(pins) == {"torch", "torchaudio", "demucs"}
    docker = text("Dockerfile")
    assert f"ARG TORCH_VERSION={pins['torch']}" in docker and f"ARG TORCHAUDIO_VERSION={pins['torchaudio']}" in docker
    assert f"ARG DEMUCS_VERSION={pins['demucs']}" in docker
    flow = text(".github/workflows/windows-app.yml")
    assert f"torch=={pins['torch']} torchaudio=={pins['torchaudio']}" in flow and "desktop,separation" in flow
