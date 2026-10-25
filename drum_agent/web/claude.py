"""Claude suggests names for a chart's sections (Intro, Verse, Chorus ...).

The transcriber finds section boundaries from the drum patterns and letters them A, B,
C. Naming them is a judgement about song form that a language model does well from a
compact description: where each section starts, how long it is, what the drummer plays
(main cymbal, density, fills), and how sections repeat. No audio, no file paths and no
configuration is sent; only that description, plus the song's title and artist.

The answer is structured (a JSON schema), then validated here: one name per existing
section, from a fixed vocabulary, at exactly the boundaries the chart already has.
Claude cannot add, move or remove a boundary, change a note or a tempo. A suggestion
changes nothing by itself: applying it makes a new chart version.

Configuration (server side only; never sent to the browser):
  ANTHROPIC_API_KEY             the API key
  DRUM_AGENT_ANTHROPIC_MODEL    the model id to use (required; see docs/WEB_APP.md)
  DRUM_AGENT_ANTHROPIC_BASE_URL optional; defaults to the public API
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from ..model import Score

DEFAULT_BASE_URL = "https://api.anthropic.com"
TIMEOUT_S = 45.0
MAX_TOKENS = 4000
NAMES = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Post-Chorus", "Bridge", "Solo", "Interlude",
         "Breakdown", "Build", "Drop", "Instrumental", "Fill", "Outro", "Tag", "Coda", "Section")
NAME_RE = re.compile(r"(" + "|".join(re.escape(n) for n in NAMES) + r")( [1-9])?")

SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_bar": {"type": "integer"},
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["first_bar", "name", "reason"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "comment": {"type": "string"},
    },
    "required": ["sections", "confidence", "comment"],
    "additionalProperties": False,
}


class ClaudeUnavailable(RuntimeError):
    """Not configured, or the API could not be reached / refused the request."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def config() -> dict:
    key, model = os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("DRUM_AGENT_ANTHROPIC_MODEL")
    missing = [n for n, v in (("ANTHROPIC_API_KEY", key), ("DRUM_AGENT_ANTHROPIC_MODEL", model)) if not v]
    return {"configured": not missing, "missing": missing, "model": model}


def describe_sections(score: Score) -> list[dict]:
    """A compact, factual description of each labelled section (what Claude sees)."""
    starts = [i for i, m in enumerate(score.measures) if m.section] or [0]
    out = []
    for k, first in enumerate(starts):
        last = (starts[k + 1] if k + 1 < len(starts) else len(score.measures)) - 1
        ms = score.measures[first:last + 1]
        insts = Counter(h.inst for m in ms for h in m.hits)
        cymbals = [i for i in ("hihat", "hihat_open", "ride", "crash", "china", "splash") if insts.get(i)]
        sigs = Counter(m.musical_signature() for m in ms)
        out.append({
            "first_bar": first + 1, "bars": len(ms), "current_label": score.measures[first].section,
            "strokes_per_bar": round(sum(len(m.hits) for m in ms) / len(ms), 1),
            "main_cymbal": max(cymbals, key=insts.get) if cymbals else None,
            "crashes": insts.get("crash", 0), "tom_strokes": sum(v for i, v in insts.items() if "tom" in i),
            "distinct_bar_patterns": len(sigs),
            "starts_at_s": round(ms[0].start_time, 1) if ms[0].start_time is not None else None,
            "same_pattern_as_section": next((p["first_bar"] for p in out if p["_sig"] == _sig(ms)), None),
            "_sig": _sig(ms),
        })
    for o in out:
        o.pop("_sig")
    return out


def _sig(ms) -> tuple:
    return tuple(m.musical_signature() for m in ms[:4])


