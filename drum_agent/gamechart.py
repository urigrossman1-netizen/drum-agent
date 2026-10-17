"""Rock Band / Clone Hero drum charts -> IR, through the shared quantizer.

A game chart is a drum part someone has already charted on a tick grid, with
the song's tempo map and meters, so it converts the way a MIDI drum track does
(`io_midi.read_midi`): tempo map -> beat grid -> `BarDef`s -> `quantize`. The
quantizer is what guarantees that every position can be spelled, even when a
charter's note sits a tick off the grid or on a 64th.

Inputs, all supplied by the user:

* ``notes.mid`` (Rock Band, Clone Hero): the track named ``PART DRUMS``; tempo
  and meter from the first (conductor) track; sections from the ``EVENTS``
  track (``[section Verse 1]`` or ``[prc_verse_1]``).
* ``notes.chart`` (Clone Hero text format): ``[Song]``, ``[SyncTrack]``,
  ``[Events]`` and ``[ExpertDrums]`` / ``[HardDrums]`` / ``[MediumDrums]`` /
  ``[EasyDrums]``.
* a song folder holding either, plus ``song.ini`` (name, artist, charter).

Pads and lanes (the dicts below are the tables the code reads)::

    pad     kit (cymbal | tom)  MIDI Expert/Hard/Medium/Easy  .chart lane  .chart flags at the same tick
    kick    kick                96 / 84 / 72 / 60; 95 Exp+    0; 32 Exp+   -
    red     snare               97 / 85 / 73 / 61             1            accent 34, ghost 40
    yellow  hihat | tom1        98 / 86 / 74 / 62             2            cymbal 66, accent 35, ghost 41
    blue    ride  | tom2        99 / 87 / 75 / 63             3            cymbal 67, accent 36, ghost 42
    green   crash | floor_tom   100 / 88 / 76 / 64            4            cymbal 68, accent 37, ghost 43

Cymbal or tom is where the formats differ:

* MIDI: with pro drums, yellow/blue/green are cymbals unless a tom marker
  (110 yellow, 111 blue, 112 green) is sounding at that tick. A file with no
  tom markers at all is an older, non-pro chart (Rock Band 1 style): the three
  pads read as toms, unless song.ini says ``pro_drums = True``.
* .chart: yellow/blue/green are toms unless a cymbal flag (66-68) sits at that
  tick.
* ``pro=False`` (``--no-pro``) reads every yellow/blue/green note as a tom.

Disco flip (MIDI text ``[mix N drums0d]`` for difficulty N, 0 = Easy to 3 =
Expert, until the next ``[mix N drums0]``) swaps red and the yellow cymbal in
a pro reading: the charted red notes are the hi-hat and the yellow cymbals are
the snare. Clone Hero dynamics (MIDI) count only when the text event
``[ENABLE_CHART_DYNAMICS]`` is in the drum track: velocity 127 is an accent,
velocity 1 a ghost note. A .chart carries them as flags.

Five-lane charts (a second green lane: MIDI 101/89/77/65, .chart lane 5) are
rejected: their pads don't map onto a drum kit the same way.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path

import mido

from .io_midi import TEMPO_MARK_CHANGE, _bar_ticks, _tempo_at, _tick_to_seconds, open_midi
from .model import Score, ScoreError, TimeSig
from .quantize import BarDef, Onset, QuantizeOptions, quantize

DIFFICULTIES = ("expert", "hard", "medium", "easy")
DIFFICULTY_INDEX = {"easy": 0, "medium": 1, "hard": 2, "expert": 3}  # N in "[mix N drums0d]"

# Pad -> kit instrument. Kick and red have no cymbal/tom variant.
PAD_TO_KIT: dict[str, str] = {
    "kick": "kick",
    "red": "snare",
    "yellow_cymbal": "hihat",
    "blue_cymbal": "ride",
    "green_cymbal": "crash",
    "yellow_tom": "tom1",
    "blue_tom": "tom2",
    "green_tom": "floor_tom",
}
COLOUR_PADS = ("yellow", "blue", "green")  # the pads that are a cymbal or a tom
LANE_ORDER = ("kick", "red", "yellow", "blue", "green")

# MIDI (PART DRUMS): first note of each difficulty; the lanes follow in LANE_ORDER.
MIDI_BASE = {"expert": 96, "hard": 84, "medium": 72, "easy": 60}
MIDI_EXPERT_PLUS_KICK = 95  # Expert+ (double-pedal) kick: a kick
MIDI_FIVE_LANE = 5  # base + 5: the extra green of a five-lane chart
MIDI_TOM_MARKERS = {110: "yellow", 111: "blue", 112: "green"}
MIDI_DRUM_TRACK = "PART DRUMS"
MIDI_EVENTS_TRACK = "EVENTS"
MIDI_DYNAMICS_EVENT = "ENABLE_CHART_DYNAMICS"
MIDI_ACCENT_VELOCITY = 127
MIDI_GHOST_VELOCITY = 1

# .chart (Clone Hero): "tick = N lane length" in [<Difficulty>Drums].
CHART_TRACKS = {"expert": "ExpertDrums", "hard": "HardDrums", "medium": "MediumDrums", "easy": "EasyDrums"}
CHART_LANES = {0: "kick", 1: "red", 2: "yellow", 3: "blue", 4: "green", 32: "kick"}  # 32 = Expert+ kick
CHART_FIVE_LANE = 5
CHART_CYMBAL_FLAGS = {66: "yellow", 67: "blue", 68: "green"}
CHART_ACCENT_FLAGS = {34: "red", 35: "yellow", 36: "blue", 37: "green"}
CHART_GHOST_FLAGS = {40: "red", 41: "yellow", 42: "blue", 43: "green"}
CHART_DEFAULT_RESOLUTION = 192

DEFAULT_TEMPO = 500000  # microseconds per quarter (120 BPM), as in MIDI
TEMPO_RANGE = (20.0, 400.0)  # what a score may print (Score.validate)

SIMPLIFIED = ("Game charts are simplified: one lane per pad colour. Every yellow cymbal is written as a "
              "closed hi-hat (open/closed and the hi-hat pedal are not charted), cymbal identity is an "
              "approximation (yellow = hi-hat, blue = ride, green = crash), and accents and ghost notes "
              "appear only where the chart has dynamics. Check it against the recording.")


class GameChartError(ValueError):
    """The file isn't a drum chart this importer can read."""


