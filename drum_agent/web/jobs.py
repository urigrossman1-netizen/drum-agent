"""Background transcription jobs: one worker thread, persistent state, real stages.

A job turns one authorized source (a normalized WAV with a stated rights basis) into a
chart version:

  prepare   read the normalized audio
  detect    onset detection and instrument classification (the trained classifier)
  beats     tempo, meter and downbeat tracking
  measures  quantization into bars (exact positions)
  sections  section boundaries from the drum patterns
  validate  measure, timing and coverage checks (`drum_agent.validate`)
  render    LilyPond PDF, MusicXML and MIDI, cross-checked against the score
  view      the on-screen SVG pages and bar map
  save      the chart version is recorded

In the personal app a song can also be charted from its name alone: a "find" job first
searches YouTube for the recording (`search`) and downloads and decodes the best match
(`download`, see `online.py`), then runs the stages above on it.

The first five stages are reported by the transcriber itself as it reaches them, so
the stage shown is the work being done. Jobs are idempotent per (source audio, engine):
asking again for the same recording returns the job that already ran or is running.
A job left running by a crash or restart is queued again on start-up (`recover`).
Cancellation is honoured at the next stage boundary.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path

from .. import __version__
from ..audio.prepare import AudioError
from ..export.render import RenderError
from ..kit import DEFAULT_KIT
from ..model import Score
from ..pipeline import ExportError, ExportOptions, export_all
from ..song.fetch import FetchError
from ..validate import chart_status, validate_score
from .store import Store, new_id
from .view import build_view

log = logging.getLogger("drum_agent.web")

ENGINE = f"drum-agent {__version__} onset-classifier"
GENERATOR = f"drum-agent {__version__} beat generator"
PROVISIONAL_TITLE = "New beat"
STAGES = [
    ("prepare", "Reading the audio"),
    ("detect", "Detecting drum strokes"),
    ("beats", "Tracking tempo, meter and downbeats"),
    ("measures", "Building measures"),
    ("sections", "Finding sections"),
    ("validate", "Validating the chart"),
    ("render", "Engraving PDF, MusicXML and MIDI"),
    ("view", "Drawing the on-screen chart"),
    ("save", "Saving the chart"),
]
GENERATE_STAGES = [
    ("interpret", "Reading your description"),
    ("arrange", "Writing the groove, fills and ending"),
    ("validate", "Validating every bar"),
    ("render", "Engraving the notation"),
    ("view", "Drawing the on-screen chart"),
    ("save", "Saving the chart"),
]
FIND_STAGES = [
    ("search", "Finding the song on YouTube"),
    ("download", "Downloading the audio"),
    *STAGES,
]
STAGES_BY_KIND = {"transcribe": STAGES, "generate": GENERATE_STAGES, "find": FIND_STAGES}
STAGE_LABELS = dict(FIND_STAGES) | dict(GENERATE_STAGES)
MAX_ATTEMPTS = 2  # a job interrupted by a crash or restart is resumed once more, then failed


class Cancelled(Exception):
    pass


class JobRunner:
    def __init__(self, store: Store, start: bool = True):
        self.store = store
        self.queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        if start:
            self.recover()
            self._thread = threading.Thread(target=self._work, name="drum-agent-jobs", daemon=True)
            self._thread.start()

    # ---- API -------------------------------------------------------------
    def submit(self, song_id: str, source_id: str) -> tuple[dict, bool]:
        """(job, created): the existing job for this recording and engine when there is one."""
        source = self.store.get_source(source_id)
        if source is None or source["song_id"] != song_id:
            raise KeyError("source not found for this song")
        key = f"{source['sha256']}|{ENGINE}"
        existing = self.store.job_by_key(key)
        if existing is not None:
            return existing, False
        job = self.store.create_job(song_id=song_id, source_id=source_id, engine=ENGINE, key=key)
        self.queue.put(job["id"])
        return job, True

    def cancel(self, job_id: str) -> dict:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] == "queued":
            return self.store.update_job(job_id, status="cancelled", cancel_requested=1,
                                         stages=_close(job["stages"], "cancelled"))
        if job["status"] == "running":
            return self.store.update_job(job_id, cancel_requested=1)
        return job

    def retry(self, job_id: str) -> dict:
        """A failed or cancelled job runs again as a new job on the same source."""
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] not in ("failed", "cancelled"):
            raise ValueError(f"only a failed or cancelled job can be retried (this one is {job['status']})")
        if job["kind"] == "generate":
            new, _ = self.submit_generate(job["song_id"], {**job["params"], "request_id": None})
            return new
        if job["kind"] == "find":
            new, _ = self.submit_find(job["song_id"], job["params"].get("video"))
            return new
        new, _ = self.submit(job["song_id"], job["source_id"])
        return new

    def submit_generate(self, song_id: str, params: dict) -> tuple[dict, bool]:
        """A beat-generation job; one per request id (a double click doesn't make two beats)."""
        rid = params.get("request_id")
        key = f"generate|{rid}" if rid else f"generate|{new_id('r')}"
        existing = self.store.job_by_key(key) if rid else None
        if existing is not None:
            return existing, False
        job = self.store.create_job(song_id=song_id, source_id=None, engine=GENERATOR, key=key, kind="generate",
                                    params={k: v for k, v in params.items() if k != "request_id"})
        self.queue.put(job["id"])
        return job, True

    def submit_find(self, song_id: str, video: dict | None = None) -> tuple[dict, bool]:
        """Find the song's recording online (or use `video`, one the user picked) and chart it. One job per
        (song, video, engine): asking again returns the job that ran or is running."""
        key = f"find|{song_id}|{(video or {}).get('id') or (video or {}).get('url') or 'best'}|{ENGINE}"
        existing = self.store.job_by_key(key)
        if existing is not None:
            return existing, False
        job = self.store.create_job(song_id=song_id, source_id=None, engine=ENGINE, key=key, kind="find",
                                    params={"video": video} if video else {})
        self.queue.put(job["id"])
        return job, True

    def recover(self) -> None:
        for job in self.store.jobs_with_status("running"):
            if job["attempts"] >= MAX_ATTEMPTS:
                self.store.update_job(job["id"], status="failed", error_code="interrupted",
                                      error="the job was interrupted repeatedly (server restarts) and was stopped",
                                      stages=_close(job["stages"], "failed"))
            else:
                self.store.update_job(job["id"], status="queued", stage=None, stages=[])
        for job in self.store.jobs_with_status("queued"):
            self.queue.put(job["id"])

    def wait(self, job_id: str, timeout: float = 600) -> dict:
        """Block until the job finishes (tests and the CLI)."""
        end = time.time() + timeout
        while time.time() < end:
            job = self.store.get_job(job_id)
            if job["status"] in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(0.2)
        raise TimeoutError(job_id)

    # ---- worker ----------------------------------------------------------
    def _work(self) -> None:
        while True:
            job_id = self.queue.get()
            try:
                self.run(job_id)
            except Exception:  # never let the worker die; run() records failures itself
                log.exception("job %s crashed the worker", job_id)

    def run(self, job_id: str) -> dict:
        job = self.store.get_job(job_id)
        if job is None or job["status"] != "queued":
            return job
        job = self.store.update_job(job_id, status="running", attempts=job["attempts"] + 1, stages=[], error=None,
                                    error_code=None)
        stages: list[dict] = []

        def step(name: str) -> None:
            nonlocal stages
            if self.store.get_job(job_id)["cancel_requested"]:
                raise Cancelled()
            stages = _close(stages, "done")
            stages.append({"name": name, "label": STAGE_LABELS.get(name, name), "status": "running",
                           "started_at": time.time()})
            self.store.update_job(job_id, stage=name, stages=stages)

        try:
            work = {"generate": self._generate, "find": self._find}.get(job["kind"], self._transcribe)
            chart = work(job, step)
        except Cancelled:
            return self.store.update_job(job_id, status="cancelled", stage=None, stages=_close(stages, "cancelled"))
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the job
            code, message = _describe(exc)
            if code == "internal":
                log.error("job %s failed:\n%s", job_id, traceback.format_exc())
            return self.store.update_job(job_id, status="failed", error_code=code, error=message,
                                         stages=_close(stages, "failed"))
        return self.store.update_job(job_id, status="succeeded", stage=None, chart_id=chart["id"],
                                     stages=_close(stages, "done"))

    def _find(self, job: dict, step) -> dict:
        from . import online

        song = self.store.get_song(job["song_id"])
        step("search")
        if not online.status()["available"]:
            raise FetchError(online.status()["detail"])
        picked = (job["params"] or {}).get("video")
        if picked:
            video = online.chosen(picked)
        else:
            found = online.candidates(song)
            if not found:
                raise FetchError(f"YouTube found nothing for “{online.search_query(song)}”; pick a video "
                                 f"yourself or upload a recording")
            video = found[0]
        step("download")
        source = online.fetch_source(self.store, song, video)
        job = self.store.update_job(job["id"], source_id=source["id"])
        return self._transcribe(job, step, song=song, source=source)

    def _transcribe(self, job: dict, step, *, song: dict | None = None, source: dict | None = None) -> dict:
        from ..audio.transcribe import TranscribeOptions, load_audio, transcribe_audio

        song = song or self.store.get_song(job["song_id"])
        source = source or self.store.get_source(job["source_id"])
        step("prepare")
        wav = Path(source["path"])
        if not wav.is_file():
            raise AudioError("source_missing", "the prepared audio for this source is missing; upload it again")
        y = load_audio(wav)
        score = transcribe_audio(y, TranscribeOptions(), title=song["title"], progress=step)
        score.artist = song["artist"]
        score.rights = source["rights"]
        video = source["info"].get("video") if source["kind"] == "video" else None
        score.source = (f"YouTube: {video['title']} <{video['url']}>" if video
                        else f"{source['kind']} {source['original_name'] or ''}".strip())
        score.transcriber = "Drum Agent (automatic transcription)"
        return self._save_chart(song, score, step, job=job, source=source,
                                audio_duration=source["info"].get("duration_s"))

    def _generate(self, job: dict, step) -> dict:
        from ..generate import generate
        from .beats import interpret_request
        params = job["params"]
        song = self.store.get_song(job["song_id"])
        step("interpret")
        spec, notes, info = interpret_request(params.get("prompt", ""), params.get("settings") or {},
                                              seed=params.get("seed"))
        step("arrange")
        score = generate(spec)
        if params.get("title"):
            score.title = params["title"]
        elif song["title"] == PROVISIONAL_TITLE:
            song = self.store.rename(song["id"], score.title)
        score.title = song["title"]
        gen = score.analysis["generator"]
        gen["notes"], gen["interpreter"], gen["prompt"] = notes, info, params.get("prompt", "")
        return self._save_chart(song, score, step, origin="generated", job=job, note="Generated from the description")

    def _save_chart(self, song: dict, score: Score, step, *, origin: str = "transcription", job: dict | None = None,
                    source: dict | None = None, audio_duration: float | None = None,
                    parent_id: str | None = None, note: str | None = None) -> dict:
        step("validate")
        validation = validate_score(score, DEFAULT_KIT, audio_duration)
        if not validation.ok:
            failed = "; ".join(c.detail for c in validation.checks if not c.ok and c.severity == "error")
            raise ChartInvalid(f"the chart is not valid: {failed}")
        chart_id = new_id("ch")
        out = self.store.chart_dir(chart_id)
        try:
            step("render")
            report = export_all(score, out, "chart", DEFAULT_KIT, ExportOptions(png=False))
            step("view")
            view = build_view(score, report.plan, out / "chart.ly", out / "view")
            step("save")
            (out / "view.json").write_text(_json(view), encoding="utf-8")
            status = chart_status(validation, report.rendering_ok)
            summary = chart_summary(score, report, view)
            (out / "validation.json").write_text(_json(validation.to_dict()), encoding="utf-8")
            return self.store.add_chart(chart_id=chart_id, song_id=song["id"], status=status, origin=origin,
                                        bars=len(score.measures), validation=validation.to_dict(), summary=summary,
                                        job_id=job["id"] if job else None,
                                        source_id=source["id"] if source else None, parent_id=parent_id, note=note)
        except BaseException:
            shutil.rmtree(out, ignore_errors=True)  # no half-written chart versions
            raise


class ChartInvalid(ValueError):
    pass


def chart_summary(score: Score, report, view: dict) -> dict:
    a = score.analysis or {}
    return {
        "title": score.title, "artist": score.artist, "bars": len(score.measures),
        "printed_bars": len(view["bars"]), "pages": len(view["pages"]),
        "tempo": score.initial_tempo, "time_signature": str(score.measures[0].time_sig),
        "tempo_estimate": a.get("tempo_estimate"), "meter": a.get("meter"), "feel": a.get("feel"),
        "detected_onsets": a.get("detected_onsets"), "instrument_counts": a.get("instrument_counts"),
        "detector": a.get("detector"), "notes": a.get("notes", []),
        "sections": [s["name"] for s in view["sections"]],
        "uncertain_printed_bars": report.uncertain_bars, "uncertain_score_bars": report.uncertain_score_bars,
        "score_status": score.status, "chart_type": score.chart_type, "rights": score.rights,
        "lilypond": report.lilypond_version, "rendering_ok": report.rendering_ok,
        "comparisons": [{"name": c.name, "ok": c.ok} for c in report.comparisons],
        "playability": report.playability, "warnings": report.warnings,
        "engine": GENERATOR if score.chart_type == "original_beat" else ENGINE,
        "generator": {k: a["generator"].get(k) for k in ("spec", "notes", "interpreter", "prompt", "sections", "fills")}
        if a.get("generator") else None,
    }


def _close(stages: list[dict], status: str) -> list[dict]:
    out = [dict(s) for s in stages]
    if out and out[-1]["status"] == "running":
        out[-1]["status"] = status
        out[-1]["ended_at"] = time.time()
    return out


def _describe(exc: BaseException) -> tuple[str, str]:
    """A stable error code and a message for people (no stack traces or paths)."""
    if isinstance(exc, AudioError):
        return exc.code, str(exc)
    if isinstance(exc, FetchError):
        return "not_found" if "found nothing" in str(exc) else "download_failed", str(exc)[:600]
    if isinstance(exc, ChartInvalid):
        return "invalid_chart", str(exc)
    if isinstance(exc, (RenderError, ExportError)):
        return "render_failed", "engraving failed: " + str(exc).split("\n")[0][:300]
    if isinstance(exc, ValueError) and "no drum strokes" in str(exc):
        return "no_drums", "no drum strokes were detected in this recording"
    return "internal", f"the transcription failed unexpectedly ({type(exc).__name__}); see the server log"


def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=1) + "\n"
