"""The on-screen chart: the engraved pages as SVG, plus where every bar sits on them.

The SVG pages are a second LilyPond run of the exact `.ly` file the PDF was engraved
from, with one change: each barline carries its bar number as an SVG attribute
(`output-attributes`). From the barlines and staff lines the page map gives each
engraved bar a box (as fractions of the page), so the browser can jump to a bar,
highlight the bars flagged for review, and follow playback, without re-deriving any
rhythm: the bar boxes come from the engraving, the bar times from the score.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..export.render import RenderError, find_lilypond
from ..layout import LayoutPlan
from ..model import Score

TAG = ("    \\override BarLine.output-attributes = #(lambda (grob) (let ((loc (grob::rhythmic-location grob))) "
       "(list (cons 'class \"bar\") (cons 'data-bar (if (pair? loc) (number->string (car loc)) \"?\")))))\n"
       "    \\override NoteHead.output-attributes = #(lambda (grob) (let* ((loc (grob::rhythmic-location grob)) "
       "(m (if (pair? loc) (cdr loc) #f))) (if m (list (cons 'class \"nh\") (cons 'data-bar (number->string (car loc))) "
       "(cons 'data-pos (string-append (number->string (ly:moment-main-numerator m)) \"/\" "
       "(number->string (ly:moment-main-denominator m))))) '())))\n")
_TRANSLATE = re.compile(r'translate\(([\d.\-]+),\s*([\d.\-]+)\)')
_VIEWBOX = re.compile(r'viewBox="([\d.\-]+) ([\d.\-]+) ([\d.]+) ([\d.]+)"')
_LINE = re.compile(r'<g transform="translate\(([\d.\-]+),\s*([\d.\-]+)\)">\s*<line [^>]*x1="([\d.\-]+)"[^>]*x2="([\d.\-]+)"')
STAFF_HALF = 2.0  # half the staff height in staff spaces (the SVG unit at the score's staff size)


def render_svg_pages(ly_path: Path, out_dir: Path, timeout: int = 600) -> list[Path]:
    ly = ly_path.read_text()
    if "    \\Score\n" not in ly:
        raise RenderError("the chart's LilyPond file has no \\Score layout block to tag")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page*.svg"):
        old.unlink()
    src = out_dir / "tagged.ly"
    src.write_text(ly.replace("    \\Score\n", "    \\Score\n" + TAG, 1))
    proc = subprocess.run([find_lilypond(), "-dbackend=svg", "-dno-point-and-click", "-o", str(out_dir / "page"),
                           str(src)], capture_output=True, text=True, timeout=timeout, cwd=out_dir, check=False)
    src.unlink()
    pages = sorted(out_dir.glob("page*.svg"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 1))
    if proc.returncode != 0 or not pages:
        raise RenderError(f"LilyPond could not draw the on-screen pages (exit {proc.returncode})",
                          proc.stderr[-2000:])
    for i, p in enumerate(pages, 1):  # page.svg (one page) or page-1.svg, page-2.svg ...
        p.rename(out_dir / f"page-{i}.svg")
    return [out_dir / f"page-{i}.svg" for i in range(1, len(pages) + 1)]


def _systems(svg: str) -> tuple[tuple[float, float], list[dict]]:
    """Page size (viewBox) and every system on the page: its staff extent and the
    barlines on it, [(x_start, x_end, bar number)] in order."""
    vb = _VIEWBOX.search(svg)
    width, height = float(vb.group(3)), float(vb.group(4))
    bars: list[tuple[float, float, float, int]] = []
    for m in re.finditer(r'<g class="bar" data-bar="(\d+)">(.*?)</g>\s*</g>', svg, re.DOTALL):
        pos = [tuple(map(float, t)) for t in _TRANSLATE.findall(m.group(2))]
        if pos:
            xs, ys = sorted(x for x, _ in pos), sorted(y for _, y in pos)
            bars.append((xs[0], xs[-1], ys[len(ys) // 2], int(m.group(1))))  # (repeat dots sit off centre)
    lines = [(float(ty), float(tx) + float(x1), float(tx) + float(x2)) for tx, ty, x1, x2 in _LINE.findall(svg)]
    systems: dict[float, dict] = {}
    for x0, x1, y, n in bars:
        key = next((k for k in systems if abs(k - y) < 1.0), y)
        sys = systems.setdefault(key, {"y": y, "bars": []})
        sys["bars"].append((x0, x1, n))
    for sys in systems.values():
        y = sys["y"]
        staff = [(a, b) for ly, a, b in lines if y - STAFF_HALF - 0.2 <= ly <= y + STAFF_HALF + 0.2]
        sys["left"] = min((a for a, _ in staff), default=min(b[0] for b in sys["bars"]))
        sys["right"] = max((b for _, b in staff), default=max(b[1] for b in sys["bars"]))
        sys["bars"].sort()
    return (width, height), sorted(systems.values(), key=lambda s: s["y"])


_NOTE = re.compile(r'<g class="nh" data-bar="(\d+)" data-pos="(-?\d+)/(\d+)">\s*<g transform="translate\(([\d.\-]+),\s*([\d.\-]+)\)')


def page_map(pages: list[Path]) -> tuple[list[dict], dict[int, dict]]:
    """Page sizes, and for each engraved bar (LilyPond's internal bar number) its box and
    the x position of each stroke position in it."""
    sizes, boxes = [], {}  # a bar split by a line break (a start-repeat) keeps its wider part
    for page_no, p in enumerate(pages):
        text = p.read_text()
        (w, h), systems = _systems(text)
        notes: dict[int, dict[str, list[float]]] = {}
        for m in _NOTE.finditer(text):
            bar, num, den, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4)), float(m.group(5))
            if num < 0 or not any(abs(y - s["y"]) <= STAFF_HALF + 4 for s in systems):
                continue  # grace notes before the bar, and the Drum Key
            notes.setdefault(bar, {}).setdefault(f"{num}/{den}", []).append(x)
        sizes.append({"file": p.name, "width": w, "height": h})
        for sys in systems:
            marks = sys["bars"]
            # The first bar of a system starts at the staff's left edge unless a barline
            # (a start-repeat) is printed there; each barline then starts the bar it numbers.
            starts: list[tuple[float, int]] = []
            if marks and marks[0][0] - sys["left"] > 3.0:
                starts.append((sys["left"], marks[0][2] - 1))
            starts += [(x1, n) for _, x1, n in marks]
            ends = [x0 for x0, _, _ in marks] + [sys["right"]]
            for k, (x, n) in enumerate(starts):
                end = next((e for e in ends if e > x + 0.5), sys["right"])
                if end - x < 1.0 or n < 0:
                    continue  # a barline at the end of the line starts the next system's bar
                box = {"page": page_no, "x0": x / w, "x1": end / w,
                       "y0": (sys["y"] - STAFF_HALF - 2.5) / h, "y1": (sys["y"] + STAFF_HALF + 2.5) / h}
                old = boxes.get(n)
                if old is None or box["x1"] - box["x0"] > old["x1"] - old["x0"]:
                    xs = notes.get(n, {})
                    box["notes"] = sorted(({"pos": pos, "x": round(sum(v) / len(v) / w, 5)} for pos, v in xs.items()
                                           if x - 1 <= sum(v) / len(v) <= end + 1), key=lambda d: d["x"])
                    boxes[n] = box
    return sizes, boxes


def render_preview(score: Score, out_dir: Path, kit=None) -> dict:
    """The on-screen pages for a working score (no PDF): engraved by LilyPond from the
    same IR, through the same layout plan the export uses."""
    from ..export.lilypond import to_lilypond
    from ..kit import DEFAULT_KIT
    from ..layout import plan_layout
    kit = kit or DEFAULT_KIT
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_layout(score)
    ly = out_dir / "chart.ly"
    ly.write_text(to_lilypond(score, kit, plan))
    return build_view(score, plan, ly, out_dir)


def build_view(score: Score, plan: LayoutPlan, ly_path: Path, out_dir: Path) -> dict:
    """SVG pages under out_dir and the bar map: one entry per engraved bar, with the
    score bars it stands for (a bar under a repeat stands for every pass), and the
    sections, review flags and performed start times taken from the score."""
    pages = render_svg_pages(ly_path, out_dir)
    sizes, boxes = page_map(pages)
    first = min(boxes) if boxes else 1
    by_printed: dict[int, list[int]] = {}
    for i, n in plan.printed_numbers.items():
        by_printed.setdefault(n, []).append(i)
    bars, missing = [], 0
    for k, pb in enumerate(plan.bars):
        printed = plan.printed_numbers.get(pb.index)
        score_bars = sorted(by_printed.get(printed, [pb.index]))
        box = boxes.get(first + k)
        if box is None:
            missing += 1
        ms = [score.measures[i] for i in score_bars]
        bars.append({
            "printed": printed, "score_bars": [i + 1 for i in score_bars], "box": box,
            "section": ms[0].section, "uncertain": any(m.uncertain for m in ms),
            "start_times": [m.start_time for m in ms if m.start_time is not None],
        })
    nominal = score.measure_start_seconds()
    timeline = [{"score_bar": i + 1, "t": m.start_time if m.start_time is not None else nominal[i],
                 "printed": plan.printed_numbers.get(i)} for i, m in enumerate(score.measures)]
    sections = [{"name": m.section, "score_bar": i + 1, "printed": plan.printed_numbers.get(i)}
                for i, m in enumerate(score.measures) if m.section]
    return {"pages": sizes, "bars": bars, "timeline": timeline, "sections": sections,
            "timeline_kind": "performed" if any(m.start_time is not None for m in score.measures) else "nominal",
            "unmapped_bars": missing}
