"""Download the tools the Drum Agent app ships with, into DEST (run on the build machine).

  LilyPond 2.26.0   engraving                                  GPL-3.0+   https://lilypond.org
  FFmpeg            decoding and converting audio files        LGPL-2.1+  https://ffmpeg.org
                    (Windows build: https://github.com/BtbN/FFmpeg-Builds)
  HTDemucs model    separating the drums from the band         MIT        https://github.com/adefossez/demucs
                    (with --separation; its code, PyTorch and demucs, is in the app itself)
  FluidSynth 2.6.2  real sampled drums for playback, `synth`   LGPL-2.1+  https://www.fluidsynth.org
  FluidR3_GM        the General MIDI soundfont it plays        MIT        Debian fluid-soundfont-gm 3.1-5.3
                    (both with --sounds; FluidSynth's build is fetched for Windows only)

    python packaging/fetch_tools.py --platform windows --dest dist/DrumAgent/tools [--separation] [--sounds]

DEST gets lilypond/, ffmpeg/bin/ and NOTICES.txt (what each tool is, its
licence and where its source is); --sounds adds fluidsynth/bin/ and
soundfonts/FluidR3_GM.sf2. Downloads are cached in build/downloads.
"""

from __future__ import annotations

import argparse
import hashlib
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
    },
    "mac": {
        "lilypond": [f"https://gitlab.com/lilypond/lilypond/-/releases/v{LILYPOND}/downloads/"
                     f"lilypond-{LILYPOND}-darwin-x86_64.tar.gz"],
        "ffmpeg": [],  # filled in by the Mac build (static builds are per architecture)
    },
}

# HTDemucs (demucs.pretrained "htdemucs"): torch hub checks that its SHA-256 starts with the name's suffix.
HTDEMUCS = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th"

# The sampled drums (drum_agent/web/samples.py) and `synth` play the FluidR3_GM soundfont
# with FluidSynth. The soundfont is taken from Debian's package, the file the Linux server
# image installs, so audio rendered on Windows matches CI and the evaluation numbers.
# (url, sha256): both pinned.
FLUIDSYNTH = {
    "windows": ("https://github.com/FluidSynth/fluidsynth/releases/download/v2.6.2/"
                "fluidsynth-v2.6.2-win10-x64-cpp11.zip",
                "808295345d43c9c428f3fa87d29fbf97a9926f356df95559ff2689f3bd4072d7"),
}
SOUNDFONT_DEB = ("https://deb.debian.org/debian/pool/main/f/fluid-soundfont/fluid-soundfont-gm_3.1-5.3_all.deb",
                 "6f531493ac4e4d9772fd96b2488ea1790af81c196135fbdd25997da0781fc60e")
SOUNDFONT = "FluidR3_GM.sf2"

SOUND_NOTICES = """
FluidSynth 2.6.2 (fluidsynth/): plays the General MIDI soundfont for the sampled drums and
  `synth`. GNU LGPL v2.1 or later. Source: https://github.com/FluidSynth/fluidsynth
FluidR3_GM.sf2 (soundfonts/): the General MIDI soundfont by Frank Wen. MIT licence.
  From Debian's fluid-soundfont-gm 3.1-5.3: https://packages.debian.org/source/fluid-soundfont
"""

