"""Settings from a `.env` file (KEY=VALUE lines) for the studio and the desktop app.

The web app reads its settings (API keys, limits, folders) from the environment. On
Windows setting environment variables by hand is awkward, and the installed app has no
shell at all, so `serve` and `app` also read a settings file:

- `serve`: `.env` in the current folder (the repository, while developing), or the file
  named by `DRUM_AGENT_ENV_FILE`;
- `app` (the desktop app): `settings.env` in its data folder (`%LOCALAPPDATA%\\Drum Agent`
  on Windows), or the file named by `DRUM_AGENT_ENV_FILE`.

Rules:
- a variable already set in the environment wins over the file;
- an empty value is skipped, so `YOUTUBE_API_KEY=` (as in `.env.example`) means
  "not configured";
- only the app's own settings are read: names starting with `DRUM_AGENT_`, `ANTHROPIC_`,
  `YOUTUBE_`, `SPOTIFY_`, `TORCH_` or `NUMBA_` (a settings file never changes `PATH` and
  the like);
- values are never printed or logged; callers get the loaded names only.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PREFIXES = ("DRUM_AGENT_", "ANTHROPIC_", "YOUTUBE_", "SPOTIFY_", "TORCH_", "NUMBA_")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class EnvLoad:
    """What `load_env_file` did, by name only (never values)."""
    path: Path | None = None
    loaded: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)       # already set in the environment
    ignored: list[str] = field(default_factory=list)    # not an app setting

    def summary(self) -> str:
        if self.path is None:
            return "no settings file"
        parts = [f"{len(self.loaded)} setting(s) from {self.path}"]
        if self.kept:
            parts.append(f"{len(self.kept)} already set in the environment")
        if self.ignored:
            parts.append("ignored (not a Drum Agent setting): " + ", ".join(self.ignored))
        return "; ".join(parts)


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE pairs from the text of a .env file: comments, blank lines, `export KEY=...`,
    single or double quotes around the value. Lines that aren't assignments are skipped."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not _NAME.fullmatch(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:  # an unquoted value may end in a comment
            value = value.split(" #", 1)[0].rstrip()
        out[name] = value
    return out


def load_env_file(path: str | Path | None, environ: dict | None = None) -> EnvLoad:
    """Set the app's settings from `path` into `environ` (default: os.environ) where they
    aren't set yet. A missing or unreadable file loads nothing."""
    env = os.environ if environ is None else environ
    if path is None:
        return EnvLoad()
    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return EnvLoad()
    result = EnvLoad(path=p)
    for name, value in parse(text).items():
        if not name.upper().startswith(PREFIXES):
            result.ignored.append(name)
        elif value == "":
            continue
        elif env.get(name):
            result.kept.append(name)
        else:
            env[name] = _expand_home(value)
            result.loaded.append(name)
    return result


def _expand_home(value: str) -> str:
    """A leading "~" is the home folder, as a shell expands it in an assignment
    (`DRUM_AGENT_DATA_DIR=~/.drum_agent/web` in .env.example)."""
    if value == "~" or value.startswith(("~/", "~\\")):
        return os.path.expanduser(value)
    return value


def default_env_file(fallback: str | Path) -> Path:
    """`DRUM_AGENT_ENV_FILE` when set, otherwise `fallback`."""
    named = os.environ.get("DRUM_AGENT_ENV_FILE")
    return Path(named).expanduser() if named else Path(fallback)
