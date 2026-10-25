"""Changing a beat: whole-beat transforms, part swaps, direct edits and plain-language
commands.

Every operation takes the current score (with whatever the user changed by hand) and
returns a new one. Three kinds of operation:

- **Settings changes** regenerate the beat from the changed `BeatSpec` with the same
  seeds, so the result is recognizably the same beat: simpler, more complex, another
  length, another feel.
- **Part swaps** regenerate one part and replace only that part in the current score.
  The parts are the hi-hat/ride hand, the kick or the ghost notes. Everything else,
  hand edits included, stays as it was.
- **Direct edits** write into the score: a fill, an ending, a crash, a tempo, clearing
  or copying bars.

`edit_command` turns a sentence ("replace the final bar with a tom fill") into these
operations by rules. Anything it can't read is reported as unsupported, with examples
of what it can do: it never silently ignores the request.
"""

from __future__ import annotations

import copy
import re
from fractions import Fraction

from ..kit import DEFAULT_KIT
from ..model import Hit, Measure, Score
from .engine import Bar, Engine, generate
from .spec import BeatSpec, new_seed

HAT_LAYER = {"hihat", "hihat_open", "hihat_half", "ride", "ride_bell", "hihat_pedal"}
TOMS = {"tom1", "tom2", "floor_tom", "floor_tom2"}
INSTRUMENT_WORDS = [  # (pattern, instruments)
    (r"ghost[- ]?notes?", "ghost"),
    (r"open hi[- ]?hats?", {"hihat_open"}),
    (r"hi[- ]?hats?|hats", {"hihat", "hihat_open", "hihat_half"}),
    (r"ride", {"ride", "ride_bell"}),
    (r"crash(?:es)?|cymbals?", {"crash", "crash2", "china", "splash"}),
    (r"cross[- ]?sticks?|rim ?clicks?", {"cross_stick"}),
    (r"snares?", {"snare"}),
    (r"kicks?|bass drums?|kick drums?", {"kick"}),
    (r"toms?", TOMS),
]


class EditError(ValueError):
    pass


def spec_of(score: Score) -> BeatSpec:
    gen = (score.analysis or {}).get("generator") or {}
    return BeatSpec.from_dict(gen.get("spec") or {})


def _with_spec(score: Score, spec: BeatSpec, note: str) -> Score:
    gen = dict((score.analysis or {}).get("generator") or {})
    gen["spec"] = spec.to_dict()
    gen.setdefault("history", [])
    gen["history"] = (gen["history"] + [note])[-50:]
    score.analysis = {**(score.analysis or {}), "generator": gen}
    return score


def _keep_meta(new: Score, old: Score) -> Score:
    """A regenerated beat keeps the title the user gave it."""
    new.title = old.title
    new.artist = old.artist
    return new


# ---- whole-beat transforms ------------------------------------------------------------

def regenerate(score: Score, spec: BeatSpec, note: str) -> Score:
    new = _keep_meta(generate(spec), score)
    return _with_spec(new, spec, note)


GENERATED_ONLY = {"regenerate", "variation", "simpler", "more_complex", "set_bars", "set_feel", "set_style", "hats",
                  "kick", "snare", "regenerate_bars"}


def is_generated(score: Score) -> bool:
    return bool((score.analysis or {}).get("generator"))