NOTICES = f"""Tools shipped with Drum Agent
=============================

Drum Agent runs these programs, unmodified, as separate programs.

LilyPond {LILYPOND} (lilypond/): music engraving. GNU GPL v3 or later.
  Source: https://lilypond.org/source.html  https://gitlab.com/lilypond/lilypond
FFmpeg (ffmpeg/): decoding and converting audio files. GNU LGPL v2.1 or later (this build has no GPL parts).
  Source: https://ffmpeg.org/download.html  Build: https://github.com/BtbN/FFmpeg-Builds
HTDemucs (torch/, when present): the model that separates the drums from the band before
  transcription, run with PyTorch (BSD) and demucs (MIT). MIT licence.
  Source: https://github.com/adefossez/demucs

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


def fetch_separation(dest: Path) -> None:
    """The HTDemucs weights where torch hub looks for them ($TORCH_HOME/hub/checkpoints)."""
    src = download(HTDEMUCS)
    expect = HTDEMUCS.rsplit("-", 1)[-1].split(".")[0]
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    if not digest.startswith(expect):
        raise SystemExit(f"the HTDemucs download is not the expected file (sha256 {digest[:12]}...)")
    out = dest / "torch" / "hub" / "checkpoints"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out / src.name)
    # demucs loads a model from a folder by its bag file (drum_agent/audio/separate.py, shipped())
    (out / "htdemucs.yaml").write_text(f"models: ['{src.name.split('-')[0]}']\n", encoding="utf-8")


def verified(url: str, sha256: str) -> Path:
    """A cached download whose SHA-256 is the pinned one (a wrong file is deleted, then refused)."""
    path = download(url)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        path.unlink()
        raise SystemExit(f"{path.name}: sha256 {digest[:12]}... is not the pinned {sha256[:12]}...")
    return path


def deb_file(deb: Path, basename: str, out: Path) -> None:
    """Copy the file named `basename` out of a Debian package (an ar archive holding data.tar.*)."""
    import io
    modes = {"data.tar.xz": "r:xz", "data.tar.gz": "r:gz", "data.tar.bz2": "r:bz2", "data.tar": "r:"}
    with deb.open("rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise SystemExit(f"{deb.name} is not a Debian package")
        while len(header := f.read(60)) == 60:
            name = header[:16].decode("ascii").strip().rstrip("/")
            size = int(header[48:58].decode("ascii").strip())
            if name in modes:
                with tarfile.open(fileobj=io.BytesIO(f.read(size)), mode=modes[name]) as t:
                    member = next((m for m in t.getmembers() if m.isfile() and Path(m.name).name == basename), None)
                    if member is None:
                        raise SystemExit(f"no {basename} in {deb.name}")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with t.extractfile(member) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                return
            f.seek(size + (size % 2), 1)  # ar members are 2-byte aligned
    raise SystemExit(f"no data archive in {deb.name}")


def fetch_sounds(platform: str, dest: Path) -> None:
    """FluidSynth (Windows build) into fluidsynth/bin, FluidR3_GM.sf2 into soundfonts/."""
    exe = ".exe" if platform == "windows" else ""
    if platform in FLUIDSYNTH:
        top = unpack(verified(*FLUIDSYNTH[platform]), ROOT / "build" / "unpacked" / "fluidsynth")
        shutil.rmtree(dest / "fluidsynth", ignore_errors=True)
        shutil.copytree(top / "bin", dest / "fluidsynth" / "bin")
        assert (dest / "fluidsynth" / "bin" / f"fluidsynth{exe}").is_file(), "no fluidsynth in its download"
    sf2 = dest / "soundfonts" / SOUNDFONT
    if not sf2.is_file():
        deb_file(verified(*SOUNDFONT_DEB), SOUNDFONT, sf2)
    notices = dest / "NOTICES.txt"
    text = notices.read_text(encoding="utf-8") if notices.is_file() else NOTICES
    if "FluidSynth" not in text:
        notices.write_text(text + SOUND_NOTICES, encoding="utf-8")


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

    (dest / "NOTICES.txt").write_text(NOTICES, encoding="utf-8")
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"tools in {dest}: {size / 2**20:.0f} MB", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--platform", choices=sorted(TOOLS), required=True)
    p.add_argument("--dest", type=Path, required=True)
    p.add_argument("--separation", action="store_true", help="also the drum separation model (HTDemucs)")
    p.add_argument("--sounds", action="store_true",
                   help="also FluidSynth (Windows) and the FluidR3_GM soundfont: real sampled drums")
    args = p.parse_args()
    fetch(args.platform, args.dest.resolve())
    if args.separation:
        fetch_separation(args.dest.resolve())
    if args.sounds:
        fetch_sounds(args.platform, args.dest.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
