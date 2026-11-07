"""Set up Drum Agent for development on this computer (Windows, macOS or Linux).

    py -3.12 scripts/dev_setup.py              # Windows
    python3.12 scripts/dev_setup.py            # elsewhere
    ... --shortcut                             # Windows: a "Drum Agent (dev)" desktop shortcut too

Idempotent; each step checks first. It:
1. creates `.venv` with the Python running this script (3.12 recommended: PyTorch, demucs
   and numba publish wheels for it; CI and the Windows app use it);
2. installs numpy, CPU PyTorch + torchaudio, demucs (`--no-separation` skips these three:
   band mixes are then transcribed without drum separation), then the package with its
   test, web and desktop extras;
3. downloads LilyPond 2.26, FFmpeg and the HTDemucs weights into `tools/`
   (packaging/fetch_tools.py: the same files the Windows app ships; Windows and macOS);
4. copies `.env.example` to `.env` when there is none (fill in your keys there; never
   committed);
5. runs `python -m drum_agent doctor` with the tools on PATH.

Then: `scripts\\windows\\drum_agent.cmd` (the app in its own window) or
`scripts\\windows\\studio.cmd` (the studio at http://127.0.0.1:8000).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
TOOLS = ROOT / "tools"
WIN = os.name == "nt"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WIN else "bin/python")


def run(cmd: list, **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def pip(*args: str) -> None:
    run([venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "-q", *args])


def tool_env() -> dict:
    env = dict(os.environ, PYTHONUTF8="1")
    exe = ".exe" if WIN else ""
    lily = TOOLS / "lilypond" / "bin" / f"lilypond{exe}"
    if lily.is_file():
        env["DRUM_AGENT_LILYPOND"] = str(lily)
    bins = [str(TOOLS / sub / "bin") for sub in ("ffmpeg", "fluidsynth") if (TOOLS / sub / "bin").is_dir()]
    env["PATH"] = os.pathsep.join([*bins, env.get("PATH", "")])
    if (TOOLS / "torch").is_dir():
        env["TORCH_HOME"] = str(TOOLS / "torch")
    if (TOOLS / "soundfonts" / "FluidR3_GM.sf2").is_file():
        env["DRUM_AGENT_SOUNDFONT"] = str(TOOLS / "soundfonts" / "FluidR3_GM.sf2")
    return env


def make_shortcut() -> None:
    """A desktop shortcut to scripts/windows/drum_agent.cmd (Windows only)."""
    target = ROOT / "scripts" / "windows" / "drum_agent.cmd"
    icon = ROOT / "build" / "drum-agent.ico"  # packaging/make_icon.py's output
    if not icon.is_file():
        try:
            run([venv_python(), ROOT / "packaging" / "make_icon.py"], cwd=ROOT)
        except subprocess.CalledProcessError:
            pass
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        "[Environment]::GetFolderPath('Desktop') + '\\Drum Agent (dev).lnk');"
        f"$s.TargetPath = '{target}'; $s.WorkingDirectory = '{ROOT}'; $s.WindowStyle = 7;"
        + (f"$s.IconLocation = '{icon}';" if icon.is_file() else "")
        + "$s.Description = 'Drum Agent (from the repository)'; $s.Save()"
    )
    run(["powershell", "-NoProfile", "-Command", ps])
    print("desktop shortcut: Drum Agent (dev)")


def main() -> int:
    p = argparse.ArgumentParser(description="Set up Drum Agent for development on this computer.")
    p.add_argument("--no-separation", action="store_true", help="skip PyTorch/demucs and the HTDemucs weights")
    p.add_argument("--no-tools", action="store_true", help="don't download LilyPond/FFmpeg into tools/")
    p.add_argument("--shortcut", action="store_true", help="Windows: add a 'Drum Agent (dev)' desktop shortcut")
    args = p.parse_args()

    if sys.version_info < (3, 10):
        print("Drum Agent needs Python 3.10 or newer (3.12 recommended).", file=sys.stderr)
        return 1
    if sys.version_info[:2] != (3, 12):
        print(f"note: Python {platform.python_version()}; 3.12 is the tested version", flush=True)

    if not venv_python().is_file():
        run([sys.executable, "-m", "venv", VENV])
    run([venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
    if not args.no_separation:
        pip("numpy")  # demucs imports numpy without declaring it (as in the Dockerfile)
        pip("torch", "torchaudio", "--index-url", TORCH_CPU_INDEX)
        pip("demucs")
    pip("-e", f"{ROOT}[test,web,desktop]")

    exe = ".exe" if WIN else ""
    need_tools = not (TOOLS / "lilypond" / "bin" / f"lilypond{exe}").is_file() or \
        not (TOOLS / "soundfonts" / "FluidR3_GM.sf2").is_file() or \
        (not args.no_separation and not (TOOLS / "torch").is_dir())
    plat = "windows" if WIN else "mac" if sys.platform == "darwin" else None
    if not args.no_tools and need_tools:
        if plat is None:
            print("Linux: install LilyPond with scripts/install_lilypond.sh, and ffmpeg, fluidsynth and "
                  "fluid-soundfont-gm with your package manager")
        else:
            run([sys.executable, ROOT / "packaging" / "fetch_tools.py", "--platform", plat, "--dest", TOOLS,
                 "--sounds", *([] if args.no_separation else ["--separation"])])

    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copyfile(ROOT / ".env.example", env_file)
        print(f"created {env_file} from .env.example: put your API keys there (it is never committed)")

    if args.shortcut and WIN:
        make_shortcut()

    run([venv_python(), "-m", "drum_agent", "doctor"], env=tool_env(), cwd=ROOT)
    print("\nReady. Start the app:", ROOT / "scripts" / "windows" / "drum_agent.cmd" if WIN else
          "python -m drum_agent app", "\nor the studio in a browser:",
          ROOT / "scripts" / "windows" / "studio.cmd" if WIN else "python -m drum_agent serve --personal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
