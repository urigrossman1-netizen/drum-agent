"""Command-line interface: `python -m drum_agent <command>` (or `drum-agent`)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

from . import __version__
from .kit import DEFAULT_KIT, Kit
from .model import RIGHTS, STATUSES


def _kit(args) -> Kit:
    return Kit.from_json(args.kit) if getattr(args, "kit", None) else DEFAULT_KIT


def _export_opts(args):
    from .pipeline import ExportOptions
    return ExportOptions(
        formats=tuple(f.strip() for f in args.formats.split(",")),
        paper=args.paper,
        staff_size=args.staff_size,
        repeats=args.repeats,
        bars_per_line=args.bars_per_line,
        legend=not args.no_legend,
        midi_timing=args.midi_timing,
    )


def _add_export_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-o", "--out", required=True, help="output directory")
    p.add_argument("--stem", default=None, help="output file name stem (default: from input)")
    p.add_argument("--formats", default="pdf,musicxml,midi,json",
                   help="comma list of pdf,ly,musicxml,midi,json (default: all)")
    p.add_argument("--paper", default="letter", choices=["letter", "a4"])
    p.add_argument("--staff-size", type=float, default=20)
    p.add_argument("--repeats", default="auto", choices=["auto", "percent", "none"],
                   help="compress exactly repeated bars (auto), simile marks only, or write everything out")
    p.add_argument("--bars-per-line", type=float, default=4.0)
    p.add_argument("--no-legend", action="store_true", help="omit the Drum Key")
    p.add_argument("--midi-timing", default="quantized", choices=["quantized", "performed"],
                   help="also write a .performed.mid with the original timing when 'performed'")
    p.add_argument("--kit", help="JSON kit override file (see drum_agent/kit.py)")


def _print_report(report, out: Path) -> int:
    print(f"Wrote {len(report.files)} files to {out}:")
    for k, v in report.files.items():
        print(f"  {k:15s} {v}")
    for c in report.comparisons:
        print(f"  check: {c.summary()}")
    if report.musicxml_errors:
        print(f"  MusicXML schema errors: {report.musicxml_errors[:5]}")
    if report.uncertain_bars:
        print(f"  bars to verify by ear (printed numbers): {report.uncertain_bars}")
        print(f"  ... as score.json bar numbers (for `edit`): {report.uncertain_score_bars}")
    for w in report.warnings:
        print(f"  warning: {w}")
    return 0 if report.rendering_ok else 2


# Every file export_all can write for a stem (plus "<stem>-page<N>.png").
_OUTPUT_SUFFIXES = (".ly", ".pdf", ".png", ".midi", ".log", ".musicxml", ".mid", ".performed.mid",
                    ".json", ".report.md", ".report.json")


def _channel(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if not 1 <= n <= 16:
        raise argparse.ArgumentTypeError(f"MIDI channels are 1-16, got {text!r}")
    return n


def _is_score_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "measures" in data


def _guard_input(input_path: str, out_dir: str, stem: str) -> None:
    """Refuse to write an output over the input (a MIDI take, a chart spec): the user's
    file would be replaced by our export. Re-rendering a score.json in place is the
    edit-then-render loop and rewrites the same score, so it is allowed."""
    inp = Path(input_path).resolve()
    if inp.parent != Path(out_dir).resolve():
        return
    names = {stem + suffix for suffix in _OUTPUT_SUFFIXES}
    page = re.fullmatch(re.escape(stem) + r"-page\d+\.png", inp.name)
    if inp.name not in names and not page:
        return
    if inp.name == f"{stem}.json" and _is_score_json(inp):
        return
    raise SystemExit(f"error: this would overwrite the input {inp} with an export; "
                     f"write to another folder (-o) or pick another name (--stem)")


def cmd_render(args) -> int:
    from .charts import load_any
    from .pipeline import export_all
    kit = _kit(args)
    score = load_any(args.input, kit)
    if args.title:
        score.title = args.title
    stem = args.stem or Path(args.input).stem
    _guard_input(args.input, args.out, stem)
    report = export_all(score, args.out, stem, kit, _export_opts(args))
    return _print_report(report, Path(args.out))


def cmd_midi(args) -> int:
    from .io_midi import read_midi
    from .pipeline import export_all
    from .quantize import QuantizeOptions
    kit = _kit(args)
    opts = QuantizeOptions(feel=args.feel, allow_32nds=not args.no_32nds)
    pickup = args.pickup
    if pickup != "auto":
        try:
            pickup = Fraction(pickup)
        except (ValueError, ZeroDivisionError):
            raise SystemExit(f"--pickup {args.pickup!r}: use a length in whole notes like 1/4, 0, or auto") from None
    stem = args.stem or Path(args.input).stem
    _guard_input(args.input, args.out, stem)
    score, rep = read_midi(args.input, channel=(args.channel - 1) if args.channel else None,
                           options=opts, title=args.title, pickup=pickup)
    if rep.pickup:
        print(f"pickup: {rep.pickup} whole note(s) ({rep.pickup_reason})")
    for w in rep.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.artist:
        score.artist = args.artist
    if args.transcriber:
        score.transcriber = args.transcriber
    score.rights = args.rights
    _apply_sections(score, args.sections)
    if rep.unmapped:
        print(f"warning: unmapped MIDI notes skipped: {rep.unmapped}", file=sys.stderr)
    report = export_all(score, args.out, stem, kit, _export_opts(args))
    return _print_report(report, Path(args.out))


def _apply_sections(score, spec: str | None) -> None:
    """--sections "Intro:1,Verse 1:5,Chorus:13" (label:first bar, 1-based performance bars)."""
    if not spec:
        return
    from .edit import EditError, set_sections
    try:
        set_sections(score, spec)
    except EditError as exc:
        raise SystemExit(f"--sections: {exc}") from None


def cmd_transcribe(args) -> int:
    from .rights import require_rights
    require_rights(args.rights, args.input)  # before touching the audio
    _guard_input(args.input, args.out, args.stem or Path(args.input).stem)
    from .audio.transcribe import TranscribeOptions, transcribe_file
    from .pipeline import export_all
    kit = _kit(args)
    topts = TranscribeOptions(
        bpm=args.bpm, time_signature=args.time_signature, downbeat=args.downbeat,
        feel=args.feel, drums_only=args.drums_only, sensitivity=args.sensitivity,
        allow_32nds=not args.no_32nds, start=args.start, end=args.end,
    )
    score = transcribe_file(args.input, topts)
    score.title = args.title or score.title
    score.artist = args.artist
    score.transcriber = args.transcriber or "Drum Agent (automatic)"
    score.rights = args.rights
    if args.chart_type:
        score.chart_type = args.chart_type
    _apply_sections(score, args.sections)
    stem = args.stem or Path(args.input).stem
    report = export_all(score, args.out, stem, kit, _export_opts(args))
    return _print_report(report, Path(args.out))


def cmd_analyze(args) -> int:
    from .audio.transcribe import analyze_file
    info = analyze_file(args.input, bpm=args.bpm, time_signature=args.time_signature)
    print(json.dumps(info, indent=1))
    return 0


def cmd_synth(args) -> int:
    from .charts import load_any
    from .synth import synthesize
    score = load_any(args.input)
    path = synthesize(score, args.out, method=args.method, kit_program=args.kit_program,
                      accompaniment=args.accompaniment, humanize_ms=args.humanize_ms, seed=args.seed)
    print(path)
    return 0


def cmd_evaluate(args) -> int:
    from .charts import load_any
    from .evaluate import evaluate_scores, format_eval, format_notation
    ref = load_any(args.reference)
    est = load_any(args.estimate)
    res = evaluate_scores(ref, est, tolerance=args.tolerance)
    print(format_eval(res))
    print(format_notation(ref, est))
    return 0


def cmd_verify(args) -> int:
    from .charts import load_any
    from .verify import validate_musicxml, verify_exports
    kit = _kit(args)
    score = load_any(args.score, kit)
    files = {"ly_midi": args.ly_midi, "musicxml": args.musicxml, "midi": args.midi}
    if not any(files.values()):
        # Default: the files written next to the score with the same stem.
        base = Path(args.score)
        guess = {"ly_midi": base.with_suffix(".midi"), "musicxml": base.with_suffix(".musicxml"),
                 "midi": base.with_suffix(".mid")}
        files = {k: str(p) for k, p in guess.items() if p.exists()}
        if not files:
            print(f"nothing to verify: no {base.stem}.midi/.musicxml/.mid next to {base}; "
                  f"pass --musicxml/--midi/--ly-midi", file=sys.stderr)
            return 2
        print("verifying", ", ".join(sorted(files.values())))
    comps = verify_exports(score, Path(files["ly_midi"]) if files.get("ly_midi") else None,
                           Path(files["musicxml"]) if files.get("musicxml") else None,
                           Path(files["midi"]) if files.get("midi") else None, kit)
    args.musicxml = files.get("musicxml")
    ok = True
    for c in comps:
        print(c.summary())
        ok &= c.ok
    if args.musicxml:
        errs = validate_musicxml(args.musicxml)
        print("MusicXML schema:", "valid" if not errs else errs[:5])
        ok &= not errs
    return 0 if ok else 2


def cmd_edit(args) -> int:
    """Apply corrections to a score.json; optionally re-render."""
    from . import edit as E
    from .charts import load_any
    kit = _kit(args)
    src = Path(args.score)
    out = Path(args.output or args.score)
    if out.suffix.lower() != ".json":
        raise SystemExit(f"error: the edited score is saved as JSON; {out.name} is not a .json file "
                         f"(use --output name.json)")
    if out.resolve() == src.resolve() and not _is_score_json(src):
        raise SystemExit(f"error: {src.name} is a chart spec, not a score.json; editing it in place would "
                         f"replace it. Edit the spec text, edit the score.json that render wrote, or "
                         f"pass --output name.json")
    score = load_any(args.score, kit)
    log = []
    for spec in args.relabel or []:
        n = E.relabel(score, spec, args.bars, kit)
        log.append(f"relabel {spec} in bars {args.bars or 'all'}: {n} hits")
    for spec in args.delete or []:
        E.delete(score, spec, kit)
        log.append(f"deleted {spec}")
    for spec in args.add or []:
        E.add(score, spec, kit)
        log.append(f"added {spec}")
    for spec in args.set or []:
        E.set_flags(score, spec, kit)
        log.append(f"set {spec}")
    if args.sections:
        E.set_sections(score, args.sections)
        log.append(f"sections {args.sections}")
    for spec in args.tempo or []:
        E.set_tempo(score, spec)
        log.append(f"tempo {spec}")
    if args.verified is not None:
        n = E.mark_verified(score, args.verified or None)
        log.append(f"marked {n} flagged bar(s) verified")
    for name in ("title", "artist", "transcriber", "chart_type", "status"):
        if getattr(args, name, None):
            setattr(score, name, getattr(args, name))
            log.append(f"{name} = {getattr(args, name)}")
    score.validate(kit)
    score.save(out)
    for line in log:
        print(line)
    print(f"saved {out}")
    if args.render:
        from .pipeline import ExportOptions, export_all
        report = export_all(score, args.render, out.stem, kit, ExportOptions())
        return _print_report(report, Path(args.render))
    return 0


def cmd_doctor(args) -> int:
    from .doctor import run_doctor
    return run_doctor()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="drum-agent", description="Drum transcription and drum-chart engraving.")
    ap.add_argument("--version", action="version", version=f"drum-agent {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("render", help="engrave a chart spec (.yaml/.json) or IR score (.json)")
    p.add_argument("input")
    p.add_argument("--title")
    _add_export_args(p)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("midi", help="MIDI drum track -> score")
    p.add_argument("input")
    p.add_argument("--channel", type=_channel, help="1-based MIDI channel, 1-16 (default 10)")
    p.add_argument("--title")
    p.add_argument("--artist")
    p.add_argument("--transcriber")
    p.add_argument("--rights", choices=sorted(RIGHTS), default=None)
    p.add_argument("--feel", default="auto", choices=["auto", "straight", "swing", "triplet"])
    p.add_argument("--no-32nds", action="store_true")
    p.add_argument("--sections", help='e.g. "Intro:1,Verse:5,Chorus:13" (label:first bar); '
                   "default: the file's markers")
    p.add_argument("--pickup", default="auto",
                   help='anacrusis length in whole notes ("1/4" = one beat in 4/4), "0" for none, '
                        'or "auto" (default: inferred from the file\'s meter changes and markers)')
    _add_export_args(p)
    p.set_defaults(func=cmd_midi)

    p = sub.add_parser("transcribe", help="audio recording -> drum score (requires --rights)")
    p.add_argument("input")
    p.add_argument("--rights", required=False, choices=sorted(RIGHTS),
                   help="basis for full transcription: own, permission, licensed, public_domain, original")
    p.add_argument("--title")
    p.add_argument("--artist")
    p.add_argument("--transcriber")
    p.add_argument("--bpm", type=float, help="tempo hint (quarter notes per minute)")
    p.add_argument("--time-signature", help="e.g. 4/4, 3/4, 6/8, 12/8 (default: detect)")
    p.add_argument("--downbeat", type=float, help="time in seconds of a downbeat (beat 1)")
    p.add_argument("--feel", default="auto", choices=["auto", "straight", "swing", "triplet"])
    p.add_argument("--drums-only", action="store_true", help="input is an isolated drum track/stem")
    p.add_argument("--sensitivity", type=float, default=1.0, help=">1 finds more (softer) strokes, <1 fewer")
    p.add_argument("--no-32nds", action="store_true")
    p.add_argument("--start", type=float, help="start time in seconds")
    p.add_argument("--end", type=float, help="end time in seconds")
    p.add_argument("--sections", help='e.g. "Intro:1,Verse:5,Chorus:13" (label:first bar)')
    p.add_argument("--chart-type", choices=["full_transcription", "performance_chart"])
    _add_export_args(p)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("analyze", help="high-level analysis only (tempo, meter, sections); no notation")
    p.add_argument("input")
    p.add_argument("--bpm", type=float)
    p.add_argument("--time-signature")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("synth", help="render a chart to audio (test fixtures)")
    p.add_argument("input")
    p.add_argument("-o", "--out", required=True, help="output .wav")
    p.add_argument("--method", default="fluidsynth", choices=["fluidsynth", "numpy"])
    p.add_argument("--kit-program", type=int, default=0, help="GM drum kit program (0 Standard, 8 Room, 16 Power, 32 Jazz, 40 Brush)")
    p.add_argument("--accompaniment", action="store_true", help="add synthetic bass/keys to emulate a band mix")
    p.add_argument("--humanize-ms", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("evaluate", help="compare an estimated score with a reference (onset and notation accuracy)")
    p.add_argument("reference")
    p.add_argument("estimate")
    p.add_argument("--tolerance", type=float, default=0.05, help="seconds")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("verify", help="check exported files against a score (default: the files next to it)")
    p.add_argument("score")
    p.add_argument("--musicxml")
    p.add_argument("--midi")
    p.add_argument("--ly-midi", help="MIDI written by LilyPond from the engraved .ly")
    p.add_argument("--kit", help="the JSON kit override the files were rendered with")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("edit", help="correct a score.json (relabel, add, delete, sections, verify)")
    p.add_argument("score", help="IR score .json (as written by transcribe/midi/render)")
    p.add_argument("--relabel", action="append", help="FROM=TO, e.g. ride=hihat (use --bars to limit)")
    p.add_argument("--bars", help="bar range for --relabel, e.g. 9-16 (1-based performance bars)")
    p.add_argument("--delete", action="append", help="BAR:POS:INST, e.g. 12:7/8:kick")
    p.add_argument("--add", action="append", help="BAR:POS:INST[:flags], e.g. 12:3/8:snare:ghost")
    p.add_argument("--set", action="append", help="BAR:POS:INST:flags (replaces flags), e.g. 5:1/4:snare:accent")
    p.add_argument("--sections", help='"Intro:1,Verse:5,Chorus:13"')
    p.add_argument("--tempo", action="append", help="BAR:BPM, e.g. 29:100")
    p.add_argument("--verified", nargs="?", const="", default=None,
                   help="clear review flags (optionally only BARS, e.g. 9-16) after checking by ear")
    p.add_argument("--title")
    p.add_argument("--artist")
    p.add_argument("--transcriber")
    p.add_argument("--chart-type", dest="chart_type", choices=["full_transcription", "performance_chart", "pattern_study"])
    p.add_argument("--status", choices=sorted(STATUSES))
    p.add_argument("-o", "--output", help="write to this .json instead of overwriting")
    p.add_argument("--render", metavar="OUT_DIR", help="re-render all formats after editing")
    p.add_argument("--kit", help="JSON kit override file")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("doctor", help="check dependencies")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # report cleanly; full trace with DRUM_AGENT_DEBUG=1
        import os
        if os.environ.get("DRUM_AGENT_DEBUG"):
            raise
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
