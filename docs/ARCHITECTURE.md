# Architecture

```
 audio file ──► audio/detect ──► audio/beats ──► quantize ──┐
 MIDI file  ──► io_midi ─────────────────────► quantize ──┤
 chart spec ──► charts ──────────────────────────────────┤
 score.json ──► model.Score.load ─────────────────────────┤
                                                          ▼
                                       IR: model.Score (score.json)
                                                          │
                       layout.plan_layout (repeats, line breaks)
                                                          │
                ┌──────────────────────┬──────────────────┼─────────────────┐
                ▼                      ▼                  ▼                 ▼
        export/lilypond         export/musicxml      export/midi      pipeline report
        (rhythm.spell_measure)  (rhythm.spell_measure)
                │                      │                  │
        export/render (LilyPond 2.26 → PDF, PNG, MIDI)    │
                │                      │                  │
                └────────── verify: read every output back and compare with the IR
```

## One source of truth

`drum_agent/model.py` defines the IR:

- `Score`: measures plus metadata (title, artist, transcriber, `chart_type`,
  `status`, `rights`, source, analysis results).
- `Measure`: time signature (with beat groups for 7/8 etc.), optional
  length (pickup), tempo/tempo text, section label, `uncertain` flag plus
  notes explaining why.
- `Hit`: position as an exact `Fraction` of a whole note from the start of
  the bar, instrument id, velocity, accent/ghost/flam/drag/roll/choke,
  confidence, and the performed time and offset (for audio and MIDI
  sources).

Floats are rejected for positions. `Score.validate()` enforces the invariants:
positions inside the bar, no duplicate strokes, no conflicting hi-hat states
at one moment, rolls that stay inside the bar, pickups only in bar 1.
Every renderer reads this structure and nothing else; no output format
re-derives rhythm on its own.

## Instruments: `kit.py`

One table maps each instrument to staff position, notehead, voice, GM MIDI
note and aliases (`hh`, `bd`, `sn`, ...). The LilyPond drum style, the
MusicXML instrument list, the MIDI map, the Drum Key and the chart-spec
names are all generated from it. `--kit file.json` overrides entries;
`tests/test_kit.py` pins the table to `docs/NOTATION_SPEC.md`.

## Rhythm spelling: `rhythm.py`

`spell_measure` turns a bar of hits into tokens per voice (notes, chords,
rests, tuplets, beams, ties):

- Per beat it picks the simplest grid that holds the strokes: 8ths, 16ths,
  32nds, triplets, sextuplets; in compound beats, 8ths/16ths and duplets. Two
  beats become a quarter-note triplet only for a real triplet figure.
- A note lasts until the next stroke in its voice or the end of its beat.
  Drum notes aren't tied, except rolls, which merge into half/dotted-half
  notes where that doesn't hide a beat.
- Rests follow the bar > half-bar > beat hierarchy.
- Beams group by beat; plain 8ths in 4/4 beam in fours.

LilyPond and MusicXML both consume these tokens, so the PDF and the MusicXML
can't disagree about how a rhythm is written.

## Layout: `layout.py`

- Repeat compression: bars identical to the previous one become simile
  marks (with counts); a phrase of 2, 4 or 8 bars that repeats becomes a
  repeat with "×N" (the phrase that saves the most written bars, the shorter
  one on a tie). Two or more empty bars become one multi-bar rest. Section
  starts, tempo or meter changes and flagged bars are never compressed.
- Line breaking: a dynamic program balances systems (about 4 bars per line,
  simile bars counting less, a multi-bar rest as one bar and never split).
  Each section starts a system; a short section shares a line only when the
  whole next section fits after it, or joins the end of the previous line.
- `plan.expand()` must reproduce the original bar sequence, which is asserted.

## Exporters: `export/`

- `lilypond.py` writes the `.ly`: generated drum style and MIDI map, header
  with chart type and status, paper, Drum Key, two voices plus a global voice
  for structure, and a second unfolded `\score` with `\midi` used only for
  verification.