@dataclass
class Gem:
    tick: int
    pad: str  # key of PAD_TO_KIT
    accent: bool = False
    ghost: bool = False


@dataclass
class GameChart:
    """One difficulty of a drum chart, independent of the file format."""
    format: str  # "midi" | "chart"
    resolution: int  # ticks per quarter note
    tempo_map: list[tuple[int, int]]  # (tick, microseconds per quarter), as io_midi
    time_sigs: list[tuple[int, TimeSig]]
    sections: list[tuple[int, str]]
    gems: list[Gem]
    difficulties: list[str]  # the difficulties that have drum notes
    pro: bool
    pro_reason: str
    dynamics: bool  # accents/ghosts can be charted
    metadata: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    offset: float = 0.0  # .chart Offset: where tick 0 sits in the audio (sync only, not notation)


@dataclass
class GameChartReport:
    path: Path  # the chart file that was read
    format: str
    difficulty: str
    difficulties: list[str]
    pro: bool
    pro_reason: str
    dynamics: bool
    gems: int = 0
    trimmed_leading_bars: int = 0
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---- locating and reading the files ----------------------------------------------

def locate_chart(path: str | Path) -> tuple[Path, Path | None, list[str]]:
    """(chart file, song.ini or None, notes) for a chart file or a song folder."""
    p = Path(path)
    notes: list[str] = []
    if p.is_dir():
        files = {f.name.lower(): f for f in sorted(p.iterdir()) if f.is_file()}
        mid, chart = files.get("notes.mid") or files.get("notes.midi"), files.get("notes.chart")
        if mid and chart:
            notes.append(f"the folder has both {mid.name} and {chart.name}; read {mid.name}")
        found = mid or chart
        if found is None:
            raise GameChartError(f"{p} has no notes.mid or notes.chart (a .sng package must be extracted first)")
        return found, files.get("song.ini"), notes
    if not p.is_file():
        raise GameChartError(f"{p} does not exist")
    if p.suffix.lower() not in (".mid", ".midi", ".chart"):
        raise GameChartError(f"{p.name}: expected a notes.mid, a notes.chart or a song folder")
    ini = next((f for f in sorted(p.parent.iterdir()) if f.is_file() and f.name.lower() == "song.ini"), None)
    return p, ini, notes


def default_stem(chart_file: Path) -> str:
    """Output name: the song folder's name for notes.mid/notes.chart (every song has one)."""
    folder = chart_file.resolve().parent.name
    if chart_file.stem.lower() == "notes" and folder:
        return folder
    return chart_file.stem


def _read_text(path: Path) -> str:
    """UTF-8 (what current tools write), UTF-16 with a byte-order mark, else Latin-1."""
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _plain(value: str) -> str:
    """Clone Hero metadata may carry rich-text tags (<color=...>); keep the text only."""
    return re.sub(r"<[^<>]*>", "", value).strip().strip('"').strip()


