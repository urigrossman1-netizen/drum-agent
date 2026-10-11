"""Export orchestration: Score -> .ly/.pdf/.png/.musicxml/.mid/.json + report.

`export_all` engraves through LilyPond, writes MusicXML and MIDI, then reads
all of them back and checks them against the IR. The report separates
*rendering correctness* (formats agree, schema valid, no LilyPond warnings)
from *transcription confidence* (uncertain bars, detection statistics), which
only a listening check can settle.
"""

from __future__ import annotations

import json
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
    lilypond_version: str = ""

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
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()
    report.warnings += score.validate(kit)
    plan = plan_layout(score, repeats=opts.repeats, bars_per_line=opts.bars_per_line)
    report.uncertain_bars = [plan.printed_numbers[i] for i, m in enumerate(score.measures) if m.uncertain]

    if "json" in opts.formats:
        p = out / f"{stem}.json"
        score.save(p)
        report.files["json"] = p

    ly_midi = None
    if "pdf" in opts.formats or "ly" in opts.formats:
        ly = to_lilypond(score, kit, plan, paper_size=opts.paper, staff_size=opts.staff_size,
                         with_legend=opts.legend)
        if "pdf" in opts.formats:
            res = render(ly, out, stem, png=opts.png)
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
        "warnings": report.warnings,
        "analysis": score.analysis,
    }


def render_report(score: Score, report: ExportReport) -> str:
    lines = [f"# Drum chart report: {score.title}", ""]
    lines.append(f"* Chart type: **{CHART_TYPES[score.chart_type]}**")
    status = STATUSES.get(score.status) or "Verified by a human"
    lines.append(f"* Status: **{status}**")
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
    if score.status == "verified":
        lines.append("* Chart entered or verified by a human; no automatic detection involved.")
    else:
        lines.append("* This chart was produced automatically. A valid PDF does **not** mean the notes are right; "
                     "listen along before relying on it.")
    if report.uncertain_bars:
        lines.append(f"* Bars needing verification (printed bar numbers, marked (?) in the PDF): "
                     f"{', '.join(str(b) for b in report.uncertain_bars)}")
    a = score.analysis or {}
    for key in ("tempo_estimate", "meter", "feel", "detected_onsets", "instrument_counts",
                "low_confidence_hits", "dropped_hits", "sections", "notes"):
        if key in a:
            lines.append(f"* {key.replace('_', ' ')}: {a[key]}")
    if report.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines += [f"* {w}" for w in report.warnings]
    lines.append("")
    lines.append("## Files")
    lines += [f"* {k}: `{v.name}`" for k, v in report.files.items() if k != "report"]
    return "\n".join(lines) + "\n"