def prompt_for(score: Score, sections: list[dict]) -> str:
    return (
        "You are naming the sections of a drum chart produced by automatic transcription. The section "
        "boundaries below were found from the drum patterns and are fixed: give each one a name, keep every "
        "first_bar exactly as given, and do not add or remove sections.\n\n"
        f"Song: {score.title}" + (f" by {score.artist}" if score.artist else "") + "\n"
        f"Tempo: {score.initial_tempo:g} BPM, time signature {score.measures[0].time_sig}, "
        f"{len(score.measures)} bars.\n\n"
        "Sections (JSON):\n" + json.dumps(sections, indent=1) + "\n\n"
        "Use only these names, optionally followed by a space and a number for repeats (\"Verse 2\"): "
        + ", ".join(NAMES) + ". Base the names on the form you can infer from the patterns (repetition, "
        "density, cymbal changes, crashes, position in the song). If you know this song's form, you may use "
        "that knowledge, but never invent a section that isn't in the list. Use \"Section\" when nothing fits. "
        "Keep each reason under 20 words and state your overall confidence honestly."
    )


def validate_suggestion(data: dict, sections: list[dict]) -> list[dict]:
    """The suggestion, checked against the chart; raises ValueError when it doesn't fit."""
    got = data.get("sections")
    if not isinstance(got, list):
        raise TypeError("the answer has no section list")
    expected = [s["first_bar"] for s in sections]
    if [s.get("first_bar") for s in got] != expected:
        raise ValueError(f"the answer moved, added or removed section boundaries (expected bars {expected})")
    out = []
    for s in got:
        name = " ".join(str(s.get("name", "")).split())
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"{name!r} is not one of the allowed section names")
        out.append({"first_bar": s["first_bar"], "name": name, "reason": str(s.get("reason", ""))[:200]})
    return out


def suggest_section_names(score: Score, client=None) -> dict:
    """{"sections": [...], "confidence", "comment", "model", "usage"}; raises ClaudeUnavailable."""
    cfg = config()
    if not cfg["configured"]:
        raise ClaudeUnavailable("not_configured", "Claude is not configured on this server: set "
                                + " and ".join(cfg["missing"]))
    import anthropic
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                     base_url=os.environ.get("DRUM_AGENT_ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL,
                                     timeout=TIMEOUT_S, max_retries=1)
    sections = describe_sections(score)
    try:
        response = client.messages.create(
            model=cfg["model"], max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt_for(score, sections)}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.AuthenticationError:
        raise ClaudeUnavailable("auth", "the Anthropic API rejected the server's API key") from None
    except anthropic.PermissionDeniedError:
        raise ClaudeUnavailable("forbidden", "the API key may not use this model") from None
    except anthropic.NotFoundError:
        raise ClaudeUnavailable("bad_model", f"the configured model {cfg['model']!r} was not found") from None
    except anthropic.RateLimitError:
        raise ClaudeUnavailable("rate_limited", "the Anthropic API rate limit was reached; try again later") from None
    except anthropic.APITimeoutError:
        raise ClaudeUnavailable("timeout", f"the Anthropic API did not answer within {TIMEOUT_S:g} s") from None
    except anthropic.APIConnectionError:
        raise ClaudeUnavailable("unreachable", "the Anthropic API could not be reached from the server") from None
    except anthropic.BadRequestError as exc:
        raise ClaudeUnavailable("bad_request", f"the Anthropic API refused the request: {_api_message(exc)}") from None
    except anthropic.APIStatusError as exc:
        raise ClaudeUnavailable("api_error", f"the Anthropic API failed (HTTP {exc.status_code})") from None
    if response.stop_reason == "refusal":
        raise ClaudeUnavailable("refused", "Claude declined to answer this request")
    if response.stop_reason == "max_tokens":
        raise ClaudeUnavailable("truncated", "Claude's answer was cut off")
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        data = json.loads(text)
        suggestion = validate_suggestion(data, sections)
    except (ValueError, TypeError) as exc:
        raise ClaudeUnavailable("invalid_answer", f"Claude's answer did not fit the chart: {exc}") from None
    usage = getattr(response, "usage", None)
    return {"sections": suggestion, "confidence": data.get("confidence"), "comment": str(data.get("comment", ""))[:400],
            "model": getattr(response, "model", cfg["model"]),
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None)}}


def _api_message(exc) -> str:
    try:
        return str(exc.body["error"]["message"])[:200]
    except (TypeError, KeyError, AttributeError):
        return str(exc)[:200]
