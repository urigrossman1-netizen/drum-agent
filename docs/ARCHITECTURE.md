# Architecture

```
 song name  ──► song (identify, find audio; rights gate) ──┐
 audio file ──► audio/detect ──► audio/beats ──► quantize ◄┘─┐
 MIDI file  ──► io_midi ─────────────────────► quantize ────┤
 game chart ──► gamechart (notes.mid / notes.chart) ► quantize┤
 chart spec ──► charts (and library/*.yaml) ────────────────┤
 score.json ──► model.Score.load ───────────────────────────┤
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
note and aliases (`hh`, `bd`, `sn`, ...). Two voicings decide the stems:
`cymbals-up` (the default: hi-hat and cymbals up; snare, toms and feet down,
the Guitar Pro / Songsterr look) and `hands-up` (Weinberg/PAS: everything the
hands play up, the feet down), chosen with `--voicing`. The LilyPond drum style, the
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
- Beams group by beat; plain 8ths in 4/4 beam in fours. A tuplet beamed
  together is marked to show its number without a bracket.

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
- A bar's width is estimated from its densest voice, its ghost notes
  (parentheses) and its sticking letters; dense bars get fewer per line.
- `plan.expand()` must reproduce the original bar sequence, which is asserted.

## Exporters: `export/`

- `lilypond.py` writes the `.ly`: generated drum style and MIDI map, header
  with chart type and status, paper, Drum Key, two voices plus a global voice
  for structure (cues, tempo marks with the swing figure), a sticking line
  (a NullVoice with lyrics under the staff), and a second unfolded `\score`
  with `\midi` used only for verification. A chart with one voice only (a
  snare rudiment) is engraved as one voice, stems up, with no rests for the
  empty one; only a bar whose roll moved up over the kick has two voices
  (the hands up, the feet down).
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
back onto the previous page when LilyPond can do it with little compression,
and measures each rendered page: LilyPond gives no warning when a line is too
dense to fit, so a line whose staff reaches into the right margin (or is cut
off at the page edge) is re-planned with fewer bars per line, a quarter fewer
at a time down to one bar per line. Only staff lines are measured: a title too
wide for the page is not a line of music. Each new set of line breaks is tried
in a scratch directory, at most four of them; the first that fits is kept,
otherwise the one that comes closest (between two cut off at the page edge,
the one with fewer bars per line), and a line that still doesn't fit is
reported. `playability.py` lists strokes one
drummer can't play together (three hands, two left-foot strokes, an open hat
as the foot closes it); in transcriptions those bars are flagged.

## Audio transcription: `audio/`

| Stage | Module | Method |
|---|---|---|
| Front end | `features.py` | 44.1 kHz mono, 96-band mel spectrogram (hop 256), frames stacked at 0, +17, +46 ms |
| Candidates | `detect.py` | Superflux onsets on the (percussive part of the) spectrogram: high recall, 86-100% of every class on real recordings |
| Classification | `classifier.py` | a small neural network (1300 level-invariant log-mel features per candidate, 11 classes) trained on synthesized drumming from 40+ sampled kits (docs/MODELS.md); rules after it: one hi-hat state, two hands, pedal under a stick stroke; toms named by NMF evidence or per-recording pitch; flams from grace energy; accents and ghosts from each drum's typical level |
| Classification (`--detector nmf`) | `detect.py` | the original: semi-adaptive KL-NMF with 68 GM-kit templates plus an accompaniment basis, activation shares, adaptive floors and rules |
| Grid | `beats.py` | drum-weighted beat tracking, tempo candidates scored by grid fit, backbeat and prior (roll and grace strokes don't count as pulse; near ties between metrical levels are ranked by a constant grid); meter by repetition; downbeat by kick/crash/backbeat placement |
| Quantization | `quantize.py` | per-beat grid choice by timing error plus complexity, swing/triplet feel, tempo map, uncertain-bar flags |
| Structure | `structure.py`, `transcribe.py` | sections at groove/meter changes, 12/8 section refinement, roll notation, bass-bleed warning |

Templates are rebuilt by `scripts/build_templates.py`. Accuracy is measured,
not assumed: `scripts/eval_detection.py` (onset level) and
`scripts/eval_notation.py` (end to end, notation level) render charts with
known content to audio and score the transcription. See `LIMITATIONS.md`.

## Inputs other than audio

- `io_midi.py`: GM drum tracks (channel 10 by default), using the file's
  tempo map, through the same quantizer.
- `gamechart.py`: Rock Band / Clone Hero drum charts (notes.mid, notes.chart,
  song.ini): pads to instruments (pro drums, disco flip, dynamics), the
  chart's own tempo map and meters; its ticks are exact, so a beat keeps the
  grid most of its ticks sit on, even with one a few ticks off. See
  `docs/GAMECHARTS.md`.
- `song/`: from a song's name to audio: metadata (MusicBrainz, iTunes,
  Deezer), the user's own library (by tags), a direct link, or a video page
  through the user's own yt-dlp. Streaming services are metadata only. See
  `docs/SONG_LOOKUP.md`.
- `charts.py`: YAML/JSON chart specs for hand-written charts, exercises,
  tests and examples.
- `edit.py`: exact, reference-based corrections to a score.json (the
  human-in-the-loop step after listening).

## Rights

`rights.py` gates note-for-note transcription of recordings: `transcribe`
needs `--rights own|permission|licensed|public_domain|original`, checked
before the audio is opened (and, in `song`, before anything is downloaded
for it). `analyze` reports tempo, meter and form only.

## The chart library

`library/rudiments` (the 40 PAS International Drum Rudiments, sticking under
every stroke) and `library/grooves` (73 grooves and fills across styles and
meters) are chart specs like any other: original pattern studies, held to
the house rules and engraved with every check passing by
`tests/test_library.py`.

## Files

```
drum_agent/        package (cli.py is the entry point: python -m drum_agent)
  export/          LilyPond, MusicXML, MIDI writers and the LilyPond runner
  audio/           transcription
  schemas/         MusicXML 4.0 XSD (validation)
  data/            onset classifier weights, NMF drum templates
  song/            song lookup and audio acquisition
library/           rudiments/ and grooves/: the 113-chart library
docs/              NOTATION_SPEC.md, ARCHITECTURE.md, AUDIT.md, LIMITATIONS.md
tests/             pytest suite; cases/ = notation regression charts; audio_cases/
examples/          specs/ (original charts) and output/ (rendered PDF/PNG/MusicXML/MIDI)
scripts/           install_lilypond.sh, build_templates.py, eval_detection.py, eval_notation.py,
                   eval_real.py (MDB Drums), adt/ (training data and classifier training)
.claude/skills/drum-chart/   the Claude Code skill (SKILL.md + reference/)
```
