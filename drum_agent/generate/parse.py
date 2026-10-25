"""Natural language -> `BeatSpec`, by rules (no network, no model).

"Create a powerful pop-punk beat at 165 BPM in 4/4. Use fast eighth-note hi-hats, a
driving kick, strong snare hits, energetic crashes, and a two-bar tom fill every
eight bars. Make it suitable for an intermediate drummer."

`interpret` returns the spec plus one note per decision: what it read from the
prompt, and what it took as a default. The page shows these notes, so the user can
see exactly what was understood and correct it with the quick settings.
"""

from __future__ import annotations

import re

from .spec import TIME_SIGNATURES, BeatSpec, new_seed
from .styles import DEFAULT_STYLE, STYLES

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "sixteen": 16, "twenty": 20, "twenty-four": 24, "thirty-two": 32,
           "single": 1, "a": 1, "an": 1, "half": 0}
NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|sixteen|twenty-four|twenty|thirty-two)"
SECTION_WORDS = [("intro", "Intro"), ("verse", "Verse"), ("pre-chorus", "Pre-Chorus"), ("chorus", "Chorus"),
                 ("bridge", "Bridge"), ("breakdown", "Breakdown"), ("build", "Build"), ("solo", "Solo"),
                 ("outro", "Outro")]


def _num(word: str) -> int | None:
    word = word.lower()
    if word.isdigit():
        return int(word)
    return NUMBERS.get(word)


def _style(text: str) -> tuple[str | None, str | None]:
    """The style whose longest keyword appears in the prompt."""
    best, best_len, word = None, 0, None
    for key, style in STYLES.items():
        for w in style.words:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) and len(w) > best_len:
                best, best_len, word = key, len(w), w
    return best, word