def transform(score: Score, action: str, params: dict | None = None) -> tuple[Score, str]:
    """Apply a named action; returns (new score, what was done)."""
    params = params or {}
    if action in GENERATED_ONLY and not is_generated(score):
        raise EditError("That change regenerates parts of an original beat; this chart was transcribed or written, "
                        "so edit it in the grid instead.")
    spec = spec_of(score)
    s = copy.deepcopy(score)
    if action == "regenerate":
        spec.seed, spec.layer_seeds = new_seed(), {}
        return regenerate(s, spec, "regenerated"), "A new beat with the same settings."
    if action == "variation":
        for layer in ("kick", "hats", "variation", "snare"):
            spec.layer_seeds[layer] = spec.layer_seeds.get(layer, 0) + 1
        return regenerate(s, spec, "variation"), "A variation: new kick, hi-hat and ghost-note choices, same form."
    if action in ("simpler", "more_complex"):
        c = spec.resolved_complexity()
        c = max(0.0, c - 0.25) if action == "simpler" else min(1.0, c + 0.25)
        spec.complexity = round(c, 2)
        if action == "simpler" and c < 0.3:
            spec.difficulty = "beginner"
        elif action == "more_complex" and c > 0.7:
            spec.difficulty = "advanced"
        elif spec.difficulty == "beginner" and c >= 0.3 or spec.difficulty == "advanced" and c <= 0.7:
            spec.difficulty = "intermediate"
        word = "Simpler" if action == "simpler" else "More complex"
        return regenerate(s, spec, action), f"{word}: complexity {c:.0%} ({spec.difficulty})."
    if action == "set_bars":
        spec.bars = int(params.get("bars") or spec.bars)
        spec.clamped()
        return regenerate(s, spec, f"bars {spec.bars}"), f"Rearranged to {spec.bars} bars."
    if action == "set_feel":
        spec.feel = params.get("feel")
        spec.clamped()
        return regenerate(s, spec, f"feel {spec.feel}"), f"Feel: {(spec.feel or 'the style default').replace('_', '-')}."
    if action == "set_style":
        spec.style = params.get("style") or spec.style
        spec.bpm = params.get("bpm", spec.bpm)
        spec.clamped()
        return regenerate(s, spec, f"style {spec.style}"), f"Style: {spec.style_def.label}."
    if action == "regenerate_bars":
        bars = [int(b) for b in params.get("bars") or []]
        if not bars:
            raise EditError("select the bars to rewrite")
        for part in ("kick", "hats", "ghosts"):
            s = swap_part(s, part, bars=bars, reseed=True)
        return s, f"New groove in bar{'s' if len(bars) > 1 else ''} {_span(bars)}; the rest is unchanged."
    if action == "set_tempo":
        bpm = float(params.get("bpm") or 0)
        return set_tempo(s, bpm), f"Tempo {bpm:g} BPM."
    if action == "hats":
        return hats(s, params)
    if action == "kick":
        return swap_part(s, "kick", bars=params.get("bars"), reseed=True,
                         changes={"syncopation": params.get("syncopation")}), "A new kick pattern."
    if action == "snare":
        return swap_part(s, "ghosts", bars=params.get("bars"), reseed=True,
                         changes={"ghost_notes": params.get("ghost_notes", True)}), "New ghost notes on the snare."
    if action == "add_fill":
        bars = params.get("bars") or [len(s.measures)]
        return add_fill(s, bars, beats=params.get("beats"), voice=params.get("voice")), \
            f"Fill in bar{'s' if len(bars) > 1 else ''} {', '.join(map(str, bars))}."
    if action == "ending":
        kind = params.get("ending") or "dramatic"
        return set_ending(s, kind), f"Ending: {kind.replace('_', ' + ')}."
    raise EditError(f"unknown action {action!r}")


def set_tempo(score: Score, bpm: float) -> Score:
    if not 20 <= bpm <= 400:
        raise EditError("the tempo must be between 20 and 400 BPM")
    score.measures[0].tempo = float(bpm)
    for m in score.measures[1:]:
        m.tempo = None
    spec = spec_of(score)
    spec.bpm = float(bpm)
    return _with_spec(score, spec.clamped(), f"tempo {bpm:g}")


