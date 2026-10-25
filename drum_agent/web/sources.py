"""Source resolution: for a chosen recording, what can the app transcribe or show?

In order:

1. EXISTING_CHART      a chart version for this song is already stored (shown at once)
2. AUTHORIZED_ASSET    the operator placed the recording in the asset directory
                       (DRUM_AGENT_ASSET_DIR) with a manifest entry stating its rights basis
3. USER_UPLOAD         the user uploaded the recording and stated a rights basis
4. LICENSED_SOURCE     a licensed audio provider; none is configured in this build, and the
                       answer says so rather than pretending one exists
5. NEEDS_SOURCE        the song is identified but no authorized audio is available: the
                       user can upload a recording they have the right to transcribe

Streaming services are never a source: Spotify and YouTube results are metadata only,
and the server never downloads audio from them (`drum_agent/rights.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import rights as rights_gate
from ..audio.prepare import EXTENSIONS, MAX_BYTES, AudioError, file_sha256, prepare
from ..model import RIGHTS
from ..song.lookup import artist_key, title_key
from .store import Store

CASES = ("EXISTING_CHART", "AUTHORIZED_ASSET", "USER_UPLOAD", "LICENSED_SOURCE", "NEEDS_SOURCE")


def asset_dir() -> Path | None:
    d = os.environ.get("DRUM_AGENT_ASSET_DIR")
    return Path(d).resolve() if d else None


def asset_manifest() -> list[dict]:
    """Entries of <asset dir>/assets.json: [{"file", "title", "artist", "rights"}]. Entries
    without a valid rights basis, or whose file is outside the directory, are ignored."""
    root = asset_dir()
    if root is None or not (root / "assets.json").is_file():
        return []
    try:
        entries = json.loads((root / "assets.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or e.get("rights") not in RIGHTS:
            continue
        path = (root / str(e.get("file", ""))).resolve()
        if path.is_file() and root in path.parents and path.suffix.lower() in EXTENSIONS:
            out.append({**e, "path": path})
    return out


def find_asset(song: dict) -> dict | None:
    key = (title_key(song["title"]), artist_key(song["artist"]))
    for e in asset_manifest():
        if (title_key(e.get("title")), artist_key(e.get("artist"))) == key:
            return e
    return None


def resolve(store: Store, song: dict) -> dict:
    charts = store.charts_for(song["id"])
    if charts:
        c = charts[0]
        return {"case": "EXISTING_CHART", "chart_id": c["id"], "chart_status": c["status"],
                "detail": f"chart version {c['version']} ({c['status']})"}
    sources = store.sources_for(song["id"])
    if sources:
        s = sources[0]
        case = "AUTHORIZED_ASSET" if s["kind"] == "asset" else "USER_UPLOAD"
        return {"case": case, "source_id": s["id"], "detail": f"{s['original_name']} (rights: {RIGHTS[s['rights']]})"}
    asset = find_asset(song)
    if asset is not None:
        return {"case": "AUTHORIZED_ASSET", "source_id": None, "asset": asset["file"],
                "detail": f"{asset['file']} in the asset directory (rights: {RIGHTS[asset['rights']]})"}
    return {"case": "NEEDS_SOURCE", "licensed_providers": [],
            "detail": "No authorized audio for this recording is available to the server. No licensed audio "
                      "provider is configured, and streaming services (Spotify, YouTube) are metadata only. "
                      "Upload a recording you have the right to transcribe."}


def song_status(store: Store, song: dict) -> str:
    """NOT_STARTED, ANALYZING, TRANSCRIBING, VERIFYING, NEEDS_SOURCE, NEEDS_CORRECTION or COMPLETE."""
    jobs = store.jobs_for(song["id"])
    active = next((j for j in jobs if j["status"] in ("queued", "running")), None)
    if active is not None:
        stage = active["stage"]
        if stage in (None, "prepare"):
            return "ANALYZING"
        if stage in ("detect", "beats", "measures", "sections"):
            return "TRANSCRIBING"
        return "VERIFYING"
    chart = store.latest_chart(song["id"])
    if chart is not None:
        return chart["status"]
    if store.sources_for(song["id"]) or find_asset(song) is not None:
        return "NOT_STARTED"
    return "NEEDS_SOURCE"


def add_upload(store: Store, song: dict, upload_path: Path, original_name: str, rights: str) -> dict:
    """Validate and normalize an uploaded file and record it as a source for the song.
    The rights gate runs first: nothing is decoded without a stated basis."""
    rights_gate.require_rights(rights, original_name)
    sha = file_sha256(upload_path)
    for s in store.sources_for(song["id"]):
        if s["sha256"] == sha and Path(s["path"]).is_file():
            return s  # the same recording again: no second decode, and the same job later
    wav = store.root / "sources" / f"{sha}.wav"
    info = prepare(upload_path, wav, original_name=original_name)
    meta = info.to_dict()
    meta.pop("path")
    return store.add_source(song_id=song["id"], kind="upload", rights=rights, sha256=sha, path=str(wav),
                            original_name=safe_name(original_name), info=meta)


def add_asset(store: Store, song: dict) -> dict | None:
    asset = find_asset(song)
    if asset is None:
        return None
    sha = file_sha256(asset["path"])
    wav = store.root / "sources" / f"{sha}.wav"
    info = prepare(asset["path"], wav, original_name=asset["path"].name)
    meta = info.to_dict()
    meta.pop("path")
    return store.add_source(song_id=song["id"], kind="asset", rights=asset["rights"], sha256=sha, path=str(wav),
                            original_name=asset["path"].name, info=meta)


def safe_name(name: str | None) -> str:
    """A display name for an uploaded file: no directories, no control characters."""
    base = Path((name or "upload").replace("\\", "/")).name
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    return base[:120] or "upload"


def save_stream(stream, limit: int = MAX_BYTES, dir: Path | None = None) -> Path:
    """Copy an upload to a temporary file, refusing it once it passes the size limit."""
    fd, tmp = tempfile.mkstemp(prefix="upload-", dir=dir)
    total = 0
    with os.fdopen(fd, "wb") as out:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                out.close()
                os.unlink(tmp)
                raise AudioError("too_large", f"the file is over the {limit / 2**20:.0f} MB limit")
            out.write(chunk)
    return Path(tmp)

