"""Dependency check: `drum-agent doctor`."""

from __future__ import annotations

import importlib
import shutil


def run_doctor() -> int:
    ok = True
    print("Drum Agent dependency check")
    try:
        from .export.render import find_lilypond, lilypond_version, MIN_VERSION
        exe = find_lilypond()
        ver, s = lilypond_version(exe)
        good = ver >= MIN_VERSION
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] LilyPond {s} at {exe}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] LilyPond: {exc}")
    for mod, need in (("numpy", True), ("scipy", True), ("librosa", True), ("soundfile", True),
                      ("mido", True), ("yaml", True), ("xmlschema", False), ("verovio", False)):
        try:
            m = importlib.import_module(mod)
            print(f"  [ok] {mod} {getattr(m, '__version__', '')}")
        except ImportError:
            ok &= not need
            print(f"  [{'FAIL' if need else 'optional'}] {mod} not installed")
    from .synth import find_soundfont
    fs = shutil.which("fluidsynth")
    try:
        sf = find_soundfont()
    except FileNotFoundError:
        sf = None
    print(f"  [{'ok' if fs else 'optional'}] fluidsynth {fs or 'not found'} (sampled drums in the player, test fixtures)")
    print(f"  [{'ok' if sf else 'optional'}] GM soundfont {sf or 'not found'}")
    ff = shutil.which("ffmpeg")
    print(f"  [{'ok' if ff else 'optional'}] ffmpeg {ff or 'not found'} (M4A/AAC and other formats libsndfile cannot read)")
    print("All required dependencies present." if ok else "Missing required dependencies.")
    return 0 if ok else 1
