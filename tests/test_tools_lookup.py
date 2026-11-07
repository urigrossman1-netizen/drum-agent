"""Finding the shipped tools: the FluidR3_GM soundfont (drum_agent/synth.py) and the
desktop app's tool folder (drum_agent/desktop.py configure)."""

import os

from drum_agent import desktop
from drum_agent.synth import find_soundfont, soundfont_candidates


def test_soundfont_named_by_the_environment_comes_first(tmp_path, monkeypatch):
    sf2 = tmp_path / "Mine.sf2"
    sf2.write_bytes(b"RIFF")
    monkeypatch.setenv("DRUM_AGENT_SOUNDFONT", str(sf2))
    monkeypatch.delenv("DRUM_AGENT_TOOLS", raising=False)
    assert soundfont_candidates()[0] == sf2
    assert find_soundfont() == str(sf2)


def test_soundfont_in_the_shipped_tools_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("DRUM_AGENT_SOUNDFONT", raising=False)
    monkeypatch.setenv("DRUM_AGENT_TOOLS", str(tmp_path))
    sf2 = tmp_path / "soundfonts" / "FluidR3_GM.sf2"
    sf2.parent.mkdir()
    sf2.write_bytes(b"RIFF")
    assert soundfont_candidates()[0] == sf2
    assert find_soundfont() == str(sf2)


def test_desktop_configure_puts_the_shipped_tools_first(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    for sub in ("ffmpeg/bin", "fluidsynth/bin", "lilypond/bin", "soundfonts", "torch"):
        (tools / sub).mkdir(parents=True)
    exe = ".exe" if os.name == "nt" else ""
    (tools / "lilypond" / "bin" / f"lilypond{exe}").write_bytes(b"")
    (tools / "soundfonts" / "FluidR3_GM.sf2").write_bytes(b"RIFF")
    for name in ("DRUM_AGENT_LILYPOND", "TORCH_HOME", "DRUM_AGENT_SOUNDFONT", "DRUM_AGENT_MODE", "DRUM_AGENT_DATA_DIR",
                 "NUMBA_CACHE_DIR", "DRUM_AGENT_AUDIO_CACHE"):
        # configure() writes these straight into os.environ. setenv first so monkeypatch records
        # the original state (delenv of an unset name records nothing, and personal mode would
        # leak into every later test), then delenv for a clean start.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("PATH", "original")
    desktop.configure(tmp_path / "data", tools)
    path = os.environ["PATH"].split(os.pathsep)
    assert path[:2] == [str(tools / "ffmpeg" / "bin"), str(tools / "fluidsynth" / "bin")]
    assert path[-1] == "original"
    assert os.environ["DRUM_AGENT_SOUNDFONT"] == str(tools / "soundfonts" / "FluidR3_GM.sf2")
    assert os.environ["TORCH_HOME"] == str(tools / "torch")
    assert os.environ["DRUM_AGENT_MODE"] == "personal"
