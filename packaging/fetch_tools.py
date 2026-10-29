"""Download the tools the Drum Agent app ships with, into DEST (run on the build machine).

  LilyPond 2.26.0   engraving                                  GPL-3.0+   https://lilypond.org
  FFmpeg            decoding the downloaded audio              LGPL-2.1+  https://ffmpeg.org
                    (Windows build: https://github.com/BtbN/FFmpeg-Builds)
  yt-dlp            finding and downloading songs on YouTube   Unlicense  https://github.com/yt-dlp/yt-dlp
  Deno              the JavaScript runtime yt-dlp needs        MIT        https://deno.com

    python packaging/fetch_tools.py --platform windows --dest dist/DrumAgent/tools

DEST gets lilypond/, ffmpeg/bin/, yt-dlp/, deno/ and NOTICES.txt (what each tool is, its
licence and where its source is). Downloads are cached in build/downloads.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "downloads"
LILYPOND = "2.26.0"

TOOLS = {
    "windows": {
        "lilypond": [f"https://gitlab.com/lilypond/lilypond/-/releases/v{LILYPOND}/downloads/"
                     f"lilypond-{LILYPOND}-mingw-x86_64.zip"],
        "ffmpeg": ["https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                   "ffmpeg-master-latest-win64-lgpl-shared.zip"],
        "yt-dlp": ["https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"],
        "deno": ["https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"],
    },
    "mac": {
        "lilypond": [f"https://gitlab.com/lilypond/lilypond/-/releases/v{LILYPOND}/downloads/"
                     f"lilypond-{LILYPOND}-darwin-x86_64.tar.gz"],
        "ffmpeg": [],  # filled in by the Mac build (static builds are per architecture)
        "yt-dlp": ["https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"],
        "deno": ["https://github.com/denoland/deno/releases/latest/download/deno-aarch64-apple-darwin.zip"],
    },
}

NOTICES = f"""Tools shipped with Drum Agent
=============================

Drum Agent runs these programs, unmodified, as separate programs.

LilyPond {LILYPOND} (lilypond/): music engraving. GNU GPL v3 or later.
  Source: https://lilypond.org/source.html  https://gitlab.com/lilypond/lilypond
FFmpeg (ffmpeg/): decoding audio. GNU LGPL v2.1 or later (this build has no GPL parts).
  Source: https://ffmpeg.org/download.html  Build: https://github.com/BtbN/FFmpeg-Builds
yt-dlp (yt-dlp/): finding and downloading songs on YouTube. The Unlicense (public domain).
  Source: https://github.com/yt-dlp/yt-dlp  (it updates itself; see Settings in the app)
Deno (deno/): the JavaScript runtime yt-dlp needs for YouTube. MIT licence.
  Source: https://github.com/denoland/deno

The licence texts are in each tool's folder where its download includes them.
"""


def download(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / url.rsplit("/", 1)[-1]
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(out.suffix + ".part")
    for attempt in range(4):
        try:
            print(f"downloading {url}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "drum-agent-build"})
            with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            tmp.replace(out)
            return out
        except OSError as exc:
            print(f"  failed ({exc}); retrying", flush=True)
            time.sleep(2 ** attempt * 2)
    raise SystemExit(f"could not download {url}")


def unpack(archive: Path, into: Path) -> Path:
    """Extract an archive into a fresh folder; returns its single top folder if it has one."""
    shutil.rmtree(into, ignore_errors=True)
    into.mkdir(parents=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")
    kids = [p for p in into.iterdir()]
    return kids[0] if len(kids) == 1 and kids[0].is_dir() else into


def fetch(platform: str, dest: Path) -> None:
    urls = TOOLS[platform]
    exe = ".exe" if platform == "windows" else ""
    work = ROOT / "build" / "unpacked"
    dest.mkdir(parents=True, exist_ok=True)

    top = unpack(download(urls["lilypond"][0]), work / "lilypond")
    shutil.rmtree(dest / "lilypond", ignore_errors=True)
    shutil.copytree(top, dest / "lilypond")
    assert (dest / "lilypond" / "bin" / f"lilypond{exe}").is_file(), "no lilypond in the LilyPond download"

    if urls["ffmpeg"]:
        top = unpack(download(urls["ffmpeg"][0]), work / "ffmpeg")
        shutil.rmtree(dest / "ffmpeg", ignore_errors=True)
        shutil.copytree(top / "bin", dest / "ffmpeg" / "bin")
        for name in ("LICENSE.txt", "LICENSE"):
            if (top / name).is_file():
                shutil.copy2(top / name, dest / "ffmpeg" / name)
        assert (dest / "ffmpeg" / "bin" / f"ffmpeg{exe}").is_file(), "no ffmpeg in the FFmpeg download"

    (dest / "yt-dlp").mkdir(exist_ok=True)
    shutil.copy2(download(urls["yt-dlp"][0]), dest / "yt-dlp" / f"yt-dlp{exe}")
    (dest / "yt-dlp" / f"yt-dlp{exe}").chmod(0o755)

    top = unpack(download(urls["deno"][0]), work / "deno")
    (dest / "deno").mkdir(exist_ok=True)
    shutil.copy2(top / f"deno{exe}", dest / "deno" / f"deno{exe}")
    (dest / "deno" / f"deno{exe}").chmod(0o755)

    (dest / "NOTICES.txt").write_text(NOTICES, encoding="utf-8")
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"tools in {dest}: {size / 2**20:.0f} MB", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--platform", choices=sorted(TOOLS), required=True)
    p.add_argument("--dest", type=Path, required=True)
    args = p.parse_args()
    fetch(args.platform, args.dest.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
