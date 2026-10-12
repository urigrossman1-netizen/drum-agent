# Chart spec format (YAML or JSON)

A chart spec is an *input* that compiles to score.json. Render it with
`python -m drum_agent render chart.yaml -o out/`.

```yaml
title: Song Title
artist: Band (optional)
transcriber: Your Name (optional)
chart_type: performance_chart   # full_transcription | performance_chart | pattern_study
rights: original                # own | permission | licensed | public_domain | original
tempo: 100                      # quarter notes per minute, or "4.=72" / "2=60"
time: 4/4                       # 3/4, 6/8, 12/8, 7/8 (+ beat_groups: "2+2+3") ...
pickup: "1/4"                   # optional anacrusis length (whole notes)
swing: false                    # true prints "Swing"; write the 8ths straight
patterns:
  verse:
    hh: "x-x-x-x-x-x-x-x-"
    sn: "----x-------x---"
    bd: "x-------x-x-----"
sections:
  - label: Verse 1
    bars: [verse, "verse*6", {sn: "----x-------xxxx", hh: "x-x-x-x-x-x-----", bd: "x-------x-------"}]
  - label: Bridge
    time: 6/8                   # meter and tempo changes persist until changed again
    tempo: "4.=70"
    repeat: 2                   # repeats this section's bar list
    bars: [...]
```

## Bars
- A pattern name, `"name*N"` (N copies), or an inline mapping of instrument
  lines. An inline mapping can also set `time`, `tempo`, `tempo_text`,
  `uncertain: true` and `notes: [...]`, or reuse `pattern: name`.

## Instrument lines
- Characters divide the bar evenly: 16 characters in 4/4 are 16ths, 12 are
  8th-note triplets, 24 are 16th triplets.
- With `|`, each segment is one beat and divides that beat:
  `"xxx|x-x|xxxx|x"` = triplets, a triplet "quarter-eighth", 16ths, a quarter.
- Instrument names: ids or aliases (`hh hho bd sn t1 t2 ft rd rb cr cr2 cs hf`...).

## Symbols
`- .` rest · `x` stroke · `X >` accent · `g` ghost · `o` open hi-hat (hh line) ·
`h` half-open hi-hat · `f` flam · `F` accented flam · `d` drag · `r` roll (`~`
extends it) · `c` choke.

## Validation (errors are explicit)
Unknown symbols, wrong beat-segment counts, unknown patterns, positions outside
the bar, conflicting hi-hat states on one beat, accent and ghost together,
rolls past the barline, and rhythms finer than 32nds/sextuplets
(e.g. quintuplets) are all rejected with a message naming the bar.
