import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = sorted((ROOT / "tests" / "cases").glob("*.yaml"))


def _have_lilypond() -> bool:
    try:
        from drum_agent.export.render import find_lilypond
        find_lilypond()
        return True
    except Exception:
        return False


def _have_soundfont() -> bool:
    try:
        from drum_agent.synth import find_soundfont  # the Linux package path, or tools/ on Windows
        find_soundfont()
        return True
    except Exception:
        return False


HAVE_LILYPOND = _have_lilypond()
HAVE_FLUIDSYNTH = shutil.which("fluidsynth") is not None and _have_soundfont()

needs_lilypond = pytest.mark.skipif(not HAVE_LILYPOND, reason="LilyPond not installed")
needs_fluidsynth = pytest.mark.skipif(not HAVE_FLUIDSYNTH, reason="fluidsynth/FluidR3_GM not installed")


@pytest.fixture
def fake_home(monkeypatch, tmp_path) -> Path:
    """Point "~" at an empty folder (so the test machine's own ~/Music stays out of it).

    POSIX: HOME. Windows: "~" is USERPROFILE, but subprocesses read that too, and LilyPond's
    fontconfig fails when it points at a stranger folder, so there expanduser itself is
    redirected, inside this process only."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    if os.name == "nt":
        real = os.path.expanduser

        def expanduser(p):
            s = os.fspath(p)
            if s == "~" or s.startswith(("~/", "~\\")):
                return str(home) + s[1:]
            return real(p)
        monkeypatch.setattr(os.path, "expanduser", expanduser)
    return home


@pytest.fixture(scope="session")
def artifacts() -> Path:
    p = ROOT / "tests" / "_artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p
