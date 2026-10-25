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
from ..validate import chart_status, validate_score
from .store import Store, new_id
from .view import build_view

log = logging.getLogger("drum_agent.web")

ENGINE = f"drum-agent {__version__} onset-classifier"
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
STAGE_LABELS = dict(STAGES)
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
        new, _ = self.submit(job["song_id"], job["source_id"])
        return new

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
            chart = self._transcribe(job, step)
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

    def _transcribe(self, job: dict, step) -> dict:
        from ..audio.transcribe import TranscribeOptions, load_audio, transcribe_audio

        song = self.store.get_song(job["song_id"])
        source = self.store.get_source(job["source_id"])
        step("prepare")
        wav = Path(source["path"])
        if not wav.is_file():
            raise AudioError("source_missing", "the prepared audio for this source is missing; upload it again")
        y = load_audio(wav)
        score = transcribe_audio(y, TranscribeOptions(), title=song["title"], progress=step)
        score.artist = song["artist"]
        score.rights = source["rights"]
        score.source = f"{source['kind']} {source['original_name'] or ''}".strip()
        score.transcriber = "Drum Agent (automatic transcription)"
        return self._save_chart(song, score, step, job=job, source=source,
                                audio_duration=source["info"].get("duration_s"))

    def _save_chart(self, song: dict, score: Score, step, *, origin: str = "transcription", job: dict | None = None,
                    source: dict | None = None, audio_duration: float | None = None,
                    parent_id: str | None = None) -> dict:
        step("validate")
        validation = validate_score(score, DEFAULT_KIT, audio_duration)
        if not validation.ok:
            failed = "; ".join(c.detail for c in validation.checks if not c.ok and c.severity == "error")
            raise ChartInvalid(f"the transcription did not produce a valid chart: {failed}")
        chart_id = new_id("ch")
        out = self.store.chart_dir(chart_id)
        try:
            step("render")
            report = export_all(score, out, "chart", DEFAULT_KIT, ExportOptions(png=False))
            step("view")
            view = build_view(score, report.plan, out / "chart.ly", out / "view")
            step("save")
            (out / "view.json").write_text(_json(view))
            status = chart_status(validation, report.rendering_ok)
            summary = chart_summary(score, report, view)
            (out / "validation.json").write_text(_json(validation.to_dict()))
            return self.store.add_chart(chart_id=chart_id, song_id=song["id"], status=status, origin=origin,
                                        bars=len(score.measures), validation=validation.to_dict(), summary=summary,
                                        job_id=job["id"] if job else None,
                                        source_id=source["id"] if source else None, parent_id=parent_id)
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
        "playability": report.playability, "warnings": report.warnings, "engine": ENGINE,
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
