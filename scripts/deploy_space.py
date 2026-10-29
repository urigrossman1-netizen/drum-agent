"""Deploy the studio to a Hugging Face Space (Docker): a permanent public address.

The Space builds this repository's Dockerfile (LilyPond, FFmpeg, CPU PyTorch with HTDemucs
inside the image), the image .github/workflows/container.yml tests. It runs as a shared
server: every visitor gets a private workspace, and the personal-practice basis is refused.

    HF_TOKEN=... python scripts/deploy_space.py [--space drum-agent] [--dry-run]

HF_TOKEN is a Hugging Face access token with write permission. Keys found in the
environment are stored as the Space's own secrets, never in a file: YOUTUBE_API_KEY,
SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, ANTHROPIC_API_KEY, DRUM_AGENT_ANTHROPIC_MODEL.
Waits until the Space runs the new build, then prints its address (and writes it to
$GITHUB_OUTPUT as `url`). Charts live in /data, which a free Space loses when it restarts
unless persistent storage is mounted there (the Space's settings).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["Dockerfile", "pyproject.toml", "scripts/install_lilypond.sh", "examples/specs/03_full_song_northbound.yaml"]
SECRETS = ["YOUTUBE_API_KEY", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "ANTHROPIC_API_KEY",
           "DRUM_AGENT_ANTHROPIC_MODEL"]
BUILDING = ("BUILDING", "RUNNING_BUILDING", "APP_STARTING", "RUNNING_APP_STARTING")
CARD = """---
title: Drum Agent Studio
emoji: 🥁
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Drum transcription and engraved drum charts
---

# Drum Agent Studio

Upload a recording you have the right to transcribe (your own playing, a licence, the rights
holder's permission, public-domain material) and get its drum chart: the drums separated
from the band, every stroke detected and placed in its bar, engraved with LilyPond, with
PDF, MusicXML and MIDI exports, an editable grid and playback in time with the recording.
Or describe a beat and get it written out.

Source, documentation and measured accuracy: {repo}
"""


def assemble(dest: Path, repo_url: str) -> list[str]:
    """The Space's files: what the Dockerfile copies, and the Space's card as README.md."""
    for rel in FILES:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest / rel)
    shutil.copytree(ROOT / "drum_agent", dest / "drum_agent", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dest / "README.md").write_text(CARD.format(repo=repo_url), encoding="utf-8")
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())


def address(api, repo_id: str) -> str:
    info = api.space_info(repo_id)
    if info.host:
        return info.host if info.host.startswith("http") else "https://" + info.host
    sub = info.subdomain or re.sub(r"[^a-z0-9]+", "-", repo_id.lower())
    return f"https://{sub}.hf.space"


def wait_running(api, repo_id: str, minutes: float) -> None:
    """Until the new build runs. Just after the upload the Space can still show the previous
    build's stage, so a stage counts once the new build has begun (or after 3 minutes: there
    was nothing to rebuild)."""
    t0 = time.time()
    begun, seen = False, None
    while time.time() < t0 + minutes * 60:
        rt = api.get_space_runtime(repo_id)
        stage = str(rt.stage)
        if stage != seen:
            print(f"   Space: {stage} (hardware {rt.hardware or '-'})", flush=True)
            seen = stage
        begun = begun or stage in BUILDING
        if begun or time.time() - t0 > 180:
            if stage == "RUNNING":
                return
            if stage not in BUILDING:
                raise SystemExit(f"the Space is {stage}: {rt.raw.get('errorMessage') or 'see its logs'}")
        time.sleep(15)
    raise SystemExit(f"the Space was not running after {minutes:.0f} minutes (last stage {seen})")


def main() -> int:
    p = argparse.ArgumentParser(description="deploy the studio to a Hugging Face Space")
    p.add_argument("--space", default="drum-agent", help="the Space's name under the token's account")
    p.add_argument("--wait", type=float, default=70, help="minutes to wait for the build (default 70)")
    p.add_argument("--dry-run", action="store_true", help="only list the files that would be uploaded")
    args = p.parse_args()
    repo_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/" \
               f"{os.environ.get('GITHUB_REPOSITORY', 'urigrossman1-netizen/drum-agent')}"
    with tempfile.TemporaryDirectory() as tmp:
        files = assemble(Path(tmp), repo_url)
        print(f"{len(files)} files: " + ", ".join(f for f in files if not f.startswith("drum_agent/"))
              + f", drum_agent/ ({sum(f.startswith('drum_agent/') for f in files)} files)")
        if args.dry_run:
            return 0
        token = os.environ.get("HF_TOKEN")
        if not token:
            print("HF_TOKEN is not set: nothing deployed")
            return 1
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        repo_id = f"{api.whoami()['name']}/{args.space}"
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
        for key in SECRETS:
            if os.environ.get(key):
                api.add_space_secret(repo_id, key, os.environ[key])
        print("   Space secrets set: " + (", ".join(k for k in SECRETS if os.environ.get(k)) or "none"))
        commit = api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                                   commit_message=f"Deploy {os.environ.get('GITHUB_SHA', 'local')[:12]}",
                                   delete_patterns=["drum_agent/**", "scripts/**", "examples/**"])
        print(f"   uploaded to {repo_id}: {commit.commit_url}")
    wait_running(api, repo_id, args.wait)
    url = address(api, repo_id)
    print(f"running: {url}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"url={url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