def read_song_ini(path: Path) -> dict[str, str]:
    """The [song] section of a song.ini, keys lowercased. Many tools write these, so a
    plain line reader: no interpolation, and a repeated key keeps its last value."""
    out: dict[str, str] = {}
    section = None
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        elif section == "song" and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip().lower()] = _plain(value)
    return out


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1", "yes", "on")


# ---- shared by both formats -------------------------------------------------------

def _pad(lane: str, cymbal: bool, disco: bool) -> str:
    if disco and lane == "red":
        return "yellow_cymbal"
    if disco and lane == "yellow" and cymbal:
        return "red"
    if lane in ("kick", "red"):
        return lane
    return f"{lane}_{'cymbal' if cymbal else 'tom'}"


_SECTION = re.compile(r"^(?:section[\s_]+|prc_)(.*)$", re.IGNORECASE)
_MIX = re.compile(r"^\[?\s*mix[\s_]*(\d)[\s_]*drums[\s_]*\d+([a-z]*)\s*\]?$", re.IGNORECASE)


def section_name(text: str) -> str | None:
    """'[section Verse 1]', 'section verse_1' or '[prc_verse_1]' -> 'Verse 1'."""
    m = _SECTION.match(text.strip().strip('"').strip("[]").strip())
    if not m:
        return None
    name = re.sub(r"\s+", " ", _plain(m.group(1)).replace("_", " ")).strip()
    return name[:1].upper() + name[1:] if name else None


def _disco_changes(texts: list[tuple[int, str]], difficulty: str) -> list[tuple[int, bool]]:
    """(tick, flipped from here on) for this difficulty's '[mix N drumsMx]' events.

    'd' flips red and yellow; 'dnoflip' marks a disco section whose pro chart is
    already the right way round, so it doesn't flip.
    """
    out = []
    for tick, text in texts:
        m = _MIX.match(text.strip().strip('"'))
        if m and int(m.group(1)) == DIFFICULTY_INDEX[difficulty]:
            out.append((tick, m.group(2).lower() == "d"))
    return sorted(out, key=lambda x: x[0])


def _state_at(changes: list[tuple[int, bool]], tick: int) -> bool:
    state = False
    for t, value in changes:
        if t > tick:
            break
        state = value
    return state


def _meter(num: int, den: int) -> TimeSig:
    try:
        return TimeSig(num, den)
    except ScoreError as exc:
        raise GameChartError(f"the chart's meter {num}/{den} can't be written: {exc}") from None


def _difficulty_error(difficulty: str, available: list[str]) -> GameChartError:
    if not available:
        return GameChartError("the chart has no drum notes")
    return GameChartError(f"the chart has no {difficulty} drum notes; it has: {', '.join(available)} "
                          f"(use --difficulty)")


def _pro_reading(pro: bool | None, has_markers: bool, ini: dict[str, str], what: str) -> tuple[bool, str]:
    if pro is False:
        return False, "off (--no-pro): yellow, blue and green read as toms"
    if pro is True:
        return True, "on (requested)"
    if has_markers:
        return True, f"on ({what} in the file)"
    if _truthy(ini.get("pro_drums")):
        return True, "on (song.ini pro_drums = True)"
    return False, f"off (no {what} in the file): yellow, blue and green read as toms"


MIN_MILLI_BPM, MAX_MILLI_BPM = 1_000, 1_000_000  # .chart tempo "B" values: 1-1000 BPM
MAX_NUMERATOR = 64


def _check_tempo(us_per_quarter: int, where: str) -> None:
    if not 60_000 <= us_per_quarter <= 60_000_000:  # 1000 BPM .. 1 BPM
        raise GameChartError(f"{where}: tempo out of range (1-1000 BPM)")


# ---- MIDI -------------------------------------------------------------------------

def _absolute(track: mido.MidiTrack):
    tick = 0
    for msg in track:
        tick += msg.time
        yield tick, msg


def _texts(track: mido.MidiTrack | None) -> list[tuple[int, str]]:
    if track is None:
        return []
    return [(t, msg.text.strip()) for t, msg in _absolute(track)
            if msg.type in ("text", "marker") and msg.text.strip()]


def _covered(spans: list[tuple[int, int]], tick: int) -> bool:
    return any(s <= tick < e or s == tick for s, e in spans)


def _midi_lane(note: int, difficulty: str) -> str | None:
    if difficulty == "expert" and note == MIDI_EXPERT_PLUS_KICK:
        return "kick"
    k = note - MIDI_BASE[difficulty]
    return LANE_ORDER[k] if 0 <= k < len(LANE_ORDER) else None