- `render.py` runs LilyPond. A missing engine, an old version, a non-zero
  exit, missing output or fatal warnings (bar-check failures and similar)
  raise `RenderError` with the log. There is no fallback renderer.
- `musicxml.py` writes partwise MusicXML 4.0: unpitched notes with display
  steps, noteheads, explicit beams, tuplets, graces, tremolos, technical
  marks, repeats, measure repeats, tempo, credits and system breaks.
- `midi.py` writes GM drums on channel 10 from the expanded IR (`quantized`
  timing, or `performed` timing for transcriptions).

## Verification: `verify.py`

After every export, three comparisons run against the IR's expected events
(bar, position, instrument):

1. LilyPond's own MIDI output from the unfolded score, which tests the
   engraving source.
2. The MusicXML read back with repeats expanded, after it has validated
   against the vendored MusicXML 4.0 XSD.
3. Our MIDI file.

Any mismatch raises `ExportError`. The report shows these as **rendering
correctness**, separately from **transcription confidence**.

`pipeline.export_all` orchestrates this. It also pulls a near-empty last page
back onto the previous page when LilyPond can do it with little compression.

## Audio transcription: `audio/`

| Stage | Module | Method |
|---|---|---|
| Front end | `features.py` | 44.1 kHz mono, 96-band mel spectrogram (hop 256), frames stacked at 0, +17, +46 ms |
| Detection | `detect.py` | Superflux onsets; semi-adaptive KL-NMF with 68 drum templates from FluidSynth GM kits plus a frozen accompaniment basis learned from the harmonic part (HPSS) |
| Classification | `detect.py` | activation share per instrument region, adaptive (Otsu) floors, rules (one cymbal per stroke, two hands, toms need tom energy, crash-on-snare), hi-hat open/closed by decay, flam graces, accents and ghosts relative to local dynamics, confidence |
| Grid | `beats.py` | drum-weighted beat tracking, tempo candidates scored by grid fit, backbeat and prior; meter by repetition; downbeat by kick/crash/backbeat placement |
| Quantization | `quantize.py` | per-beat grid choice by timing error plus complexity, swing/triplet feel, tempo map, uncertain-bar flags |
| Structure | `structure.py`, `transcribe.py` | sections at groove/meter changes, 12/8 section refinement, roll notation, bass-bleed warning |

Templates are rebuilt by `scripts/build_templates.py`. Accuracy is measured,
not assumed: `scripts/eval_detection.py` (onset level) and
`scripts/eval_notation.py` (end to end, notation level) render charts with
known content to audio and score the transcription. See `LIMITATIONS.md`.

## Inputs other than audio

- `io_midi.py`: GM drum tracks (channel 10 by default), using the file's
  tempo map, through the same quantizer.
- `charts.py`: YAML/JSON chart specs for hand-written charts, exercises,
  tests and examples.
- `edit.py`: exact, reference-based corrections to a score.json (the
  human-in-the-loop step after listening).

## Rights

`rights.py` gates note-for-note transcription of recordings: `transcribe`
needs `--rights own|permission|licensed|public_domain|original`, checked
before the audio is opened. `analyze` reports tempo, meter and form only.

## Files

```
drum_agent/        package (cli.py is the entry point: python -m drum_agent)
  export/          LilyPond, MusicXML, MIDI writers and the LilyPond runner
  audio/           transcription
  schemas/         MusicXML 4.0 XSD (validation)
  data/            NMF drum templates
docs/              NOTATION_SPEC.md, ARCHITECTURE.md, AUDIT.md, LIMITATIONS.md
tests/             pytest suite; cases/ = notation regression charts; audio_cases/
examples/          specs/ (original charts) and output/ (rendered PDF/PNG/MusicXML/MIDI)
scripts/           install_lilypond.sh, build_templates.py, eval_detection.py, eval_notation.py
.claude/skills/drum-chart/   the Claude Code skill (SKILL.md + reference/)
```
