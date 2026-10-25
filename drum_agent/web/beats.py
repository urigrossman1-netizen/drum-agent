"""Original beats in the web app: reading a description (rules, plus Claude when it is
configured) and applying actions and plain-language edits to a working score."""

from __future__ import annotations

import logging

from ..generate.edits import EXAMPLES, EditError, edit_command, transform
from ..generate.parse import apply_overrides, interpret
from ..generate.spec import BeatSpec
from ..model import Score
from . import claude

log = logging.getLogger("drum_agent.web")
RULE_FIELDS_FIRST = ("bpm", "time_signature", "bars")  # numbers read from the prompt are exact


def interpret_request(prompt: str, settings: dict, seed: int | None = None,
                      use_claude: bool = True) -> tuple[BeatSpec, list[dict], dict]:
    """(spec, notes, info). The rules always run; Claude, when configured, fills in the
    musical judgement (style, feel, parts) the rules left at their defaults."""
    spec, notes = interpret(prompt, None, seed)
    info: dict = {"interpreter": "rules"}
    if use_claude and claude.config()["configured"] and prompt.strip():
        try:
            answer = claude.interpret_beat(prompt)
            from_rules = {n["field"] for n in notes if n["source"] == "prompt"}
            d = spec.to_dict()
            for k, v in answer["spec"].items():
                if v is None or k in from_rules and k in RULE_FIELDS_FIRST:
                    continue
                d[k] = v
            spec = BeatSpec.from_dict(d)
            notes.append({"field": "interpreter", "value": "Claude", "source": "claude", "detail": answer["summary"]})
            info = {"interpreter": "claude", "summary": answer["summary"], "usage": answer["usage"]}
        except claude.ClaudeUnavailable as exc:
            log.info("Claude interpretation unavailable: %s", exc)
            info = {"interpreter": "rules", "claude_error": exc.code}
    spec = apply_overrides(spec, settings or {}, notes)
    return spec, notes, info


def summary_for(score: Score) -> dict:
    return {"bars": len(score.measures), "time_signature": str(score.measures[0].time_sig),
            "tempo": score.initial_tempo,
            "sections": [{"name": m.section, "first_bar": i + 1} for i, m in enumerate(score.measures) if m.section],
            "instruments": score.instruments_used()}


def apply_command(score: Score, command: str) -> tuple[Score, list[str], dict]:
    try:
        new, done = edit_command(score, command)
        return new, done, {"interpreter": "rules"}
    except EditError as rules_error:
        if not claude.config()["configured"]:
            raise
        try:
            answer = claude.edit_to_commands(command, summary_for(score), EXAMPLES)
        except claude.ClaudeUnavailable as exc:
            raise EditError(f"{rules_error} (Claude could not help: {exc})") from None
        if answer["unsupported"] or not answer["commands"]:
            raise EditError(answer["explanation"] or str(rules_error)) from None
        done: list[str] = []
        s = score
        for cmd in answer["commands"]:
            s, d = edit_command(s, cmd)
            done += d
        return s, done, {"interpreter": "claude", "commands": answer["commands"]}


def apply_action(score: Score, action: str, params: dict) -> tuple[Score, str]:
    return transform(score, action, params)