def parse_midi(path: Path, difficulty: str = "expert", pro: bool | None = None,
               ini: dict[str, str] | None = None) -> GameChart:
    try:
        mid = open_midi(path)
    except (OSError, EOFError, ValueError) as exc:
        raise GameChartError(f"{path.name} is not a readable MIDI file: {exc}") from None
    if mid.ticks_per_beat < 1:  # also SMPTE time division, which charts never use
        raise GameChartError(f"{path.name}: ticks per quarter note must be positive, got {mid.ticks_per_beat}")
    ini = ini or {}
    tracks: dict[str, mido.MidiTrack] = {}
    for tr in mid.tracks:
        tracks.setdefault(tr.name.strip().upper(), tr)
    drums = tracks.get(MIDI_DRUM_TRACK)
    if drums is None:
        names = [tr.name.strip() for tr in mid.tracks if tr.name.strip()]
        raise GameChartError(f"{path.name} has no '{MIDI_DRUM_TRACK}' track (tracks: {', '.join(names) or 'none'})")
    conductor = mid.tracks[0]

    tempo_map = sorted(((t, m.tempo) for t, m in _absolute(conductor) if m.type == "set_tempo"),
                       key=lambda c: c[0])
    for t, tempo in tempo_map:
        _check_tempo(tempo, f"tick {t}: set_tempo {tempo}")
    if not tempo_map or tempo_map[0][0] != 0:
        tempo_map.insert(0, (0, DEFAULT_TEMPO))
    metres = sorted(((t, _meter(m.numerator, m.denominator))
                     for t, m in _absolute(conductor) if m.type == "time_signature"), key=lambda c: c[0])

    strokes: list[tuple[int, int, int]] = []  # tick, note, velocity
    open_markers: dict[int, list[int]] = {}
    spans: dict[str, list[tuple[int, int]]] = {pad: [] for pad in COLOUR_PADS}
    for tick, msg in _absolute(drums):
        if msg.type == "note_on" and msg.velocity > 0:
            strokes.append((tick, msg.note, msg.velocity))
            if msg.note in MIDI_TOM_MARKERS:
                open_markers.setdefault(msg.note, []).append(tick)
        elif msg.type in ("note_off", "note_on") and open_markers.get(msg.note):
            spans[MIDI_TOM_MARKERS[msg.note]].append((open_markers[msg.note].pop(0), tick))
    for note, starts in open_markers.items():  # never released: covers its own tick
        spans[MIDI_TOM_MARKERS[note]] += [(s, s) for s in starts]

    five = sorted({n for _, n, _ in strokes} & {b + MIDI_FIVE_LANE for b in MIDI_BASE.values()})
    if five:
        raise GameChartError(f"{path.name} is a five-lane drum chart (note {five[0]}); only four-lane "
                             f"(Rock Band / Clone Hero) drum charts are supported")
    available = [d for d in DIFFICULTIES if any(_midi_lane(n, d) for _, n, _ in strokes)]
    if difficulty not in available:
        raise _difficulty_error(difficulty, available)

    drum_texts = _texts(drums)
    dynamics = any(text.strip("[] ").upper() == MIDI_DYNAMICS_EVENT for _, text in drum_texts)
    pro_on, reason = _pro_reading(pro, any(spans.values()), ini, "tom markers (notes 110-112)")
    disco = _disco_changes(drum_texts, difficulty)
    notes = []
    if any(flip for _, flip in disco) and not pro_on:
        notes.append("disco-flip sections are left as charted: the flip belongs to a pro-drums reading")

    gems = []
    for tick, note, vel in strokes:
        lane = _midi_lane(note, difficulty)
        if lane is None:
            continue
        cymbal = pro_on and lane in COLOUR_PADS and not _covered(spans[lane], tick)
        flip = pro_on and _state_at(disco, tick)
        dyn = dynamics and lane != "kick"
        gems.append(Gem(tick, _pad(lane, cymbal, flip), accent=dyn and vel == MIDI_ACCENT_VELOCITY,
                        ghost=dyn and vel == MIDI_GHOST_VELOCITY))

    events = tracks.get(MIDI_EVENTS_TRACK, conductor)
    sections = [(t, name) for t, text in _texts(events) if (name := section_name(text))]
    return GameChart("midi", mid.ticks_per_beat, tempo_map, metres, sections, gems, available,
                     pro_on, reason, dynamics, notes=notes)


# ---- .chart -----------------------------------------------------------------------

_BLOCK = re.compile(r"^\[(.+)\]$")
_EVENT = re.compile(r"^(\d+)\s*=\s*([A-Za-z]+)\s*(.*)$")


def _chart_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        m = _BLOCK.match(line)
        if m:
            current = m.group(1).strip()
            blocks.setdefault(current, [])
        elif line and line not in ("{", "}") and current is not None:
            blocks[current].append(line)
    return blocks


