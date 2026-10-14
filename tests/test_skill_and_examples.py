"""The drum-chart skill and the examples must stay consistent with the code.

The skill is only useful if Claude Code can load it (valid frontmatter) and
if every command, flag, path and link it teaches actually works.
"""

import re
import shlex
from pathlib import Path

import pytest
import yaml

from conftest import needs_lilypond
from drum_agent.charts import load_any
from drum_agent.cli import build_parser
from drum_agent.pipeline import _compression, _page_fill, export_all

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "drum-chart"
DOCS = [SKILL / "SKILL.md", *sorted((SKILL / "reference").glob("*.md"))]
EXAMPLES = sorted((ROOT / "examples" / "specs").glob("*.yaml"))


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_frontmatter_is_valid_yaml_with_the_documented_fields():
    fm = frontmatter(SKILL / "SKILL.md")
    assert fm["name"] == "drum-chart"
    for key in ("description", "when_to_use"):
        assert isinstance(fm[key], str) and fm[key].strip()
    assert len(fm["description"]) <= 1024
    # Claude Code truncates description + when_to_use at 1,536 characters in the listing.
    assert len(fm["description"]) + len(fm["when_to_use"]) <= 1536


def test_skill_body_stays_lean():
    assert len((SKILL / "SKILL.md").read_text().splitlines()) < 500


def test_every_link_resolves_and_every_reference_is_linked():
    linked = set()
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)#]+)\)", doc.read_text()):
            if target.startswith("http"):
                continue
            path = (doc.parent / target).resolve()
            assert path.exists(), f"{doc.name}: broken link {target}"
            linked.add(path)
    for ref in (SKILL / "reference").glob("*.md"):
        assert ref.resolve() in linked, f"{ref.name} is not linked from the skill"


def code_blocks(text: str):
    """Fenced code blocks (also indented ones inside list items)."""
    block, lines = None, []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if block is None:
                block, lines = line.strip()[3:].strip(), []
            else:
                yield block, "\n".join(lines)
                block = None
        elif block is not None:
            lines.append(line)


def doc_commands():
    """Every `python -m drum_agent ...` command in shell code blocks, continuations joined."""
    for doc in DOCS:
        for lang, body in code_blocks(doc.read_text()):
            if lang not in ("", "bash", "sh"):
                continue
            for line in body.replace("\\\n", " ").splitlines():
                line = line.split(" #", 1)[0].strip()
                if line.startswith("python -m drum_agent "):
                    yield doc.name, line


def test_documented_commands_parse_with_the_real_cli():
    parser = build_parser()
    seen = 0
    for name, line in doc_commands():
        argv = shlex.split(line)[3:]
        try:
            parser.parse_args(argv)
        except SystemExit:
            pytest.fail(f"{name}: command does not parse: {line}")
        seen += 1
    assert seen >= 8


def test_every_documented_flag_exists():
    parser = build_parser()
    flags = set()
    for action in parser._subparsers._group_actions[0].choices.values():  # noqa: SLF001 (argparse internals)
        for a in action._actions:  # noqa: SLF001
            flags.update(a.option_strings)
    for doc in DOCS:
        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", doc.read_text()):
            assert flag in flags, f"{doc.name} mentions {flag}, which no subcommand accepts"


def test_documented_repo_paths_exist():
    pattern = re.compile(r"`((?:docs|scripts|examples|tests|drum_agent)/[\w./-]+)`")
    for doc in DOCS:
        for path in pattern.findall(doc.read_text()):
            if "<" in path or "*" in path:
                continue
            assert (ROOT / path).exists(), f"{doc.name} mentions {path}, which does not exist"


# --- examples -------------------------------------------------------------------

@pytest.mark.parametrize("spec", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_compiles_and_validates(spec):
    score = load_any(spec)
    assert score.measures and score.rights == "original"
    assert score.status == "entered"


@needs_lilypond
@pytest.mark.parametrize("spec", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_engraves_and_all_checks_pass(spec, tmp_path):
    report = export_all(load_any(spec), tmp_path, spec.stem)
    assert report.rendering_ok, [c.summary() for c in report.comparisons]
    assert not [w for w in report.warnings if w.startswith("LilyPond")]
    pages = [k for k in report.files if k.startswith("png")]
    if spec.stem.startswith("03_full_song"):
        score = load_any(spec)
        assert len(score.measures) == 60
        assert any(str(m.time_sig) == "2/4" for m in score.measures)
        assert len(pages) == 2
    if spec.stem.startswith("04_performance"):
        assert load_any(spec).chart_type == "performance_chart"
        assert len(pages) == 1  # the one-bar Ending joins the last line instead of a page of its own


# --- page fitting helpers --------------------------------------------------------

def test_compression_parses_lilypond_warnings():
    assert _compression(["x.ly: warning: compressing over-full page by 4.5 staff-spaces",
                         "warning: page 1 has been compressed",
                         "warning: compressing over-full page by 1.25 staff-spaces"]) == pytest.approx(5.75)
    assert _compression(["warning: something else"]) == 0


def test_page_fill_measures_the_lowest_ink(tmp_path):
    from PIL import Image, ImageDraw
    img = Image.new("L", (100, 200), 255)
    ImageDraw.Draw(img).rectangle([10, 10, 90, 49], fill=0)
    img.save(tmp_path / "p.png")
    assert _page_fill(tmp_path / "p.png") == pytest.approx(0.25)
    Image.new("L", (100, 200), 255).save(tmp_path / "blank.png")
    assert _page_fill(tmp_path / "blank.png") == 0.0


@needs_lilypond
def test_a_sliver_of_a_last_page_is_pulled_back(tmp_path):
    from drum_agent.charts import compile_spec
    from drum_agent.pipeline import ExportOptions
    groove = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
    score = compile_spec({"title": "Fit", "tempo": 100, "sections": [{"bars": [groove] * 44}]})
    report = export_all(score, tmp_path, "s", options=ExportOptions(repeats="none"))
    assert [k for k in report.files if k.startswith("png")] == ["png1"]
    assert any("Fitted onto 1 page" in n for n in report.notes)
    assert not [w for w in report.warnings if w.startswith("LilyPond")]


def test_chart_spec_reference_example_compiles():
    """The YAML example at the top of the chart-spec reference compiles as written
    (its Bridge section's "bars: [...]" placeholder aside), sticking and cue included."""
    from drum_agent.charts import compile_spec
    text = (SKILL / "reference" / "chart-spec.md").read_text()
    block = text.split("```yaml", 1)[1].split("```", 1)[0]
    spec = yaml.safe_load(block.split("  - label: Bridge")[0])
    score = compile_spec(spec)
    assert any(m.cue == "Band in" for m in score.measures)
    spec["sections"].append({"label": "Fill", "bars": ["fill"]})
    fill = compile_spec(spec).measures[-1]
    assert [h.sticking for h in sorted(fill.hits, key=lambda h: h.pos) if h.sticking][:4] == ["R", "L", "R", "L"]
