"""Export orchestration: Score -> .ly/.pdf/.png/.musicxml/.mid/.json + report.

`export_all` engraves through LilyPond, writes MusicXML and MIDI, then reads
all of them back and checks them against the IR. The report separates
*rendering correctness* (formats agree, schema valid, no LilyPond warnings)
from *transcription confidence* (uncertain bars, detection statistics), which
only a listening check can settle.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .kit import DEFAULT_KIT, Kit
from .layout import plan_layout
from .model import CHART_TYPES, STATUSES, Score
from .verify import Comparison, validate_musicxml, verify_exports


@dataclass
class ExportOptions:
    formats: tuple[str, ...] = ("pdf", "musicxml", "midi", "json")
    paper: str = "letter"
    staff_size: float = 20
    repeats: str = "auto"
    bars_per_line: float = 4.0
    legend: bool = True
    midi_timing: str = "quantized"
    png: bool = True
    verify: bool = True


@dataclass
class ExportReport:
    files: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    musicxml_errors: list[str] = field(default_factory=list)
    uncertain_bars: list[int] = field(default_factory=list)  # printed bar numbers
    uncertain_score_bars: list[int] = field(default_factory=list)  # 1-based bar numbers in score.json (for `edit`)
    lilypond_version: str = ""
    notes: list[str] = field(default_factory=list)  # layout decisions worth knowing, not problems

    @property
    def rendering_ok(self) -> bool:
        return all(c.ok for c in self.comparisons) and not self.musicxml_errors


class ExportError(RuntimeError):
    pass


def export_all(score: Score, out_dir: str | Path, stem: str = "score", kit: Kit = DEFAULT_KIT,
               options: ExportOptions | None = None) -> ExportReport:
    from .export.lilypond import to_lilypond
    from .export.midi import write_midi
    from .export.musicxml import to_musicxml
    from .export.render import render

    opts = options or ExportOptions()
    out = Path(out_dir).resolve()  # report every file with the same, absolute, kind of path
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()
    report.warnings += score.validate(kit)
    plan = plan_layout(score, repeats=opts.repeats, bars_per_line=opts.bars_per_line)
    report.uncertain_bars = [plan.printed_numbers[i] for i, m in enumerate(score.measures) if m.uncertain]
    report.uncertain_score_bars = [i + 1 for i, m in enumerate(score.measures) if m.uncertain]

    if "json" in opts.formats:
        p = out / f"{stem}.json"
        score.save(p)
        report.files["json"] = p

    ly_midi = None
    if "pdf" in opts.formats or "ly" in opts.formats:
        ly = to_lilypond(score, kit, plan, paper_size=opts.paper, staff_size=opts.staff_size,
                         with_legend=opts.legend)
        if "pdf" in opts.formats:
            res = render(ly, out, stem, png=True)
            fitted = _fit_fewer_pages(score, kit, plan, opts, res, out, stem)
            if fitted is not None:
                res = fitted
                report.notes.append(f"Fitted onto {len(res.pngs)} page(s) instead of {len(res.pngs) + 1} "
                                    "(the last page held only a sliver); vertical spacing slightly compressed.")
            if not opts.png:
                for p in res.pngs:
                    p.unlink()
                res.pngs = []
            report.files.update({"ly": res.ly, "pdf": res.pdf})
            for k, png in enumerate(res.pngs, 1):
                report.files[f"png{k}"] = png
            report.warnings += [f"LilyPond: {w}" for w in res.warnings]
            report.lilypond_version = res.version
            ly_midi = res.midi
            if res.midi is not None:
                report.files["engraved_midi"] = res.midi
        else:
            p = out / f"{stem}.ly"
            p.write_text(ly)
            report.files["ly"] = p

    xml_path = None
    if "musicxml" in opts.formats:
        xml_path = out / f"{stem}.musicxml"
        xml_path.write_text(to_musicxml(score, kit, plan))
        report.files["musicxml"] = xml_path
        if opts.verify:
            report.musicxml_errors = validate_musicxml(xml_path)

    midi_path = None
    if "midi" in opts.formats:
        midi_path = write_midi(score, out / f"{stem}.mid", kit, timing="quantized")
        report.files["midi"] = midi_path
        if opts.midi_timing == "performed":
            report.files["midi_performed"] = write_midi(score, out / f"{stem}.performed.mid", kit, timing="performed")

    if opts.verify:
        report.comparisons = verify_exports(score, ly_midi, xml_path, midi_path, kit)
    report_path = out / f"{stem}.report.md"
    report_path.write_text(render_report(score, report))
    report.files["report"] = report_path
    (out / f"{stem}.report.json").write_text(json.dumps(report_json(score, report), indent=1) + "\n")
    report.files["report_json"] = out / f"{stem}.report.json"
    if opts.verify and not report.rendering_ok:
        raise ExportError("exports disagree with the IR or MusicXML is invalid:\n" + render_report(score, report))
    return report


# A last page whose content ends above this fraction of the page height holds
# only a system or two; try to pull it onto the previous page.
LIGHT_LAST_PAGE = 0.30
# Accept the fitted version only if LilyPond had to squeeze this little
# (staff-spaces in total); more than that crowds the systems.
MAX_COMPRESSION = 6.0


def _page_fill(png: Path) -> float | None:
    """Fraction of the page height down to the lowest ink (None if Pillow is missing)."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    ink = np.asarray(Image.open(png).convert("L")) < 128
    rows = np.nonzero(ink.any(axis=1))[0]
    return float(rows[-1] + 1) / ink.shape[0] if len(rows) else 0.0


