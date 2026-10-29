"""The studio API: original beats, the working score, previews, versions and the library.

Routes:
  GET   /api/kit                          instruments (staff order, MIDI notes) and sample availability
  GET   /api/kit/samples/{inst}.wav       a sampled drum sound (rendered from the GM soundfont)
  GET   /api/beats/styles                 the generator's styles (for the quick settings)
  POST  /api/beats/interpret              what a description means, without generating
  POST  /api/beats                        start a generation job: a new beat project
  POST  /api/beats/transform              regenerate / variation / simpler / ... on a working score
  POST  /api/beats/command                a plain-language edit on a working score
  POST  /api/preview                      engrave a working score for the screen (SVG, no PDF)
  GET   /api/previews/{key}/{page}        a preview page
  GET   /api/projects                     the library (songs and beats), searchable
  GET   /api/projects/{id}                one project: status, versions, jobs, draft
  PATCH /api/projects/{id}                rename
  PUT   /api/projects/{id}/draft          keep the unsaved working score on the server
  DELETE /api/projects/{id}/draft         discard it
  POST  /api/projects/{id}/versions       save the working score as a new chart version
  POST  /api/projects/{id}/duplicate      copy the project with its latest version
  DELETE /api/projects/{id}               delete the project, its versions and its audio
  POST  /api/charts/{id}/restore          make an earlier version the newest one

A working score is the IR (`Score.to_dict()`); every route that takes one parses and
validates it before using it, and nothing the client sends is written as a file name.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..generate.edits import EXAMPLES, EditError
from ..generate.styles import STYLES
from ..kit import DEFAULT_KIT
from ..model import Score, ScoreError
from ..validate import validate_score
from . import samples, sources
from .beats import apply_action, apply_command, interpret_request
from .jobs import PROVISIONAL_TITLE, ChartInvalid
from .store import new_id

router = APIRouter()
MAX_BARS, MAX_HITS = 400, 40000
MAX_PREVIEWS = 150
_render_slots = threading.BoundedSemaphore(2)


class BeatIn(BaseModel):
    prompt: str = Field(default="", max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=120)
    request_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


class InterpretIn(BaseModel):
    prompt: str = Field(default="", max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)


class ScoreIn(BaseModel):
    score: dict[str, Any]


class TransformIn(ScoreIn):
    action: str = Field(max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)


class CommandIn(ScoreIn):
    command: str = Field(min_length=1, max_length=500)


class DraftIn(ScoreIn):
    base_chart_id: str | None = Field(default=None, max_length=40)


class VersionIn(ScoreIn):
    note: str | None = Field(default=None, max_length=200)
    base_chart_id: str | None = Field(default=None, max_length=40)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


# ---- helpers -------------------------------------------------------------------------------

def _state(request: Request):
    return request.app.state.store, request.app.state.runner


def parse_score(d: dict) -> Score:
    """A working score from the client, or a 422 that says what is wrong with it."""
    try:
        score = Score.from_dict(d)
        if len(score.measures) > MAX_BARS:
            raise ScoreError(f"a chart can have at most {MAX_BARS} bars")
        if sum(len(m.hits) for m in score.measures) > MAX_HITS:
            raise ScoreError("the chart has too many strokes")
        score.validate(DEFAULT_KIT)
    except (ScoreError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, f"the chart is not valid: {exc}") from None
    return score


def _project(store, project_id: str) -> dict:
    from .app import _check
    row = store.get_song(_check("song", project_id))
    if row is None:
        raise HTTPException(404, "no such project")
    return row


def project_card(store, s: dict) -> dict:
    charts = store.charts_for(s["id"])
    c = charts[0] if charts else None
    summary = (c or {}).get("summary") or {}
    return {"id": s["id"], "kind": s.get("kind") or "song", "title": s["title"], "artist": s["artist"],
            "album": s.get("album"), "year": s.get("year"), "version": s.get("version"),
            "prompt": s.get("prompt"), "status": sources.song_status(store, s),
            "created_at": s["created_at"], "updated_at": s.get("updated_at") or s["created_at"],
            "versions": len(charts), "has_draft": bool(s.get("draft")),
            "chart": {"id": c["id"], "version": c["version"], "status": c["status"], "bars": c["bars"],
                      "origin": c["origin"], "tempo": summary.get("tempo"),
                      "time_signature": summary.get("time_signature")} if c else None}


def _public_chart(c: dict) -> dict:
    from .app import _public_chart as pc
    return pc(c)


# ---- kit -----------------------------------------------------------------------------------

@router.get("/api/kit")
def kit():
    return {"instruments": samples.instruments(), "samples": samples.available(),
            "sample_source": "FluidR3_GM soundfont (MIT licence), rendered with fluidsynth"
            if samples.available() else None}


@router.get("/api/kit/samples/{name}")
def kit_sample(name: str, request: Request):
    store, _ = _state(request)
    inst = name[:-4] if name.endswith(".wav") else ""
    if inst not in DEFAULT_KIT:
        raise HTTPException(404, "no such instrument")
    try:
        path = samples.sample_path(store.root / "samples", inst)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


# ---- beats ---------------------------------------------------------------------------------

@router.get("/api/beats/styles")
def styles():
    return {"styles": [{"key": k, "label": s.label, "bpm": s.bpm, "time_signature": s.time_signature,
                        "triplet": s.triplet} for k, s in STYLES.items()],
            "edit_examples": EXAMPLES}


@router.post("/api/beats/interpret")
def interpret(body: InterpretIn):
    spec, notes, info = interpret_request(body.prompt, body.settings, use_claude=False)
    return {"spec": spec.to_dict(), "notes": notes, "interpreter": info}


@router.post("/api/beats")
def create_beat(body: BeatIn, request: Request):
    store, runner = _state(request)
    if not body.prompt.strip() and not body.settings:
        raise HTTPException(400, "describe the beat, or choose a style in the quick settings")
    title = (body.title or "").strip() or PROVISIONAL_TITLE
    if body.request_id:
        existing = store.job_by_key(f"generate|{body.request_id}")
        if existing:
            return {"project": project_card(store, store.get_song(existing["song_id"])),
                    "job": request.app.state.public_job(existing), "created": False}
    pid = new_id("s")
    store.upsert_song(title=title, artist="Original beat", song_id=pid, kind="beat", prompt=body.prompt.strip() or None,
                      provider="generator")
    job, created = runner.submit_generate(pid, {"prompt": body.prompt, "settings": body.settings,
                                                "title": body.title, "request_id": body.request_id})
    return {"project": project_card(store, store.get_song(pid)), "job": request.app.state.public_job(job),
            "created": created}


@router.post("/api/beats/transform")
def transform_beat(body: TransformIn):
    score = parse_score(body.score)
    try:
        new, message = apply_action(score, body.action, body.params)
    except EditError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"score": new.to_dict(), "message": message}


@router.post("/api/beats/command")
def command(body: CommandIn):
    score = parse_score(body.score)
    try:
        new, done, info = apply_command(score, body.command)
    except EditError as exc:
        return JSONResponse({"error": "unsupported", "detail": str(exc), "examples": EXAMPLES}, status_code=422)
    return {"score": new.to_dict(), "applied": done, "interpreter": info}


# ---- previews ------------------------------------------------------------------------------

@router.post("/api/preview")
def preview(body: ScoreIn, request: Request):
    from ..export.render import RenderError
    from .view import render_preview
    store, _ = _state(request)
    score = parse_score(body.score)
    canonical = json.dumps(score.to_dict(), sort_keys=True)
    key = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    out = store.root / "previews" / key
    validation = validate_score(score, DEFAULT_KIT).to_dict()
    if not (out / "view.json").is_file():
        with _render_slots:
            try:
                tmp = out.with_name(key + ".part")
                shutil.rmtree(tmp, ignore_errors=True)
                view = render_preview(score, tmp)
                (tmp / "view.json").write_text(json.dumps(view))
                shutil.rmtree(out, ignore_errors=True)
                tmp.rename(out)
            except RenderError as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(422, "LilyPond could not engrave this chart: " + str(exc).split("\n")[0][:300]) \
                    from None
        _prune(store.root / "previews")
    else:
        (out / "view.json").touch()
    view = json.loads((out / "view.json").read_text())
    return {"key": key, "view": view, "validation": validation}


def _prune(root: Path) -> None:
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and not p.name.endswith(".part")),
                  key=lambda p: p.stat().st_mtime)
    for p in dirs[:-MAX_PREVIEWS]:
        shutil.rmtree(p, ignore_errors=True)


@router.get("/api/previews/{key}/{page}")
def preview_page(key: str, page: str, request: Request):
    import re
    store, _ = _state(request)
    if not re.fullmatch(r"[0-9a-f]{24}", key) or not re.fullmatch(r"page-[1-9][0-9]{0,2}\.svg", page):
        raise HTTPException(404, "no such page")
    path = store.root / "previews" / key / page
    if not path.is_file():
        raise HTTPException(404, "no such page")
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=86400"})


# ---- projects ------------------------------------------------------------------------------

@router.get("/api/projects")
def projects(request: Request, q: str = "", kind: str | None = None):
    store, _ = _state(request)
    if kind not in (None, "", "song", "beat"):
        raise HTTPException(400, "kind is song or beat")
    return {"projects": [project_card(store, s) for s in store.list_projects(q[:200], kind or None)]}


@router.get("/api/projects/{project_id}")
def project(project_id: str, request: Request):
    store, _ = _state(request)
    s = _project(store, project_id)
    public_job = request.app.state.public_job
    out = {**project_card(store, s),
           "charts": [_public_chart(c) for c in store.charts_for(s["id"])],
           "jobs": [public_job(j) for j in store.jobs_for(s["id"])][:10],
           "draft": s.get("draft")}
    if out["kind"] == "song":
        from .app import _public_source
        out["resolution"] = {k: v for k, v in sources.resolve(store, s).items() if k != "path"}
        out["sources"] = [_public_source(x) for x in store.sources_for(s["id"])]
    return out


@router.patch("/api/projects/{project_id}")
def rename(project_id: str, body: RenameIn, request: Request):
    store, _ = _state(request)
    _project(store, project_id)
    return project_card(store, store.rename(project_id, " ".join(body.title.split())))


@router.put("/api/projects/{project_id}/draft")
def save_draft(project_id: str, body: DraftIn, request: Request):
    store, _ = _state(request)
    _project(store, project_id)
    score = parse_score(body.score)
    store.set_draft(project_id, {"score": score.to_dict(), "base_chart_id": body.base_chart_id, "saved_at": time.time()})
    return {"saved_at": time.time()}


@router.delete("/api/projects/{project_id}/draft")
def discard_draft(project_id: str, request: Request):
    store, _ = _state(request)
    _project(store, project_id)
    store.set_draft(project_id, None)
    return {"ok": True}


@router.post("/api/projects/{project_id}/versions")
def save_version(project_id: str, body: VersionIn, request: Request):
    store, runner = _state(request)
    s = _project(store, project_id)
    score = parse_score(body.score)
    base = store.get_chart(body.base_chart_id) if body.base_chart_id else store.latest_chart(project_id)
    if base is not None and base["song_id"] != project_id:
        raise HTTPException(422, "that version belongs to another project")
    if s.get("kind") == "beat":
        score.title = s["title"]
    src = store.get_source(base["source_id"]) if base and base.get("source_id") else None
    # An edit never changes the rights basis (a personal-practice chart stays one): it comes from
    # the recording, else from the version edited.
    if src is not None:
        score.rights = src["rights"]
    elif base is not None and (base.get("summary") or {}).get("rights"):
        score.rights = base["summary"]["rights"]
    with request.app.state.revise_lock:
        try:
            chart = runner._save_chart(s, score, lambda stage: None, origin="edit", source=src,
                                       audio_duration=src["info"].get("duration_s") if src else None,
                                       parent_id=base["id"] if base else None, note=body.note or "Edited")
        except ChartInvalid as exc:
            raise HTTPException(422, str(exc)) from None
    store.set_draft(project_id, None)
    return _public_chart(chart)


@router.post("/api/projects/{project_id}/duplicate")
def duplicate(project_id: str, request: Request):
    store, _ = _state(request)
    s = _project(store, project_id)
    pid = new_id("s")
    store.upsert_song(title=f"{s['title']} (copy)"[:120], artist=s["artist"], album=s.get("album"), year=s.get("year"),
                      duration_s=s.get("duration_s"), isrc=s.get("isrc"), version=s.get("version"),
                      provider=s.get("provider"), song_id=pid, kind=s.get("kind") or "song", prompt=s.get("prompt"))
    latest = store.latest_chart(project_id)
    if latest is not None:
        cid = new_id("ch")
        shutil.copytree(latest["dir"], store.chart_dir(cid))
        store.add_chart(chart_id=cid, song_id=pid, status=latest["status"], origin="duplicate", bars=latest["bars"],
                        validation=latest["validation"], summary=latest["summary"], source_id=latest.get("source_id"),
                        parent_id=latest["id"], note=f"Copy of “{s['title']}” v{latest['version']}")
    if s.get("draft"):
        store.set_draft(pid, s["draft"])
    return project_card(store, store.get_song(pid))


@router.delete("/api/projects/{project_id}")
def delete(project_id: str, request: Request):
    store, _ = _state(request)
    _project(store, project_id)
    if any(j["status"] in ("queued", "running") for j in store.jobs_for(project_id)):
        raise HTTPException(409, "a job is still running for this project; cancel it first")
    for p in store.delete_project(project_id):
        path = Path(p).resolve()
        if store.root in path.parents:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return {"deleted": project_id}


@router.post("/api/charts/{chart_id}/restore")
def restore(chart_id: str, request: Request):
    from .app import _chart
    store, runner = _state(request)
    c = _chart(store, chart_id)
    s = store.get_song(c["song_id"])
    score = Score.load(Path(c["dir"]) / "chart.json")
    src = store.get_source(c["source_id"]) if c.get("source_id") else None
    with request.app.state.revise_lock:
        chart = runner._save_chart(s, score, lambda stage: None, origin="restore", source=src,
                                   audio_duration=src["info"].get("duration_s") if src else None,
                                   parent_id=c["id"], note=f"Restored version {c['version']}")
    return _public_chart(chart)