def interpret(prompt: str, overrides: dict | None = None, seed: int | None = None) -> tuple[BeatSpec, list[dict]]:
    text = " ".join((prompt or "").lower().replace("–", "-").replace("—", "-").split())
    notes: list[dict] = []
    spec = BeatSpec(seed=seed if seed is not None else new_seed())

    def note(field: str, value, source: str = "prompt", detail: str | None = None):
        notes.append({"field": field, "value": value, "source": source, **({"detail": detail} if detail else {})})

    style, word = _style(text)
    if style is None and ("half-time" in text or "half time" in text):
        style = "half_time"
    if style:
        spec.style = style
        note("style", STYLES[style].label, detail=f"from “{word}”" if word else None)
    else:
        spec.style = DEFAULT_STYLE
        note("style", STYLES[DEFAULT_STYLE].label, "default")
    st = STYLES[spec.style]

    m = re.search(r"(\d{2,3})\s*(?:bpm|beats per minute|b\.p\.m)", text) or \
        re.search(r"(?:tempo|at|around)\s+(?:of\s+)?(\d{2,3})(?!\s*(?:bars?|measures?|seconds?|minutes?|/))", text)
    if m:
        spec.bpm = float(m.group(1))
        note("bpm", int(spec.bpm))
    else:
        tempo_words = [("very fast", 1.35), ("blazing", 1.4), ("fast", 1.15), ("uptempo", 1.15), ("up-tempo", 1.15),
                       ("slow", 0.8), ("laid-back", 0.92), ("relaxed", 0.92)]
        factor = next((f for w, f in tempo_words if re.search(r"\b" + re.escape(w) + r"\b", text)
                       and not re.search(re.escape(w) + r"[- ](?:eighth|8th|sixteenth|16th|hi)", text)), None)
        if factor:
            spec.bpm = float(round(st.bpm * factor))
            note("bpm", int(spec.bpm), "prompt", "estimated from the tempo words")
        else:
            note("bpm", st.bpm, "default", f"the {st.label} default")

    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b", text)
    if m and f"{m.group(1)}/{m.group(2)}" in TIME_SIGNATURES:
        spec.time_signature = f"{m.group(1)}/{m.group(2)}"
        note("time_signature", spec.time_signature)
    elif m:
        note("time_signature", st.time_signature, "default", f"{m.group(0)} is not supported")
    elif "waltz" in text or "three-four" in text:
        spec.time_signature = "3/4"
        note("time_signature", "3/4")
    else:
        note("time_signature", st.time_signature, "default")

    bars_given = False
    m = re.search(NUM + r"[- ](?:bar|measure)s?(?![- ]?(?:long )?(?:tom |snare |drum )?fills?)", text)
    if m and not re.search(r"every\s+" + re.escape(m.group(0)), text):
        n = _num(m.group(1))
        if n:
            spec.bars = n
            bars_given = True
            note("bars", n)
    else:
        m = re.search(r"(\d+)\s*(seconds?|secs?|minutes?|mins?)\b", text)
        if m:
            secs = int(m.group(1)) * (60 if m.group(2).startswith("m") else 1)
            from ..model import TimeSig
            ts = TimeSig.parse(spec.time_signature or st.time_signature)
            spb = float(ts.bar_length) * 4 * 60 / (spec.bpm or st.bpm)
            spec.bars = max(2, min(64, round(secs / spb)))
            bars_given = True
            note("bars", spec.bars, "prompt", f"about {secs} s at this tempo")
        else:
            note("bars", spec.bars, "default")

    for words, level in ((("beginner", "easy", "simple", "basic", "novice", "first-year"), "beginner"),
                         (("intermediate", "medium difficulty", "moderate"), "intermediate"),
                         (("advanced", "difficult", "hard to play", "expert", "pro level", "challenging",
                           "virtuosic", "technical"), "advanced")):
        if any(re.search(r"\b" + re.escape(w) + r"s?\b", text) for w in words):
            spec.difficulty = level
            note("difficulty", level)
            break
    else:
        note("difficulty", spec.difficulty, "default")

    complexity = None
    if re.search(r"\b(complex|busy|busier|intricate|dense|lots of notes)\b", text):
        complexity = min(1.0, (spec.resolved_complexity()) + 0.2)
    if re.search(r"\b(minimal|sparse|simple|stripped)\b", text):
        complexity = max(0.0, spec.resolved_complexity() - 0.2)
    if complexity is not None:
        spec.complexity = round(complexity, 2)
        note("complexity", spec.complexity)

    if re.search(r"\b(half[- ]time)\b", text) and spec.style != "half_time":
        spec.feel = "half_time"
        note("feel", "half-time")
    elif re.search(r"\b(double[- ]time|skank)\b", text):
        spec.feel = "double_time"
        note("feel", "double-time")
    elif re.search(r"\b(shuffle|swung|swing feel|triplet feel)\b", text) and not st.triplet:
        spec.feel = "triplet"
        note("feel", "triplet (shuffle)")
    elif re.search(r"\bstraight\b", text) and st.triplet:
        spec.feel = "straight"
        note("feel", "straight")

    if re.search(r"\b(on the ride|ride cymbal|use (?:the )?ride|ride pattern|ride instead)\b", text):
        spec.cymbal = "ride"
        note("cymbal", "ride")
    elif re.search(r"\bhi[- ]?hats?\b", text) and st.cymbal == "ride":
        spec.cymbal = "hihat"
        note("cymbal", "hi-hat")
    if re.search(r"(sixteenth|16th)[- ]note (?:hi[- ]?hats?|hats|ride)|(sixteenth|16th)s? on the (?:hi[- ]?hat|ride)|"
                 r"(?:hi[- ]?hats?|hats) in (?:sixteenths|16ths)", text):
        spec.hat_rate = "16ths"
        note("hat_rate", "16th notes")
    elif re.search(r"(eighth|8th)[- ]note (?:hi[- ]?hats?|hats|ride)|(eighth|8th)s on the (?:hi[- ]?hat|ride)|"
                   r"(?:hi[- ]?hats?|hats) in (?:eighths|8ths)", text):
        spec.hat_rate = "shuffle" if (spec.feel == "triplet" or (st.triplet and spec.feel != "straight")) else "8ths"
        note("hat_rate", "8th notes")
    elif re.search(r"quarter[- ]note (?:hi[- ]?hats?|hats|ride)", text):
        spec.hat_rate = "quarters"
        note("hat_rate", "quarter notes")
    if re.search(r"\bopen[- ]hi[- ]?hats?|open hats?\b", text):
        spec.open_hats = True
        note("open_hats", True)
    elif re.search(r"\b(closed hi[- ]?hats?|no open)\b", text):
        spec.open_hats = False
        note("open_hats", False)
    if re.search(r"\bghost[- ]?notes?\b", text) and not re.search(r"\bno ghost", text):
        spec.ghost_notes = True
        note("ghost_notes", True)
    elif re.search(r"\bno ghost", text):
        spec.ghost_notes = False
        note("ghost_notes", False)
    if re.search(r"\b(cross[- ]?stick|rim[- ]?click|side[- ]?stick)\b", text):
        spec.cross_stick = True
        note("cross_stick", True)
    if re.search(r"\b(double[- ]?bass|double[- ]?kick|twin pedal|double pedal)\b", text):
        spec.double_bass = True
        note("double_bass", True)
    if re.search(r"\bsyncopat\w*\s+(kick|bass drum)|(kick|bass drum)\w*\s+(?:is |are )?syncopat", text):
        spec.syncopation = 0.85
        note("syncopation", "syncopated kick")
    elif re.search(r"\bsyncopat", text):
        spec.syncopation = 0.75
        note("syncopation", "syncopated")
    elif re.search(r"\b(driving|straight-ahead|steady|solid) (kick|bass drum)", text):
        spec.syncopation = 0.45
        note("syncopation", "driving kick")

    for words, energy in ((("powerful", "driving", "energetic", "aggressive", "heavy", "hard-hitting", "loud",
                            "intense", "big"), "high"),
                          (("relaxed", "laid-back", "laid back", "subtle", "gentle", "soft", "chill", "quiet",
                            "mellow", "smooth"), "low")):
        if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words):
            spec.energy = energy
            note("energy", energy)
            break

    if re.search(r"\b(energetic|lots of|frequent|big) crash", text) or re.search(r"\bcrash(es)? (accents|on every)", text):
        spec.crashes = "phrases"
        note("crashes", "at every phrase")
    elif re.search(r"\bno crash", text):
        spec.crashes = "none"
        note("crashes", "none")

    if re.search(r"\bno fills?\b|\bwithout (?:any )?fills?\b", text):
        spec.fill_every = 0
        note("fills", "none")
    else:
        m = re.search(NUM + r"[- ](beat|bar|measure)[- ](?:long )?(?:(tom|snare|drum)[- ])?fills?", text)
        every = re.search(r"fills?\s+(?:at the end of\s+|after\s+)?every\s+" + NUM + r"?\s*(?:bars?|measures?)", text) or \
            re.search(r"every\s+" + NUM + r"\s*(?:bars?|measures?)", text)
        if m:
            n = _num(m.group(1)) or 1
            unit = m.group(2)
            spec.fill_beats = n * (len(__import__("drum_agent.model", fromlist=["TimeSig"]).TimeSig.parse(
                spec.time_signature or st.time_signature).beats()) if unit != "beat" else 1)
            if m.group(3) == "snare":
                spec.fill_voice = "snare"
            note("fill_length", f"{n} {unit}{'s' if n != 1 else ''}")
        if every:
            n = _num(every.group(1)) if every.group(1) else 1
            if n:
                spec.fill_every = n
                note("fill_every", f"every {n} bars")
        if re.search(r"\b(snare fills?|fills? on the snare)\b", text):
            spec.fill_voice = "snare"
        elif re.search(r"\btom fills?|fills? (?:on|around) the toms|tom[- ]heavy\b", text):
            spec.fill_voice = "toms"
        if "fill" in text:
            note("fill_voice", spec.fill_voice)

    if re.search(r"\b(dramatic|big|epic|huge) ending|ending (?:with|on) (?:a )?(?:big|dramatic)", text):
        spec.ending = "dramatic"
    elif re.search(r"\b(stop|abrupt|sudden) ending|end(?:s|ing)? (?:on|with) a stop|choke", text):
        spec.ending = "stop"
    elif re.search(r"\b(crash ending|end(?:s|ing)? (?:on|with) a crash)", text):
        spec.ending = "crash"
    elif re.search(r"\b(no ending|loop(?:able|ing)?|seamless)\b", text):
        spec.ending = "none"
    elif re.search(r"\bending\b|\bend with a fill\b", text):
        spec.ending = "fill_crash"
    if spec.ending:
        note("ending", spec.ending.replace("_", " + "))

    mentioned = []
    for w, name in SECTION_WORDS:
        for mm in re.finditer(r"\b" + re.escape(w) + r"s?\b", text):
            if name == "Chorus" and text[max(0, mm.start() - 4):mm.start()] == "pre-":
                continue
            if name == "Build" and re.search(r"\bbuild(s|ing)? (up )?(to|into)\b", text[mm.start():mm.start() + 20]):
                pass
            mentioned.append((mm.start(), name))
            break
    if len(mentioned) >= 2:
        spec.sections = [n for _, n in sorted(mentioned)]
        if spec.bars < 4 * len(spec.sections) and not bars_given:
            spec.bars = min(64, 8 * len(spec.sections))
            _set_note(notes, "bars", spec.bars, "planned for the sections")
        note("sections", " · ".join(spec.sections))
    if spec.fill_every and not bars_given and spec.bars < 2 * spec.fill_every:
        spec.bars = min(64, 2 * spec.fill_every)
        _set_note(notes, "bars", spec.bars, "two fill cycles")

    m = re.search(r"(?:called|titled|named)\s+[\"“']([^\"”']{1,80})[\"”']", prompt or "")
    if m:
        spec.title = m.group(1).strip()
        note("title", spec.title)

    spec = apply_overrides(spec, overrides or {}, notes)
    return spec.clamped(), notes


def _set_note(notes: list[dict], field: str, value, detail: str) -> None:
    notes[:] = [n for n in notes if n["field"] != field]
    notes.append({"field": field, "value": value, "source": "prompt", "detail": detail})


OVERRIDABLE = ("style", "bpm", "time_signature", "bars", "difficulty", "complexity", "feel", "cymbal", "hat_rate",
               "open_hats", "ghost_notes", "syncopation", "double_bass", "cross_stick", "fill_every", "fill_beats",
               "fill_voice", "crashes", "ending", "energy", "title", "seed")


def apply_overrides(spec: BeatSpec, overrides: dict, notes: list[dict] | None = None) -> BeatSpec:
    """Quick settings win over the prompt."""
    d = spec.to_dict()
    for k, v in overrides.items():
        if k in OVERRIDABLE and v not in (None, "", "auto"):
            d[k] = v
            if notes is not None:
                notes[:] = [n for n in notes if n["field"] != k]
                notes.append({"field": k, "value": v, "source": "setting"})
    return BeatSpec.from_dict(d)