def _compression(warnings: list[str]) -> float:
    total = 0.0
    for w in warnings:
        m = re.search(r"compressing over-full page by ([\d.]+) staff-spaces", w)
        if m:
            total += float(m.group(1))
    return total


def _fit_fewer_pages(score, kit, plan, opts, res, out: Path, stem: str):
    """Avoid a near-empty last page by asking LilyPond for one page fewer.

    The attempt is rendered in a scratch directory and only replaces the
    original when it really has fewer pages and needed little compression.
    """
    from .export.lilypond import to_lilypond
    from .export.render import RenderError, render

    n = len(res.pngs)
    if n < 2:
        return None
    fill = _page_fill(res.pngs[-1])
    if fill is None or fill > LIGHT_LAST_PAGE:
        return None
    ly = to_lilypond(score, kit, plan, paper_size=opts.paper, staff_size=opts.staff_size,
                     with_legend=opts.legend, page_count=n - 1)
    with tempfile.TemporaryDirectory(dir=out) as td:
        try:
            trial = render(ly, td, stem, png=True)
        except RenderError:
            return None
        if len(trial.pngs) != n - 1 or _compression(trial.warnings) > MAX_COMPRESSION:
            return None
    fitted = render(ly, out, stem, png=True)
    fitted.warnings = [w for w in fitted.warnings
                       if "compressing over-full page" not in w and "has been compressed" not in w]
    return fitted


def report_json(score: Score, report: ExportReport) -> dict:
    return {
        "title": score.title,
        "chart_type": score.chart_type,
        "status": score.status,
        "bars": len(score.measures),
        "events": len(score.event_list()),
        "files": {k: str(v) for k, v in report.files.items()},
        "rendering_ok": report.rendering_ok,
        "lilypond_version": report.lilypond_version,
        "comparisons": [{"name": c.name, "ok": c.ok, "expected": c.expected, "found": c.found}
                        for c in report.comparisons],
        "musicxml_errors": report.musicxml_errors,
        "uncertain_bars": report.uncertain_bars,
        "uncertain_score_bars": report.uncertain_score_bars,
        "warnings": report.warnings,
        "layout_notes": report.notes,
        "analysis": score.analysis,
    }


STATUS_REPORT = {
    "verified": "Verified by a human",
    "entered": "Entered as a chart spec (written by hand or from a description)",
    "unverified_auto": "Automatic transcription, unverified",
    "unverified_import": "Imported from MIDI, unverified",
    "draft": "Draft",
}
CONFIDENCE_TEXT = {
    "verified": "A human checked this chart against the recording.",
    "entered": "Written as a chart spec: nothing was detected automatically, and nobody has checked it "
               "against a recording. It shows what was written, not necessarily what is played.",
    "unverified_import": "The strokes come from the MIDI file, but the barlines (pickup, meter changes) and the "
                         "quantization were worked out automatically. Check that downbeats, crashes and meter "
                         "changes sit where they belong before relying on it.",
    "unverified_auto": "This chart was produced automatically. A valid PDF does **not** mean the notes are right; "
                       "listen along before relying on it.",
    "draft": "Draft: not finished or not checked.",
}


def render_report(score: Score, report: ExportReport) -> str:
    lines = [f"# Drum chart report: {score.title}", ""]
    lines.append(f"* Chart type: **{CHART_TYPES[score.chart_type]}**")
    lines.append(f"* Status: **{STATUS_REPORT.get(score.status, score.status)}**")
    if score.rights:
        lines.append(f"* Rights basis: {score.rights}")
    if score.source:
        lines.append(f"* Source: {score.source}")
    lines.append(f"* Bars: {len(score.measures)}; notated strokes: {len(score.event_list())}")
    lines.append("")
    lines.append("## Rendering correctness (automated)")
    if report.lilypond_version:
        lines.append(f"* Engraved with LilyPond {report.lilypond_version}")
    for c in report.comparisons:
        lines.append(f"* {c.summary()}")
    if report.files.get("musicxml"):
        lines.append(f"* MusicXML 4.0 schema: {'valid' if not report.musicxml_errors else 'INVALID'}")
        for e in report.musicxml_errors[:10]:
            lines.append(f"  * {e}")
    lines.append("")
    lines.append("## Transcription confidence")
    lines.append("* " + CONFIDENCE_TEXT.get(score.status, CONFIDENCE_TEXT["unverified_auto"]))
    if report.uncertain_bars:
        pairs = ", ".join(f"{p} ({s})" for p, s in zip(report.uncertain_bars, report.uncertain_score_bars))
        lines.append(f"* Bars needing verification, marked (?) in the PDF: {pairs}")
        lines.append("  (printed bar number, then the score.json bar number that `python -m drum_agent edit` uses)")
        reasons = []
        for i, m in enumerate(score.measures):
            if m.uncertain and m.notes:
                reasons.append(f"  * score bar {i + 1}: {'; '.join(m.notes)}")
        lines += reasons[:40]
    a = score.analysis or {}
    for key in ("tempo_estimate", "meter", "feel", "pickup", "detected_onsets", "instrument_counts",
                "low_confidence_hits", "dropped_hits", "sections", "notes"):
        if key in a:
            lines.append(f"* {key.replace('_', ' ')}: {a[key]}")
    if report.notes:
        lines.append("")
        lines.append("## Layout notes")
        lines += [f"* {n}" for n in report.notes]
    if report.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines += [f"* {w}" for w in report.warnings]
    lines.append("")
    lines.append("## Files")
    lines += [f"* {k}: `{v.name}`" for k, v in report.files.items() if k != "report"]
    return "\n".join(lines) + "\n"
