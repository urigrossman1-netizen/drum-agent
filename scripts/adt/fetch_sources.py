"""Fetch the training sources where the Debian/Ubuntu packages aren't installed (Windows).

scripts/adt/oneshots.py and generate.py read drum kits and General MIDI soundfonts from the
Debian package paths (/usr/share/sounds/sf2, /usr/share/hydrogen/data/drumkits). This
downloads the same packages from deb.debian.org, checks each against the SHA-256 that
packages.debian.org publishes, and unpacks them under ~/.cache/drum-agent/adt/debian.
Point the scripts there with DRUM_AGENT_SAMPLE_ROOT (printed at the end).

  python scripts/adt/fetch_sources.py      # about 530 MB of downloads, once

FluidR3_GM.sf2 is copied in from tools/soundfonts (packaging/fetch_tools.py --sounds).
Nothing is redistributed: the samples only shape the classifier's weights (docs/MODELS.md
lists each source's licence).
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = Path(os.environ.get("DRUM_AGENT_DATA", Path.home() / ".cache" / "drum-agent")) / "adt" / "debian"
POOL = "https://deb.debian.org/debian/pool/main/"
# pool path, SHA-256 from packages.debian.org/<suite>/all/<package>/download (2026-11-05)
PACKAGES = [
    ("h/hydrogen-drumkits/hydrogen-drumkits_2017.09.19~dfsg-1_all.deb",  # Debian 12
     "6ea3c6df9a67762e2362f946c695e619859126b19fbccf32a2e8f07dfd03b2f4"),
    ("a/avldrums.lv2/avldrums.lv2-soundfont_0.7.3-1_all.deb",  # Debian 13: has Blonde Bop
     "c5879904287dafd5c580412a09ff534032b22e7e57746352ed000919d4add468"),
    ("c/csound/csound-soundfont_6.18.1+dfsg-1_all.deb",
     "0d05bec0cff2486f4537dd0236fece99f3565b62959717f82e975be8e0cf1393"),
    ("m/musescore-general-soundfont/musescore-general-soundfont-lossless_0.2.1-1_all.deb",
     "ece0ce63dc4d4d44fecbd3ee6761b328e66c189892b2b369cbd8e79b4411a82b"),
    ("t/timgm6mb-soundfont/timgm6mb-soundfont_1.3-5_all.deb",
     "034abdfb296d9353433513dad5dbdcab46425ee6008fc02fe7039b46e75edc54"),
]
MODES = {"data.tar.xz": "r:xz", "data.tar.gz": "r:gz", "data.tar.bz2": "r:bz2", "data.tar": "r:"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch(pool_path: str, want: str, cache: Path) -> Path:
    name = pool_path.rsplit("/", 1)[-1]
    deb = cache / name
    if deb.exists() and sha256(deb) == want:
        return deb
    url = POOL + pool_path.replace("~", "%7E").replace("+", "%2B")
    req = urllib.request.Request(url, headers={"User-Agent": "drum-agent-training"})
    part = deb.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as out:
        shutil.copyfileobj(r, out, 1 << 20)
    got = sha256(part)
    if got != want:
        part.unlink()
        raise SystemExit(f"{name}: SHA-256 {got} is not the published {want}; deleted")
    part.replace(deb)
    return deb


def unpack(deb: Path, dest: Path) -> int:
    """Extract the package's data archive into dest (tarfile's "data" filter: no absolute
    paths, nothing outside dest, no device files)."""
    with deb.open("rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise SystemExit(f"{deb.name} is not a Debian package")
        while header := f.read(60):
            name, size = header[:16].decode().strip().rstrip("/"), int(header[48:58])
            data = f.read(size)
            f.read(size % 2)
            if name in MODES:
                with tarfile.open(fileobj=io.BytesIO(data), mode=MODES[name]) as t:
                    members = [m for m in t.getmembers() if m.name.lstrip("./").startswith("usr/")]
                    t.extractall(dest, members=members, filter="data")
                    return len(members)
    raise SystemExit(f"{deb.name}: no data archive")


def main() -> None:
    cache = DEST.parent / "debs"
    cache.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    for pool_path, want in PACKAGES:
        deb = fetch(pool_path, want, cache)
        n = unpack(deb, DEST)
        print(f"{deb.name}: {deb.stat().st_size / 1e6:.0f} MB, {n} files and folders unpacked", flush=True)
    sf2 = DEST / "usr" / "share" / "sounds" / "sf2"
    fluid = ROOT / "tools" / "soundfonts" / "FluidR3_GM.sf2"
    if not (sf2 / fluid.name).exists():
        if not fluid.exists():
            raise SystemExit(f"{fluid} missing: run packaging/fetch_tools.py --sounds first")
        shutil.copy2(fluid, sf2 / fluid.name)
    print("soundfonts:", ", ".join(sorted(p.name for p in sf2.glob("*.sf2"))))
    kits = DEST / "usr" / "share" / "hydrogen" / "data" / "drumkits"
    print("hydrogen kits:", ", ".join(sorted(p.name for p in kits.iterdir() if p.is_dir())))
    print(f"\nset DRUM_AGENT_SAMPLE_ROOT={DEST}")


if __name__ == "__main__":
    sys.exit(main())