def hats(score: Score, params: dict) -> tuple[Score, str]:
    spec = spec_of(score)
    rates = ["8ths", "16ths", "quarters"]
    changes: dict = {}
    if params.get("hat_rate"):
        changes["hat_rate"] = params["hat_rate"]
    if params.get("cymbal"):
        changes["cymbal"] = params["cymbal"]
    if "open_hats" in params:
        changes["open_hats"] = params["open_hats"]
    current = spec.hat_rate or spec.style_def.hat_rate
    if not changes:  # cycle: busier, then sparser, then back, with a fresh choice of open hats
        changes["hat_rate"] = rates[(rates.index(current) + 1) % len(rates)] if current in rates else "8ths"
    elif changes.get("hat_rate") == current and "open_hats" not in changes:
        changes["open_hats"] = True  # already at that rate: busier means open hi-hats
    new = swap_part(score, "hats", bars=params.get("bars"), reseed=True, changes=changes)
    what = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in changes.items())
    return new, f"Cymbal part: {what}. Kick and snare unchanged."


# ---- part swaps ---------------------------------------------------------------------------

def _in_part(h: Hit, part: str) -> bool:
    if part == "hats":
        return h.inst in HAT_LAYER or (h.inst == "crash" and not h.accent and h.pos != 0)
    if part == "kick":
        return h.inst in ("kick", "kick2")
    if part == "ghosts":
        return h.inst == "snare" and h.ghost
    raise EditError(f"unknown part {part}")