def _chart_events(lines: list[str]) -> tuple[list[tuple[int, str, str]], int]:
    """(tick, kind, rest) per "tick = KIND rest" line, and the number of lines that aren't one."""
    out, skipped = [], 0
    for line in lines:
        m = _EVENT.match(line)
        if m:
            out.append((int(m.group(1)), m.group(2).upper(), m.group(3).strip()))
        else:
            skipped += 1
    return out, skipped


def _ints(args: str, block: str, tick: int, count: int) -> list[int]:
    """The first `count` numbers of an event (a missing optional one is left out)."""
    try:
        values = [int(x) for x in args.split()[:count]]
    except ValueError:
        values = []
    if not values:
        raise GameChartError(f"[{block}] tick {tick}: expected numbers, got {args!r}")
    return values


def parse_chart(text: str, difficulty: str = "expert", pro: bool | None = None,
                ini: dict[str, str] | None = None) -> GameChart:
    ini = ini or {}
    blocks = _chart_blocks(text)
    song = {}
    for line in blocks.get("Song", []):
        if "=" in line:
            key, value = line.split("=", 1)
            song[key.strip().lower()] = _plain(value)
    try:
        resolution = int(float(song.get("resolution", CHART_DEFAULT_RESOLUTION)))
    except (ValueError, OverflowError):
        raise GameChartError(f"[Song] Resolution {song['resolution']!r} is not a number") from None
    if resolution < 1:
        raise GameChartError(f"[Song] Resolution must be positive, got {resolution}")

    skipped = 0
    parsed: dict[str, list[tuple[int, str, str]]] = {}
    for name in ("SyncTrack", "Events", *CHART_TRACKS.values()):
        if name in blocks:
            parsed[name], n = _chart_events(blocks[name])
            skipped += n

    tempo_map, metres = [], []
    for tick, kind, args in parsed.get("SyncTrack", []):
        if kind == "B":  # BPM x 1000
            milli_bpm = _ints(args, "SyncTrack", tick, 1)[0]
            if not MIN_MILLI_BPM <= milli_bpm <= MAX_MILLI_BPM:
                raise GameChartError(f"[SyncTrack] tick {tick}: tempo B {args} is out of range "
                                     f"({MIN_MILLI_BPM // 1000}-{MAX_MILLI_BPM // 1000} BPM, times 1000)")
            tempo_map.append((tick, round(60_000_000_000 / milli_bpm)))
        elif kind == "TS":  # numerator, then the denominator as a power of two (default 2: quarters)
            num, *exp = _ints(args, "SyncTrack", tick, 2)
            power = exp[0] if exp else 2
            if not 1 <= num <= MAX_NUMERATOR or not 0 <= power <= 5:
                raise GameChartError(f"[SyncTrack] tick {tick}: meter TS {args} can't be written "
                                     f"(numerator 1-{MAX_NUMERATOR}, denominator 1-32)")
            metres.append((tick, _meter(num, 2 ** power)))
    tempo_map.sort(key=lambda c: c[0])
    if not tempo_map or tempo_map[0][0] != 0:
        tempo_map.insert(0, (0, DEFAULT_TEMPO))
    metres.sort(key=lambda c: c[0])
    sections = [(tick, name) for tick, kind, args in parsed.get("Events", [])
                if kind == "E" and (name := section_name(args))]

    # Per difficulty: tick -> the lanes and flags at that tick.
    notes_at: dict[str, dict[int, set[int]]] = {}
    for d, block in CHART_TRACKS.items():
        for tick, kind, args in parsed.get(block, []):
            if kind == "N":
                notes_at.setdefault(d, {}).setdefault(tick, set()).add(_ints(args, block, tick, 1)[0])
    lanes_used = {d: set().union(*at.values()) for d, at in notes_at.items()}
    if any(CHART_FIVE_LANE in used for used in lanes_used.values()):
        raise GameChartError("this is a five-lane drum chart (lane 5); only four-lane (Rock Band / Clone Hero) "
                             "drum charts are supported")
    available = [d for d in DIFFICULTIES if lanes_used.get(d, set()) & set(CHART_LANES)]
    if difficulty not in available:
        raise _difficulty_error(difficulty, available)

    has_flags = any(used & set(CHART_CYMBAL_FLAGS) for used in lanes_used.values())
    # In a .chart the cymbal flags are the pro reading; song.ini's pro_drums alone has
    # nothing to mark which pads are cymbals.
    pro_on, reason = _pro_reading(pro, has_flags, {}, "cymbal flags (66-68)")
    track_texts = [(t, a) for t, k, a in parsed[CHART_TRACKS[difficulty]] if k == "E"]
    disco = _disco_changes(track_texts, difficulty)
    known = set(CHART_LANES) | set(CHART_CYMBAL_FLAGS) | set(CHART_ACCENT_FLAGS) | set(CHART_GHOST_FLAGS)
    ignored = sorted(lanes_used[difficulty] - known)
    notes = [f"chart lanes {ignored} (flams, markers) are not read"] if ignored else []
    if skipped:
        notes.append(f"{skipped} line(s) of the chart could not be read and were skipped")

    gems = []
    at = notes_at[difficulty]
    for tick in sorted(at):
        flags = at[tick]
        cymbals = {CHART_CYMBAL_FLAGS[n] for n in flags if n in CHART_CYMBAL_FLAGS}
        accents = {CHART_ACCENT_FLAGS[n] for n in flags if n in CHART_ACCENT_FLAGS}
        ghosts = {CHART_GHOST_FLAGS[n] for n in flags if n in CHART_GHOST_FLAGS}
        flip = pro_on and _state_at(disco, tick)
        for lane in sorted({CHART_LANES[n] for n in flags if n in CHART_LANES}, key=LANE_ORDER.index):
            cymbal = pro_on and lane in cymbals
            gems.append(Gem(tick, _pad(lane, cymbal, flip), accent=lane in accents, ghost=lane in ghosts))
    meta = {k: song[k] for k in ("name", "artist", "charter") if song.get(k)}
    try:
        offset = float(song.get("offset", 0))
    except ValueError:
        offset = 0.0
    if not math.isfinite(offset):
        offset = 0.0
    return GameChart("chart", resolution, tempo_map, metres, sections, gems, available, pro_on, reason,
                     dynamics=True, metadata=meta, notes=notes, offset=offset)


