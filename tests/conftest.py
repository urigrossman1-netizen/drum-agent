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


HAVE_LILYPOND = _have_lilypond()
HAVE_FLUIDSYNTH = shutil.which("fluidsynth") is not None and Path("/usr/share/sounds/sf2/FluidR3_GM.sf2").exists()

needs_lilypond = pytest.mark.skipif(not HAVE_LILYPOND, reason="LilyPond not installed")
needs_fluidsynth = pytest.mark.skipif(not HAVE_FLUIDSYNTH, reason="fluidsynth/FluidR3_GM not installed")


@pytest.fixture(scope="session")
def artifacts() -> Path:
    p = ROOT / "tests" / "_artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p
