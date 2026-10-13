"""Run LilyPond to produce PDF, PNG and MIDI. Failures are hard errors.

There is deliberately no fallback renderer: if LilyPond is missing or the
source doesn't compile cleanly, the caller gets a RenderError with the
LilyPond log instead of a fake chart.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MIN_VERSION = (2, 24, 0)
_CANDIDATES = (
    "/opt/lilypond-2.26.0/bin/lilypond",
    "/opt/lilypond/bin/lilypond",
    "/usr/local/bin/lilypond",
    "/usr/bin/lilypond",
)

# Warnings that mean the engraving is wrong, not merely cosmetic.
_FATAL_WARNINGS = (
    "bar check failed",  # LilyPond >= 2.20 spelling
    "barcheck failed",  # older spelling
    "programming error",
    "unterminated",
    "beam was started but never ended",
    "unexpected",
    "syntax error",
    "unknown escaped string",
    "not a note name",
    "cannot find",
    "skipping zero-duration",
    "music for the martians",
)


class RenderError(RuntimeError):
    def __init__(self, message: str, log: str = ""):
        super().__init__(message + (f"\n--- LilyPond log ---\n{log}" if log else ""))
        self.log = log


@dataclass
class RenderResult:
    ly: Path
    pdf: Path
    pngs: list[Path]
    midi: Path | None
    warnings: list[str] = field(default_factory=list)
    log: str = ""
    version: str = ""


def find_lilypond() -> str:
    env = os.environ.get("DRUM_AGENT_LILYPOND")
    if env:
        if not Path(env).exists():
            raise RenderError(f"DRUM_AGENT_LILYPOND points to {env}, which does not exist")
        return env
    for c in _CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("lilypond")
    if found:
        return found
    raise RenderError(
        "LilyPond was not found. Install LilyPond 2.24 or newer (2.26 recommended): "
        "`scripts/install_lilypond.sh`, `apt-get install lilypond`, or set DRUM_AGENT_LILYPOND."
    )


def lilypond_version(exe: str) -> tuple[tuple[int, int, int], str]:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"could not run {exe}: {exc}") from exc
    m = re.search(r"GNU LilyPond (\d+)\.(\d+)\.(\d+)", out)
    if not m:
        raise RenderError(f"could not determine the LilyPond version from: {out[:200]}")
    ver = tuple(int(x) for x in m.groups())
    return ver, ".".join(m.groups())  # type: ignore[return-value]


def render(ly_source: str, out_dir: str | Path, stem: str, png: bool = True,
           resolution: int = 150, timeout: int = 600) -> RenderResult:
    exe = find_lilypond()
    ver, ver_str = lilypond_version(exe)
    if ver < MIN_VERSION:
        raise RenderError(f"LilyPond {ver_str} is too old; 2.24 or newer is required")
    # Absolute: LilyPond runs with cwd=out_dir, so a relative -o path would be doubled.
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ly_path = out_dir / f"{stem}.ly"
    ly_path.write_text(ly_source)
    for old in _pages(out_dir, stem) + [out_dir / f"{stem}.pdf", out_dir / f"{stem}.midi"]:
        if old.exists():
            old.unlink()
    cmd = [exe, "-dno-point-and-click", "--pdf", "-o", str(out_dir / stem)]
    if png:
        cmd[2:2] = ["--png", f"-dresolution={resolution}"]
    cmd.append(str(ly_path))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=out_dir)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"LilyPond timed out after {timeout}s") from exc
    log = proc.stderr + proc.stdout
    warnings = [line.strip() for line in log.splitlines() if "warning:" in line or "error:" in line]
    fatal = [w for w in warnings if "error:" in w or any(f in w.lower() for f in _FATAL_WARNINGS)]
    if proc.returncode != 0 or fatal:
        (out_dir / f"{stem}.log").write_text(log)
        raise RenderError(f"LilyPond failed (exit {proc.returncode}): {fatal[:5] or 'see log'} "
                          f"(full log: {out_dir / (stem + '.log')})", log)
    pdf = out_dir / f"{stem}.pdf"
    if not pdf.exists() or pdf.stat().st_size < 1000:
        raise RenderError("LilyPond reported success but produced no usable PDF", log)
    pngs = _pages(out_dir, stem) if png else []
    if png and not pngs:
        raise RenderError("LilyPond produced no PNG pages", log)
    # LilyPond writes "<stem>.midi". Never fall back to "<stem>.mid": that is the
    # MIDI file our own exporter writes, and confusing the two would make the
    # engraving check compare our MIDI with itself.
    midi = out_dir / f"{stem}.midi"
    if not midi.exists():
        raise RenderError("LilyPond produced no MIDI file for the engraving check", log)
    return RenderResult(ly_path, pdf, pngs, midi, warnings, log, ver_str)


def _pages(out_dir: Path, stem: str) -> list[Path]:
    """This chart's PNG pages only: "<stem>.png" or "<stem>-page<N>.png". (A glob on
    "<stem>*" would also take another chart's "<stem>_fill.png", and treats [ ] in a
    stem as a pattern.)"""
    page = re.compile(re.escape(stem) + r"(-page\d+)?\.png")
    return sorted((p for p in out_dir.iterdir() if page.fullmatch(p.name)), key=_page_key)


def _page_key(p: Path) -> int:
    m = re.search(r"-page(\d+)\.png$", p.name)
    return int(m.group(1)) if m else 0