# ---- chart -> score ---------------------------------------------------------------

def _short_meter(ticks: int, den: int, tpb: int) -> TimeSig | None:
    """The meter of a bar cut short to `ticks` (a 4/4 bar cut after three beats is 3/4)."""
    length = Fraction(ticks, 4 * tpb)
    for d in (2, 4, 8, 16):
        if d >= den and (length * d).denominator == 1 and length * d >= 1:
            return TimeSig(int(length * d), d)
    return None


def _bars(time_sigs: list[tuple[int, TimeSig]], end_tick: int,
          tpb: int) -> tuple[list[tuple[int, TimeSig]], list[str]]:
    """(start tick, meter) of every bar through `end_tick`, and notes on odd meter events.

    In both games a meter event starts a new bar where it stands, so one placed
    inside a bar cuts that bar short; the short bar gets the meter of its own
    length. One that can't be written that way applies from the next barline.
    """
    # Of several meter events at one tick the last wins.
    metres = [c for i, c in enumerate(time_sigs) if i + 1 == len(time_sigs) or time_sigs[i + 1][0] != c[0]]
    if not metres or metres[0][0] != 0:
        metres.insert(0, (0, TimeSig(4, 4)))
    bars, notes = [], []
    tick, i = 0, 0
    while tick <= end_tick:
        while i + 1 < len(metres) and metres[i + 1][0] <= tick:
            i += 1
        ts = metres[i][1]
        length = _bar_ticks(ts, tpb)
        nxt = metres[i + 1][0] if i + 1 < len(metres) else None
        if nxt is not None and nxt < tick + length:
            short = _short_meter(nxt - tick, ts.den, tpb)
            if short is not None:
                notes.append(f"the meter change at tick {nxt} cuts a {ts} bar short: written as a {short} bar")
                bars.append((tick, short))
                tick = nxt
                continue
            notes.append(f"the meter change at tick {nxt} falls inside a {ts} bar; it starts at the next barline")
        bars.append((tick, ts))
        tick += length
    return bars, notes


def _nearest_bar(starts: list[int], tick: int) -> int:
    """Index of the barline nearest `tick` (the earlier one on a tie)."""
    i = max(bisect.bisect_right(starts, tick) - 1, 0)
    if i + 1 < len(starts) and 2 * (tick - starts[i]) > starts[i + 1] - starts[i]:
        return i + 1
    return i


TICK_SLACK = 2  # ticks a gem may sit off a grid position and still be read as on it
MAX_BEATS = 20_000  # about 80 minutes at 240 BPM: past this a chart's ticks are corrupt


