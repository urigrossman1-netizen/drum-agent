"""HTTP API and page for the web app (FastAPI). Start it with `python -m drum_agent serve`.

Routes (all JSON unless noted):
  GET  /api/health                         dependencies, providers, Claude configuration
  GET  /api/search?q=Title - Artist        the chart catalog first, then metadata providers
  POST /api/songs                          pick a search result: stores it, resolves its source
  GET  /api/songs                          the catalog
  GET  /api/songs/{id}                     song, status, source resolution, jobs, chart versions
  POST /api/songs/{id}/upload              multipart file + rights: validated, normalized, queued
  POST /api/songs/{id}/use-asset           transcribe the operator-provided asset for this song
  POST /api/songs/{id}/jobs                (re)queue the song's latest source (idempotent)
  GET  /api/jobs/{id}                      stages, status, error
  POST /api/jobs/{id}/cancel | /retry
  GET  /api/charts/{id}                    chart version, validation, summary, bar map
  GET  /api/charts/{id}/files/{name}       chart.pdf | chart.musicxml | chart.mid | chart.json | page-N.svg
  GET  /api/charts/{id}/audio              the chart's source audio, for playback-follow (if any)
  POST /api/charts/{id}/suggest-sections   Claude's section names (a suggestion; changes nothing)
  POST /api/charts/{id}/sections           apply section names: a new chart version
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..audio.prepare import MAX_BYTES, AudioError
from ..model import RIGHTS, Score
from ..rights import RightsError
from . import claude, sources
from .jobs import ENGINE, JobRunner
from .providers import Providers, split_query
from .store import Store, default_data_dir

log = logging.getLogger("drum_agent.web")
STATIC = Path(__file__).parent / "static"
ID = {"song": re.compile(r"s_[0-9a-f]{16}"), "job": re.compile(r"job_[0-9a-f]{16}"),
      "chart": re.compile(r"ch_[0-9a-f]{16}"), "source": re.compile(r"src_[0-9a-f]{16}")}
FILES = {"chart.pdf": "application/pdf", "chart.musicxml": "application/vnd.recordare.musicxml+xml",
         "chart.mid": "audio/midi", "chart.json": "application/json"}
PAGE = re.compile(r"page-([1-9][0-9]{0,2})\.svg")


class SongIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    album: str | None = Field(default=None, max_length=300)
    year: int | None = None
    duration_s: float | None = None
    isrc: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=40)
    provider_id: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    id: str | None = None


class SectionName(BaseModel):
    first_bar: int
    name: str = Field(min_length=1, max_length=40)


class ReviewIn(BaseModel):
    bars: list[int] = Field(min_length=1, max_length=2000)  # score bar numbers (1-based)


class SectionsIn(BaseModel):
    sections: list[SectionName]
    source: str = Field(default="user", pattern="^(user|claude)$")


def _check(kind: str, value: str) -> str:
    if not ID[kind].fullmatch(value):
        raise HTTPException(404, f"no such {kind}")
    return value


def create_app(data_dir: str | Path | None = None, *, providers: Providers | None = None,
               start_worker: bool = True) -> FastAPI:
    store = Store(data_dir or default_data_dir())
    runner = JobRunner(store, start=start_worker)
    providers = providers or Providers()
    revise_lock = threading.Lock()
    app = FastAPI(title="Drum Agent", version=__version__, docs_url=None, redoc_url=None)
    app.state.store, app.state.runner, app.state.providers = store, runner, providers
    app.state.revise_lock, app.state.public_job = revise_lock, _public_job
    from . import samples
    from .studio import router as studio_router
    app.include_router(studio_router)
    if start_worker and samples.available():  # render the drum sounds before the first play
        def warm():
            for inst in samples.instruments():
                try:
                    samples.sample_path(store.root / "samples", inst["id"])
                except Exception:  # noqa: BLE001 - a missing sound falls back to the synthesized kit
                    log.warning("could not render the %s sample", inst["id"])
        threading.Thread(target=warm, name="drum-agent-samples", daemon=True).start()

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'")
        return response

    @app.exception_handler(AudioError)
    async def audio_error(request: Request, exc: AudioError):
        return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=422)

    # ---- health ----------------------------------------------------------
    @app.get("/api/health")
    def health():
        import shutil

        from ..export.render import RenderError, find_lilypond, lilypond_version
        checks = {}
        try:
            checks["lilypond"] = {"ok": True, "version": lilypond_version(find_lilypond())[1]}
        except RenderError as exc:
            checks["lilypond"] = {"ok": False, "detail": str(exc).split("\n")[0]}
        for tool in ("ffmpeg", "ffprobe"):
            checks[tool] = {"ok": shutil.which(tool) is not None}
        weights = Path(__file__).parents[1] / "data" / "onset_classifier.npz"
        checks["onset_classifier"] = {"ok": weights.is_file()}
        try:
            store.list_songs(1)
            checks["database"] = {"ok": True}
        except sqlite3.Error as exc:  # pragma: no cover - a broken database file
            checks["database"] = {"ok": False, "detail": type(exc).__name__}
        cfg = claude.config()
        ok = all(c["ok"] for c in checks.values())
        body = {"ok": ok, "version": __version__, "engine": ENGINE, "checks": checks,
                "providers": providers.status(),
                "claude": {"configured": cfg["configured"], "missing": cfg["missing"]},
                "licensed_audio_providers": [], "rights_options": RIGHTS,
                "asset_dir_configured": sources.asset_dir() is not None,
                "limits": {"max_upload_mb": MAX_BYTES // 2**20}}
        return JSONResponse(body, status_code=200 if ok else 503)

    # ---- search ----------------------------------------------------------
    @app.get("/api/search")
    def search(q: str = ""):
        text = " ".join(q.split())[:300]
        if not text:
            raise HTTPException(400, "type a song name, e.g. American Idiot - Green Day")
        title, artist = split_query(text)
        catalog = [_song_card(store, s) for s in store.find_songs(f"{title} {artist or ''}")]
        results, states = providers.search(text)
        known = {c["id"] for c in catalog}
        for r in results:
            r["in_catalog"] = r["id"] in known
            existing = store.get_song(r["id"])
            r["status"] = sources.song_status(store, existing) if existing else "NEEDS_SOURCE"
        return {"query": text, "title": title, "artist": artist, "catalog": catalog,
                "results": [r for r in results if not r["in_catalog"]], "providers": states}

    # ---- songs -----------------------------------------------------------
    @app.get("/api/songs")
    def songs():
        return {"songs": [_song_card(store, s) for s in store.list_songs()]}

    @app.post("/api/songs")
    def pick(song: SongIn):
        if song.id:
            existing = store.get_song(_check("song", song.id))
            if existing:
                return _song_detail(store, existing)
        row = store.upsert_song(title=song.title.strip(), artist=song.artist.strip(), album=song.album,
                                year=song.year, duration_s=song.duration_s, isrc=song.isrc, version=song.version,
                                provider=song.provider, provider_id=song.provider_id,
                                urls={song.provider: song.url} if song.provider and song.url else None,
                                song_id=song.id)
        return _song_detail(store, row)

    @app.get("/api/songs/{song_id}")
    def song(song_id: str):
        return _song_detail(store, _song(store, song_id))

    @app.post("/api/songs/{song_id}/upload")
    def upload(song_id: str, file: Annotated[UploadFile, File()], rights: Annotated[str, Form()] = ""):
        row = _song(store, song_id)
        name = sources.safe_name(file.filename)
        try:
            sources.rights_gate.require_rights(rights or None, name)
        except RightsError as exc:
            raise HTTPException(403, str(exc)) from None
        tmp = sources.save_stream(file.file, MAX_BYTES, dir=store.root / "uploads")
        try:
            src = sources.add_upload(store, row, tmp, name, rights)
        finally:
            tmp.unlink(missing_ok=True)
        job, created = runner.submit(row["id"], src["id"])
        return {"source": _public_source(src), "job": _public_job(job), "created": created}

    @app.post("/api/songs/{song_id}/use-asset")
    def use_asset(song_id: str):
        row = _song(store, song_id)
        src = sources.add_asset(store, row)
        if src is None:
            raise HTTPException(404, "no authorized asset is configured for this song")
        job, created = runner.submit(row["id"], src["id"])
        return {"source": _public_source(src), "job": _public_job(job), "created": created}

    @app.post("/api/songs/{song_id}/jobs")
    def start(song_id: str):
        row = _song(store, song_id)
        srcs = store.sources_for(row["id"])
        if not srcs:
            raise HTTPException(409, "this song has no authorized source yet; upload a recording first")
        job, created = runner.submit(row["id"], srcs[0]["id"])
        return {"job": _public_job(job), "created": created}

    # ---- jobs ------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return _public_job(_job(store, job_id))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        _job(store, job_id)
        return _public_job(runner.cancel(job_id))

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        _job(store, job_id)
        try:
            return _public_job(runner.retry(job_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    # ---- charts ----------------------------------------------------------
    @app.get("/api/charts/{chart_id}")
    def chart(chart_id: str):
        c = _chart(store, chart_id)
        d = Path(c["dir"])
        view = json.loads((d / "view.json").read_text())
        song_row = store.get_song(c["song_id"])
        return {**_public_chart(c), "song": _public_song(song_row), "view": view,
                "versions": [_public_chart(v) for v in store.charts_for(c["song_id"])],
                "has_audio": bool(c["source_id"]),
                "files": {k: f"/api/charts/{c['id']}/files/{k}" for k in FILES if (d / k).is_file()}}

    @app.get("/api/charts/{chart_id}/files/{name}")
    def chart_file(chart_id: str, name: str, download: int = 0):
        c = _chart(store, chart_id)
        d = Path(c["dir"])
        if name in FILES:
            path, media = d / name, FILES[name]
        elif PAGE.fullmatch(name):
            path, media = d / "view" / name, "image/svg+xml"
        else:
            raise HTTPException(404, "no such file")
        if not path.is_file():
            raise HTTPException(404, "no such file")
        song_row = store.get_song(c["song_id"])
        nice = _download_name(song_row, c, name)
        headers = {"Cache-Control": "private, max-age=3600"}
        return FileResponse(path, media_type=media, headers=headers,
                            filename=nice if download else None,
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/charts/{chart_id}/audio")
    def chart_audio(chart_id: str):
        c = _chart(store, chart_id)
        src = store.get_source(c["source_id"]) if c["source_id"] else None
        if src is None or not Path(src["path"]).is_file():
            raise HTTPException(404, "this chart has no source audio")
        return FileResponse(src["path"], media_type="audio/wav", headers={"Cache-Control": "private, no-store"})

    @app.post("/api/charts/{chart_id}/suggest-sections")
    def suggest(chart_id: str):
        c = _chart(store, chart_id)
        score = Score.load(Path(c["dir"]) / "chart.json")
        try:
            return {"suggestion": claude.suggest_section_names(score), "applied": False}
        except claude.ClaudeUnavailable as exc:
            status = 503 if exc.code in ("not_configured", "unreachable", "timeout", "rate_limited") else 502
            return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=status)

    @app.post("/api/charts/{chart_id}/sections")
    def apply_sections(chart_id: str, body: SectionsIn):
        c = _chart(store, chart_id)
        score = Score.load(Path(c["dir"]) / "chart.json")
        boundaries = [i + 1 for i, m in enumerate(score.measures) if m.section]
        if [s.first_bar for s in body.sections] != boundaries:
            raise HTTPException(422, f"section names must be given for the existing boundaries, bars {boundaries}")
        for s in body.sections:
            if not claude.NAME_RE.fullmatch(" ".join(s.name.split())) and body.source == "claude":
                raise HTTPException(422, f"{s.name!r} is not an allowed section name")
            score.measures[s.first_bar - 1].section = " ".join(s.name.split())
        score.analysis = {**(score.analysis or {}), "section_names": (
            "suggested by Claude and accepted by the user" if body.source == "claude" else "named by the user")}
        song_row = store.get_song(c["song_id"])
        src = store.get_source(c["source_id"]) if c["source_id"] else None
        with revise_lock:
            new = runner._save_chart(song_row, score, lambda stage: None, origin="correction", source=src,
                                     audio_duration=src["info"].get("duration_s") if src else None,
                                     parent_id=c["id"])
        return _public_chart(new)

    @app.post("/api/charts/{chart_id}/review")
    def review(chart_id: str, body: ReviewIn):
        """A person listened to these bars and confirms them: their review flags are cleared
        in a new chart version (the notes are not changed)."""
        from ..edit import EditError, mark_verified
        c = _chart(store, chart_id)
        score = Score.load(Path(c["dir"]) / "chart.json")
        try:
            cleared = sum(mark_verified(score, str(b)) for b in sorted(set(body.bars)))
        except (EditError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
        if not cleared:
            raise HTTPException(409, "none of these bars is flagged for review")
        song_row = store.get_song(c["song_id"])
        src = store.get_source(c["source_id"]) if c["source_id"] else None
        with revise_lock:
            new = runner._save_chart(song_row, score, lambda stage: None, origin="correction", source=src,
                                     audio_duration=src["info"].get("duration_s") if src else None,
                                     parent_id=c["id"])
        return _public_chart(new)

    # ---- page ------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


# ---- views of rows (no server paths, no secrets) ---------------------------------------

def _song(store: Store, song_id: str) -> dict:
    row = store.get_song(_check("song", song_id))
    if row is None:
        raise HTTPException(404, "no such song")
    return row


def _job(store: Store, job_id: str) -> dict:
    row = store.get_job(_check("job", job_id))
    if row is None:
        raise HTTPException(404, "no such job")
    return row


def _chart(store: Store, chart_id: str) -> dict:
    row = store.get_chart(_check("chart", chart_id))
    if row is None or not (Path(row["dir"]) / "view.json").is_file():
        raise HTTPException(404, "no such chart")
    return row


def _public_song(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "title", "artist", "album", "year", "duration_s", "isrc", "version", "provider",
                                  "urls", "kind", "prompt", "updated_at")}


def _public_source(s: dict) -> dict:
    info = s.get("info") or {}
    return {"id": s["id"], "kind": s["kind"], "rights": s["rights"], "rights_text": RIGHTS.get(s["rights"]),
            "name": s["original_name"], "duration_s": info.get("duration_s"),
            "original": {k: info.get(f"original_{k}") for k in ("codec", "sample_rate", "channels", "format")},
            "levels": {"rms_dbfs": info.get("rms_dbfs"), "peak_dbfs": info.get("peak_dbfs")}}


def _public_job(j: dict) -> dict:
    from .jobs import STAGES_BY_KIND
    out = {k: j.get(k) for k in ("id", "song_id", "source_id", "kind", "status", "stage", "stages", "error",
                                 "error_code", "attempts", "chart_id", "engine", "created_at", "updated_at")}
    out["plan"] = [{"name": n, "label": label} for n, label in STAGES_BY_KIND.get(j.get("kind") or "transcribe", [])]
    return out


def _public_chart(c: dict) -> dict:
    return {k: c.get(k) for k in ("id", "song_id", "version", "parent_id", "status", "origin", "bars", "validation",
                                  "summary", "created_at", "note", "source_id")}


def _song_card(store: Store, s: dict) -> dict:
    chart = store.latest_chart(s["id"])
    return {**_public_song(s), "status": sources.song_status(store, s),
            "chart": _public_chart(chart) if chart else None}


def _song_detail(store: Store, s: dict) -> dict:
    return {"song": _public_song(s), "status": sources.song_status(store, s),
            "resolution": {k: v for k, v in sources.resolve(store, s).items() if k != "path"},
            "sources": [_public_source(x) for x in store.sources_for(s["id"])],
            "jobs": [_public_job(j) for j in store.jobs_for(s["id"])][:10],
            "charts": [_public_chart(c) for c in store.charts_for(s["id"])]}


def _download_name(song: dict, chart: dict, name: str) -> str:
    base = f"{song['title']} - {song['artist']} - drums v{chart['version']}"
    base = re.sub(r"[^\w\s.,()'&-]", "", base).strip()[:150] or "chart"
    return base + Path(name).suffix


def serve(host: str = "127.0.0.1", port: int = 8000, data_dir: str | None = None) -> None:
    import uvicorn
    logging.basicConfig(level=os.environ.get("DRUM_AGENT_LOG_LEVEL", "INFO"))
    uvicorn.run(create_app(data_dir), host=host, port=port, log_level="info")
