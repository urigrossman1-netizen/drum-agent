# Chart spec format (YAML or JSON)

A chart spec is an *input* that compiles to score.json. Render it with
`python -m drum_agent render chart.yaml -o out/`.

```yaml
title: Song Title               # only what the user called it
artist: Band                    # omit unless the user gave it
transcriber: Name               # omit unless the user gave it; never guess a name
chart_type: performance_chart   # full_transcription | performance_chart | pattern_study
rights: original                # own | permission | licensed | public_domain | original
tempo: 100                      # quarter notes per minute, or "4.=72" / "2=60"
tempo_text: Funk                # style/feel printed with the tempo mark (also per section)
time: 4/4                       # 3/4, 6/8, 12/8, 7/8 (+ beat_groups: "2+2+3") ...
# pickup: "1/4"                 # optional anacrusis: bar 1 is then this long (whole notes)
swing: false                    # true prints "Swing" with its rhythm (♫ = ♩♪³); write the 8ths straight
patterns:
  verse:
    hh: "x-x-x-x-x-x-x-x-"
    sn: "----x-------x---"
    bd: "x-------x-x-----"
  fill:
    sn: "x-x-x-x-xxxx----"
    t1: "------------xx--"
    ft: "--------------xx"
    bd: "x-------x-------"
    sticking: "R-L-R-L-RLRLRLRL"     # hand per stroke, on the same grid; printed under the staff
sections:
  - label: Verse 1
    cue: Band in                # italic text above the first bar of the section
    bars: [verse, "verse*6", {sn: "----x-------xxxx", hh: "x-x-x-x-x-x-----", bd: "x-------x-------"}]
  - label: Bridge
    time: 6/8                   # meter and tempo changes persist until changed again
    tempo: "4.=70"
    repeat: 2                   # repeats this section's bar list
    bars: [...]
```

## Bars
- A pattern name, `"name*N"` (N copies), or an inline mapping of instrument
  lines. An inline mapping can also set `time`, `tempo`, `tempo_text`, `cue`,
  `uncertain: true` and `notes: [...]`, or reuse `pattern: name`.

## Sticking and cues
- `sticking:` (or `stick:`) is a line in a pattern or bar, on the same grid as
  the instrument lines: `R`, `L` or `B` (both hands) under a stroke, `-` for
  none. Each letter goes to the hand stroke at that position (a drum before a
  cymbal); a letter with no hand stroke under it is an error. It prints on one
  line under the staff and is exported as MusicXML fingering.
- `cue:` on a bar entry or a section prints italic text above the staff at the
  start of that bar ("Band in", "Gtr. solo", "hey"). Never put lyrics here.

Charts compiled from a spec get status `entered` (the report says so). It
means "written, not detected": nobody has checked it against a recording.

## Instrument lines
- Characters divide the bar evenly: 16 characters in 4/4 are 16ths, 12 are
  8th-note triplets, 24 are 16th triplets, 32 are 32nds. Every line must fit
  the meter: 4/4 takes 4, 8, 12, 16, 24, 32 or 48 characters; 3/4 takes 3, 6,
  9, 12, 18, 24 or 36; 6/8 takes 2, 4, 6, 8, 12 or 24. Count before rendering.
  A wrong count is rejected with the section, bar, pattern and instrument
  named.
- With `|`, each segment is one beat and divides that beat:
  `"xxx|x-x|xxxx|x"` = triplets, a triplet "quarter-eighth", 16ths, a quarter.
  Beats follow the meter's grouping: 6/8 has two dotted-quarter beats, 3/8 and
  2/8 one, 4/8 two, 7/8 (2+2+3) three.
- Instrument names: ids or aliases (`hh hho bd sn t1 t2 ft rd rb cr cr2 cs hf`...).

## Symbols
`- .` rest · `x` stroke · `X >` accent · `g` ghost · `o` open hi-hat (hh line) ·
`h` half-open hi-hat · `f` flam · `F` accented flam · `d` drag · `D` accented drag · `r` roll (`~`
extends it) · `c` choke.

## Validation (errors are explicit)
Rejected before anything is engraved:
- unknown symbols or patterns;
- lines that don't fit a supported grid, or the wrong number of beat segments;
- bar keys such as `time`, `tempo` or `length` inside a pattern (put them on the
  section or on the bar entry: `{pattern: turn, time: 2/4}`);
- conflicting hi-hat states at one moment, accent and ghost together, rolls
  past the barline.

Grid errors name the section, bar, pattern and instrument. Rhythms finer than
32nds or sextuplets (e.g. quintuplets) can't be written.