def chart_to_score(chart: GameChart, options: QuantizeOptions | None = None) -> tuple[Score, dict]:
    """Quantize a chart's gems onto its own bar grid, as io_midi does for a MIDI track."""
    if not chart.gems:
        raise GameChartError("the chosen difficulty has no drum notes")
    tpb = chart.resolution
    last = max(g.tick for g in chart.gems)
    if last / tpb > MAX_BEATS:
        raise GameChartError(f"the last note is at tick {last}, {last // tpb} beats in: more than any song; "
                             f"the chart's ticks or resolution are corrupt")
    # One bar past the last stroke, as io_midi (empty trailing bars are dropped below).
    bars, notes = _bars(chart.time_sigs, last + 4 * tpb, tpb)
    beat_ticks: list[int] = []
    bar_defs: list[BarDef] = []
    for start, ts in bars:
        bar_defs.append(BarDef(len(beat_ticks), ts, len(ts.beats())))
        beat_ticks += [start + int(round(pos * 4 * tpb)) for pos, _ in ts.beats()]
    beat_ticks.append(bars[-1][0] + _bar_ticks(bars[-1][1], tpb))
    if any(b <= a for a, b in zip(beat_ticks, beat_ticks[1:])):
        raise GameChartError(f"resolution {tpb} is too coarse for the chart's meters")
    beat_times = [_tick_to_seconds(t, chart.tempo_map, tpb) for t in beat_ticks]

    def seconds(tick: int) -> float:
        # Linear in ticks within a beat: a tempo event inside a beat must not move a
        # stroke onto another subdivision (an 8th stays an 8th).
        k = bisect.bisect_right(beat_ticks, tick) - 1
        if not 0 <= k < len(beat_ticks) - 1:
            return _tick_to_seconds(tick, chart.tempo_map, tpb)
        share = (tick - beat_ticks[k]) / (beat_ticks[k + 1] - beat_ticks[k])
        return beat_times[k] + share * (beat_times[k + 1] - beat_times[k])

    onsets = [Onset(time=seconds(g.tick), inst=PAD_TO_KIT[g.pad], accent=g.accent, ghost=g.ghost)
              for g in chart.gems]
    # Chart ticks are exact positions, not played times: a beat whose ticks all sit on a
    # spellable grid keeps them (at a fast tempo the time-based costs alone would rewrite
    # an exact 32nd-16th figure as sextuplets); off-grid ticks are snapped as usual.
    exact = replace(options or QuantizeOptions(), exact_tol=TICK_SLACK / tpb)
    result = quantize(onsets, beat_times, bar_defs, exact)
    starts = [s for s, _ in bars]

    # Leave out the empty bars before the drums come in and after they stop, as io_midi does.
    lead, end = 0, len(result.measures)
    while lead + 1 < end and not result.measures[lead].hits:
        lead += 1
    while end - 1 > lead and not result.measures[end - 1].hits:
        end -= 1
    measures, kept = result.measures[lead:end], starts[lead:end]
    kept_end = starts[end] if end < len(starts) else beat_ticks[-1]
    if lead:
        notes.append(f"the {lead} empty bar(s) before the drums come in are left out: bar 1 here is bar "
                     f"{lead + 1} of the game chart")

    _tempo_marks(measures, kept, kept_end, chart.tempo_map, tpb, notes)
    for m in measures:
        m.tempo_text = None
    if result.feel == "swing":
        measures[0].tempo_text = "Swing"
    _place_sections(measures, starts, lead, chart.sections, notes)

    counts: dict[str, int] = {}
    for m in measures:
        for h in m.hits:
            counts[h.inst] = counts.get(h.inst, 0) + 1
    score = Score(measures=measures, chart_type="full_transcription", status="unverified_import")
    score.swing = result.feel == "swing"
    info = {"lead": lead, "notes": notes, "feel": result.feel, "merged": result.merged,
            "grid_counts": result.grid_counts, "instrument_counts": counts, "dropped": result.dropped}
    return score, info


def _tempo_marks(measures, kept: list[int], kept_end: int, tempo_map: list[tuple[int, int]], tpb: int,
                 notes: list[str]) -> None:
    """Tempo marks from the chart's tempo map at barlines, as io_midi writes them. A chart
    beat-mapped to a recording moves a little every beat; only real changes get a mark,
    and so does a change of beat unit (4/4 to 6/8: quarter to dotted quarter)."""
    snap = tpb // 16  # a tempo event this close after a barline belongs to it
    current, clamped, unit = None, False, None
    for m, tick_at in zip(measures, kept):
        m.tempo = None
        bpm = round(mido.tempo2bpm(_tempo_at(tempo_map, tick_at + snap)), 2)
        value, dotted = m.time_sig.metronome_unit()
        new_unit = (value or Fraction(1, 4), dotted)  # None: a plain quarter-note mark
        if current is None or abs(bpm - current) / current >= TEMPO_MARK_CHANGE or new_unit != unit:
            m.tempo = min(max(bpm, TEMPO_RANGE[0]), TEMPO_RANGE[1])
            clamped |= m.tempo != bpm
            current, unit = bpm, new_unit
    if clamped:
        notes.append(f"tempo marks outside {TEMPO_RANGE[0]:g}-{TEMPO_RANGE[1]:g} BPM are printed at that limit")
    inside = sum(1 for t, _ in tempo_map[1:]
                 if kept[0] < t < kept_end and not any(0 <= t - s <= snap for s in kept))
    if inside:
        notes.append(f"{inside} tempo change(s) fall inside bars (a tempo map that follows the recording); "
                     f"marks show the tempo at barlines where it moved by {TEMPO_MARK_CHANGE:.0%} or more")