def _fill_start(score: Score, i: int) -> Fraction | None:
    """Where a fill starts in bar i (from the generator's record or the first tom stroke)."""
    gen = (score.analysis or {}).get("generator") or {}
    starts = gen.get("fill_starts") or {}
    if str(i + 1) in starts:
        return Fraction(starts[str(i + 1)])
    toms = [h.pos for h in score.measures[i].hits if h.inst in TOMS]
    if toms:
        beat = Fraction(1, 4)
        return (min(toms) // beat) * beat
    return None


def swap_part(score: Score, part: str, *, bars: list[int] | None = None, reseed: bool = True,
              changes: dict | None = None) -> Score:
    if not is_generated(score):
        raise EditError("Writing a new hi-hat, kick or ghost-note part works on original beats only; edit this "
                        "chart's notes in the grid.")
    spec = spec_of(score)
    for k, v in (changes or {}).items():
        if v is not None:
            setattr(spec, k, v)
    spec.bars = len(score.measures)
    if reseed:
        layer = {"hats": "hats", "kick": "kick", "ghosts": "snare"}[part]
        spec.layer_seeds[layer] = spec.layer_seeds.get(layer, 0) + 1
    spec.clamped()
    fresh = generate(spec)
    out = copy.deepcopy(score)
    targets = set(range(len(out.measures))) if not bars else {b - 1 for b in bars if 1 <= b <= len(out.measures)}
    for i in targets:
        m, new = out.measures[i], fresh.measures[i]
        if m.time_sig != new.time_sig:
            continue
        cut = _fill_start(out, i)
        last_bar_ending = i == len(out.measures) - 1 and spec.resolved_ending() != "none" and not bars
        if last_bar_ending:
            continue
        keep = [h for h in m.hits if not (_in_part(h, part) and (cut is None or h.pos < cut))]
        taken = {(h.pos, h.inst) for h in keep}
        crash_at = {h.pos for h in keep if h.inst in ("crash", "crash2", "china", "splash")}
        for h in new.hits:
            if _in_part(h, part) and (cut is None or h.pos < cut) and (h.pos, h.inst) not in taken:
                if part == "hats" and h.pos in crash_at:
                    continue
                keep.append(copy.copy(h))
        m.hits = _playable(m, keep)
    return _with_spec(out, spec, f"{part} part")


def _playable(m: Measure, hits: list[Hit]) -> list[Hit]:
    eng = Engine(BeatSpec(time_signature=str(m.time_sig) if str(m.time_sig) in
                          ("2/4", "3/4", "4/4", "5/4", "6/8", "7/8", "9/8", "12/8") else None))
    bar = Bar(m.time_sig)
    for h in hits:
        bar.hits[(h.pos, h.inst)] = h
    return eng._playable(bar)


# ---- direct edits -------------------------------------------------------------------------

def add_fill(score: Score, bars: list[int], beats: int | None = None, voice: str | None = None) -> Score:
    spec = spec_of(score)
    if voice in ("toms", "snare", "mixed"):
        spec.fill_voice = voice
    out = copy.deepcopy(score)
    gen = dict((out.analysis or {}).get("generator") or {})
    starts = dict(gen.get("fill_starts") or {})
    for b in sorted(set(bars)):
        if not 1 <= b <= len(out.measures):
            raise EditError(f"bar {b} does not exist (the chart has {len(out.measures)} bars)")
        m = out.measures[b - 1]
        eng = Engine(_spec_for(spec, m))
        n_beats = len(m.time_sig.beats())
        take = n_beats if beats is None else max(1, min(n_beats, int(beats)))
        start = n_beats - take
        bar = Bar(m.time_sig)
        for h in m.hits:
            bar.hits[(h.pos, h.inst)] = copy.copy(h)
        eng.fill(bar, start, f"edit:{b}:{spec.layer_seeds.get('fills', 0)}")
        m.hits = eng._playable(bar)
        starts[str(b)] = str(m.time_sig.beats()[start][0])
        if b < len(out.measures):  # land the fill on a crash
            nxt = out.measures[b]
            nb = Bar(nxt.time_sig)
            for h in nxt.hits:
                nb.hits[(h.pos, h.inst)] = h
            eng.crash(nb)
            nxt.hits = eng._playable(nb)
    gen["fill_starts"] = starts
    out.analysis = {**(out.analysis or {}), "generator": gen}
    spec.layer_seeds["fills"] = spec.layer_seeds.get("fills", 0) + 1
    return _with_spec(out, spec, f"fill {bars}")


def _spec_for(spec: BeatSpec, m: Measure) -> BeatSpec:
    s = copy.deepcopy(spec)
    ts = str(m.time_sig)
    s.time_signature = ts if ts in ("2/4", "3/4", "4/4", "5/4", "6/8", "7/8", "9/8", "12/8") else None
    return s.clamped()


def set_ending(score: Score, kind: str) -> Score:
    if kind not in ("crash", "fill_crash", "stop", "dramatic", "none"):
        raise EditError(f"unknown ending {kind!r}")
    out = copy.deepcopy(score)
    spec = spec_of(out)
    spec.ending = kind
    n = len(out.measures)
    last = out.measures[-1]
    eng = Engine(_spec_for(spec, last))
    if kind == "none":  # no ending: the last bar plays the groove of the bar before it
        if n >= 2 and out.measures[n - 2].time_sig == last.time_sig:
            last.hits = copy.deepcopy(out.measures[n - 2].hits)
    else:
        last.hits = eng.ending_bar(kind).sorted()
        if kind in ("fill_crash", "dramatic") and n >= 2:
            out = add_fill(_with_spec(out, spec, "ending"), [n - 1])
            return out
    return _with_spec(out, spec, f"ending {kind}")


def _bars(spec: BeatSpec, n: int) -> BeatSpec:
    s = copy.deepcopy(spec)
    s.bars = n
    return s.clamped()


def add_crash(score: Score, bars: list[int]) -> Score:
    out = copy.deepcopy(score)
    spec = spec_of(out)
    for b in bars:
        if not 1 <= b <= len(out.measures):
            raise EditError(f"bar {b} does not exist")
        m = out.measures[b - 1]
        eng = Engine(_spec_for(spec, m))
        bar = Bar(m.time_sig)
        for h in m.hits:
            bar.hits[(h.pos, h.inst)] = h
        eng.crash(bar)
        m.hits = eng._playable(bar)
    return _with_spec(out, spec, f"crash {bars}")


def clear(score: Score, bars: list[int], instruments) -> Score:
    out = copy.deepcopy(score)
    for b in bars:
        m = out.measures[b - 1]
        if instruments == "ghost":
            m.hits = [h for h in m.hits if not h.ghost]
        elif instruments is None:
            m.hits = []
        else:
            m.hits = [h for h in m.hits if h.inst not in instruments]
    return _with_spec(out, spec_of(out), f"clear {bars}")


def copy_bar(score: Score, src: int, dst: list[int]) -> Score:
    out = copy.deepcopy(score)
    n = len(out.measures)
    if not 1 <= src <= n or any(not 1 <= d <= n for d in dst):
        raise EditError(f"bars must be between 1 and {n}")
    for d in dst:
        if out.measures[d - 1].time_sig != out.measures[src - 1].time_sig:
            raise EditError(f"bar {d} is in another meter than bar {src}")
        out.measures[d - 1].hits = copy.deepcopy(out.measures[src - 1].hits)
    return _with_spec(out, spec_of(out), f"copy {src} -> {dst}")


# ---- plain-language commands ----------------------------------------------------------------

NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
EXAMPLES = [
    "Add a fill to bar 8",
    "Replace the final bar with a tom fill",
    "Add an eighth-note kick variation to the last two bars",
    "Make the hi-hat pattern busier but keep the kick and snare",
    "Use the ride in the chorus",
    "Add ghost notes",
    "Remove the crashes from bars 2-4",
    "Change the tempo to 128",
    "Give it a dramatic ending",
    "Make it simpler",
    "Copy bar 1 to bars 2-4",
]


def _n(word: str) -> int:
    return int(word) if word.isdigit() else NUMS.get(word, 1)


def parse_bars(text: str, score: Score) -> list[int] | None:
    n = len(score.measures)
    m = re.search(r"bars?\s+(\d+)\s*(?:-|to|through|–)\s*(\d+)", text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return list(range(min(a, b), min(n, max(a, b)) + 1))
    m = re.search(r"(?:last|final) (\w+) bars", text)
    if m:
        k = _n(m.group(1))
        return list(range(max(1, n - k + 1), n + 1))
    if re.search(r"(?:last|final|ending) bar|the end\b|at the end", text):
        return [n]
    m = re.search(r"first (\w+) bars", text)
    if m:
        return list(range(1, min(n, _n(m.group(1))) + 1))
    if re.search(r"first bar|bar one\b", text):
        return [1]
    m = re.search(r"every (\w+) bars", text)
    if m:
        k = _n(m.group(1))
        return list(range(k, n + 1, k)) if k else None
    m = re.search(r"bars?\s+((?:\d+\s*(?:,|and)?\s*)+)", text)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1)) if 1 <= int(x) <= n]
        return nums or None
    for name in ("intro", "verse", "pre-chorus", "chorus", "bridge", "breakdown", "build", "solo", "outro", "groove"):
        if re.search(r"\b(the )?" + name + r"(es|s)?\b", text):
            return section_bars(score, name)
    return None