def _place_sections(measures, starts: list[int], lead: int, sections: list[tuple[int, str]],
                    notes: list[str]) -> None:
    """Each section on its nearest barline; the last one in the bars left out opens bar 1."""
    placed: dict[int, str] = {}
    carried = None
    for tick, name in sorted(sections, key=lambda s: s[0]):
        k = _nearest_bar(starts, tick) - lead
        if k < 0:
            carried = name
        elif k < len(measures):
            placed[k] = name
            if tick not in starts:
                notes.append(f"section {name!r} at tick {tick} is not on a barline; placed at bar {k + 1}")
    if carried and 0 not in placed:
        placed[0] = carried
    for k, name in placed.items():
        measures[k].section = name


# ---- entry point ------------------------------------------------------------------

def read_gamechart(path: str | Path, difficulty: str = "expert", pro: bool | None = None,
                   title: str | None = None, artist: str | None = None,
                   options: QuantizeOptions | None = None) -> tuple[Score, GameChartReport]:
    """Import the drum part of a game chart (notes.mid, notes.chart or a song folder).

    `pro`: None reads pro drums when the file has tom markers (MIDI) or cymbal
    flags (.chart), or song.ini says pro_drums; False reads every coloured pad
    as a tom. Title and artist come from the arguments, song.ini or the .chart's
    [Song] block (the user's own files), never from anywhere else.
    """
    if difficulty not in DIFFICULTIES:
        raise GameChartError(f"difficulty must be one of {', '.join(DIFFICULTIES)}, got {difficulty!r}")
    chart_file, ini_file, notes = locate_chart(path)
    ini = read_song_ini(ini_file) if ini_file else {}
    if _truthy(ini.get("five_lane_drums")):
        raise GameChartError("song.ini says five_lane_drums = True; only four-lane (Rock Band / Clone Hero) "
                             "drum charts are supported")
    if chart_file.suffix.lower() == ".chart":
        chart = parse_chart(_read_text(chart_file), difficulty, pro, ini)
    else:
        chart = parse_midi(chart_file, difficulty, pro, ini)
    score, info = chart_to_score(chart, options)

    report = GameChartReport(chart_file, chart.format, difficulty, chart.difficulties, chart.pro,
                             chart.pro_reason, chart.dynamics, gems=len(chart.gems),
                             trimmed_leading_bars=info["lead"])
    # song.ini is what Clone Hero shows, so it wins over the .chart's [Song] block.
    report.metadata = dict(chart.metadata)
    report.metadata.update({k: ini[k] for k in ("name", "artist", "charter") if ini.get(k)})
    if ini.get("frets") and not ini.get("charter"):
        report.metadata["charter"] = ini["frets"]  # the older song.ini key for the charter
    report.warnings = notes + chart.notes + info["notes"]
    if chart.format == "midi" and not chart.pro and pro is None:
        report.warnings.append("no pro-drums tom markers: yellow, blue and green are written as toms. If they "
                               "are cymbals, relabel them (`edit --relabel tom1=hihat`, tom2=ride, "
                               "floor_tom=crash) or set pro_drums = True in song.ini")
    if info["dropped"]:
        report.warnings.append(f"{info['dropped']} stroke(s) fell outside the bar grid and were left out")

    score.title = title or report.metadata.get("name") or default_stem(chart_file)
    score.artist = artist or report.metadata.get("artist")
    if report.metadata.get("charter"):
        score.transcriber = f"{report.metadata['charter']} (game chart)"
    kind = "Clone Hero .chart" if chart.format == "chart" else "Rock Band / Clone Hero MIDI"
    score.source = f"{kind} {chart_file.name}, {difficulty.capitalize()} drums"
    score.analysis = {
        "input": "gamechart",
        "format": chart.format,
        "difficulty": difficulty,
        "difficulties": chart.difficulties,
        "pro_drums": chart.pro_reason,
        "dynamics": chart.dynamics,
        "gems": len(chart.gems),
        "instrument_counts": info["instrument_counts"],
        "feel": info["feel"],
        "merged_duplicates": info["merged"],
        "grid_counts": info["grid_counts"],
        "trimmed_leading_bars": info["lead"],
        "notes": [SIMPLIFIED, f"Read the {difficulty} drums of {chart_file.name}; pro drums {chart.pro_reason}."]
                 + report.warnings,
    }
    if chart.offset:
        score.analysis["audio_offset_s"] = chart.offset
    return score, report