def section_bars(score: Score, name: str) -> list[int] | None:
    out, current = [], None
    for i, m in enumerate(score.measures):
        if m.section:
            current = m.section.lower()
        if current and current.split()[0] == name:
            out.append(i + 1)
    return out or None


def edit_command(score: Score, command: str) -> tuple[Score, list[str]]:
    """Apply a plain-language edit; raises EditError (with examples) if it can't be read."""
    text = " ".join(command.lower().replace("–", "-").split())
    if not text:
        raise EditError("type what to change, e.g. " + "; ".join(EXAMPLES[:3]))
    bars = parse_bars(text, score)
    done: list[str] = []
    s = score

    m = re.search(r"(?:tempo|bpm|speed)\D{0,20}(\d{2,3})|(\d{2,3})\s*bpm", text)
    if m:
        bpm = float(m.group(1) or m.group(2))
        s = set_tempo(copy.deepcopy(s), bpm)
        done.append(f"Tempo {bpm:g} BPM.")
    elif re.search(r"\b(faster|speed (it )?up)\b", text):
        bpm = round(s.initial_tempo * 1.1)
        s = set_tempo(copy.deepcopy(s), bpm)
        done.append(f"Tempo {bpm:g} BPM.")
    elif re.search(r"\b(slower|slow (it )?down)\b", text):
        bpm = round(s.initial_tempo * 0.9)
        s = set_tempo(copy.deepcopy(s), bpm)
        done.append(f"Tempo {bpm:g} BPM.")

    ending = re.search(r"\b(dramatic|big|epic|stop|crash|abrupt)\b[^.]*\bending\b|\bending\b[^.]*\b(dramatic|stop|crash)\b",
                       text)
    if ending:
        word = ending.group(1) or ending.group(2)
        kind = {"dramatic": "dramatic", "big": "dramatic", "epic": "dramatic", "stop": "stop", "abrupt": "stop",
                "crash": "crash"}[word]
        s = set_ending(s, kind)
        done.append(f"Ending: {kind}.")
    elif re.search(r"\b(change|new|different) (the )?ending\b", text):
        current = spec_of(s).resolved_ending()
        kind = {"dramatic": "stop", "stop": "crash", "crash": "dramatic"}.get(current, "dramatic")
        s = set_ending(s, kind)
        done.append(f"Ending: {kind}.")

    if re.search(r"\bfill\b", text) and not ending:
        voice = "toms" if re.search(r"\btom", text) else ("snare" if re.search(r"\bsnare fill", text) else None)
        beats = None if re.search(r"\b(replace|whole|full|entire)\b", text) else (
            2 if re.search(r"\b(short|half|two[- ]beat|2[- ]beat)\b", text) else None)
        target = bars or [len(s.measures)]
        s = add_fill(s, target, beats=beats, voice=voice)
        done.append(f"Fill in bar{'s' if len(target) > 1 else ''} {', '.join(map(str, target))}.")

    m = re.search(r"\bcopy bar (\d+) to (bars? [\d\s,and-]+)", text) or re.search(r"\brepeat bar (\d+)", text)
    if m:
        src = int(m.group(1))
        dst = parse_bars(m.group(2), s) if m.lastindex and m.lastindex >= 2 else [min(len(s.measures), src + 1)]
        s = copy_bar(s, src, dst or [])
        done.append(f"Bar {src} copied to {', '.join(map(str, dst or []))}.")

    hat_words = re.search(r"\bhi[- ]?hats?|\bhats?\b|\bride\b|\bcymbal pattern", text)
    if hat_words and not re.search(r"\b(remove|delete|clear|no)\b", text):
        params: dict = {"bars": bars}
        if re.search(r"\bride\b", text) and re.search(r"\b(use|switch|move|on|play)\b", text):
            params["cymbal"] = "ride"
        elif re.search(r"\b(use|switch|back to|move to)\b[^.]*\bhi[- ]?hat", text):
            params["cymbal"] = "hihat"
        if re.search(r"\b(busier|more|sixteenth|16th|faster|denser)\b", text):
            params["hat_rate"] = "16ths"
        elif re.search(r"\b(eighth|8th)", text):
            params["hat_rate"] = "8ths"
        elif re.search(r"\b(sparser|less busy|quarter|simpler|calmer)\b", text):
            params["hat_rate"] = "quarters" if "quarter" in text else "8ths"
        if re.search(r"\bopen\b", text):
            params["open_hats"] = True
        if len(params) > 1 or re.search(r"\b(change|vary|new|different)\b", text):
            s, msg = hats(s, params)
            done.append(msg)

    keeps = set(re.findall(r"keep (?:the )?(kick|snare|hi[- ]?hat)s?(?: and (?:the )?(kick|snare|hi[- ]?hat)s?)?", text))
    kept = {w for pair in keeps for w in pair if w}
    if re.search(r"\bkick|bass drum", text) and "kick" not in kept and not re.search(r"\b(remove|delete|clear|no)\b", text):
        if re.search(r"double[- ]?(bass|kick)", text):
            s = swap_part(s, "kick", bars=bars, changes={"double_bass": True})
            done.append("Double bass in " + (f"bars {_span(bars)}." if bars else "every bar."))
        elif re.search(r"\b(variation|vary|syncopat|busier|more|different|new|change)\b", text):
            grid_16 = re.search(r"\b(sixteenth|16th)", text)
            changes = {"syncopation": 0.95 if re.search(r"syncopat|busier|more", text) else 0.7}
            if not grid_16 and re.search(r"\b(eighth|8th)", text):
                changes["difficulty"] = "beginner"  # 8th-note grid for the kick
            s = swap_part(s, "kick", bars=bars, changes=changes)
            if "difficulty" in changes:
                spec = spec_of(s)
                spec.difficulty = spec_of(score).difficulty
                s = _with_spec(s, spec, "kick")
            done.append("New kick pattern in " + (f"bars {_span(bars)}." if bars else "every bar."))
        elif re.search(r"\b(simpler|less|sparser)\b", text):
            s = swap_part(s, "kick", bars=bars, changes={"syncopation": 0.15})
            done.append("Simpler kick in " + (f"bars {_span(bars)}." if bars else "every bar."))

    if re.search(r"ghost[- ]?notes?", text) and "snare" not in kept and \
            not re.search(r"\b(remove|delete|clear|no|without)\b", text):
        s = swap_part(s, "ghosts", bars=bars, changes={"ghost_notes": True, "complexity": max(0.5, spec_of(s).resolved_complexity())})
        done.append("Ghost notes added" + (f" in bars {_span(bars)}." if bars else "."))

    if re.search(r"\b(add|put|place)\b[^.]*\bcrash", text) and not ending:
        target = bars or [1]
        s = add_crash(s, target)
        done.append(f"Crash on bar {', '.join(map(str, target))}.")

    m = re.search(r"\b(remove|delete|clear|drop|take out|no)\b\s+(?:all\s+)?(?:the\s+)?([a-z -]+?)(?:\s+(?:from|in|on|of)\b|$)", text)
    if m:
        what = m.group(2).strip()
        insts = None
        for pat, val in INSTRUMENT_WORDS:
            if re.fullmatch(r"(?:the )?(?:" + pat + r")", what) or re.search(r"\b(?:" + pat + r")\b", what):
                insts = val
                break
        if insts is None and re.search(r"\b(bar|bars|everything|notes)\b", what):
            insts = None
        elif insts is None:
            raise EditError(f"I can't tell which instrument “{what}” is. " + _examples())
        target = bars or list(range(1, len(s.measures) + 1))
        s = clear(s, target, insts)
        done.append(f"Removed {what} from bar{'s' if len(target) > 1 else ''} {_span(target)}.")

    if not is_generated(s) and re.search(r"\b(simpler|easier|less busy|less complex|more complex|harder|busier|"
                                          r"half[- ]time|double[- ]time)\b", text) and not done:
        raise EditError("Simplifying or changing the feel regenerates an original beat; for this chart, edit the "
                        "notes in the grid. " + _examples())
    if re.search(r"\b(simpler|easier|less busy|less complex|tone it down)\b", text) and not hat_words and \
            not re.search(r"\bkick", text):
        s, msg = transform(s, "simpler")
        done.append(msg)
    elif re.search(r"\b(more complex|harder|busier|more intricate|more advanced|spice)\b", text) and not hat_words and \
            not re.search(r"\bkick", text):
        s, msg = transform(s, "more_complex")
        done.append(msg)
    if re.search(r"\bhalf[- ]time\b", text):
        s, msg = transform(s, "set_feel", {"feel": "half_time"})
        done.append(msg)
    elif re.search(r"\bdouble[- ]time\b", text):
        s, msg = transform(s, "set_feel", {"feel": "double_time"})
        done.append(msg)

    if not done:
        raise EditError("I couldn't turn that into a change to the chart. " + _examples())
    return s, done


def _span(bars: list[int] | None) -> str:
    if not bars:
        return "all"
    if len(bars) > 2 and bars == list(range(bars[0], bars[-1] + 1)):
        return f"{bars[0]}-{bars[-1]}"
    return ", ".join(map(str, bars))


def _examples() -> str:
    return "Things I can do: " + "; ".join(f"“{e}”" for e in EXAMPLES[:6]) + "."


__all__ = ["DEFAULT_KIT", "EXAMPLES", "EditError", "edit_command", "spec_of", "transform"]
