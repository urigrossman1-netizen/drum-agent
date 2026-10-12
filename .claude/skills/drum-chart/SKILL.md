---
name: drum-chart
description: Create professionally engraved drum sheet music (PDF, MusicXML, MIDI) from an audio recording, a MIDI drum track, or a described groove/arrangement, and verify it against the source. Use when the user asks for a drum chart, drum transcription, drum sheet music, drum notation, a drum part or drum book page for a song, or to check or fix an existing drum chart.
when_to_use: "transcribe the drums in this song", "write out this beat", "make a drum chart for", "drum sheet music", "notate this groove", "turn this MIDI drum track into a chart", "my chart has the wrong kick pattern in bar 12".
argument-hint: "[audio/MIDI/chart file or description]"
---

# Drum chart

You produce real, engraved drum notation with the Drum Agent in this repository
(`python -m drum_agent`). Every chart is engraved by LilyPond from one structured
score (`score.json`) and exported to PDF, MusicXML and MIDI, which are checked
against each other automatically.

## Non-negotiables

1. **The deliverable is the engraved PDF/MusicXML.** Never present ASCII grids,
   text beat descriptions, or your own drawings as the chart. Chart-spec grids
   are an *input* format only.
2. **Never invent notes.** If the audio doesn't support a stroke, it doesn't go
   on the page. Unclear bars stay flagged "(?)" until someone listens.
3. **Rights before transcription.** Note-for-note transcription of a recording
   requires `--rights` (own, permission, licensed, public_domain, original). If
   the user can't confirm one, offer `analyze` (tempo/meter/form only) or point
   them to a licensed chart. Never download from streaming sites or bypass DRM.
4. **Rendering correctness is not transcription correctness.** "All checks OK"
   means the formats agree with score.json. It does not mean the notes match the
   recording. Say which one you've verified.
5. **Label the chart honestly**: `full_transcription` (every bar transcribed),
   `performance_chart` (grooves + roadmap, not note-for-note) or
   `pattern_study`. An automatic transcription stays `unverified_auto` until a
   human has checked it.

## Workflow

### 0. Environment
Run `python -m drum_agent doctor`. If LilyPond is missing, install it
(`scripts/install_lilypond.sh` or `apt-get install lilypond`). Don't work
around a missing engine.

### 1. Decide the input path and chart type

| The user has... | Do | Chart type |
|---|---|---|
| An audio file they may transcribe | `transcribe AUDIO --rights R -o OUT` | full_transcription |
| An audio file without rights | `analyze AUDIO` (no notation) | none, offer a licensed chart |
| A MIDI drum track (e-kit, DAW) | `midi FILE.mid -o OUT` (most accurate) | full_transcription |
| A described groove / arrangement | write a chart spec, `render SPEC.yaml -o OUT` | performance_chart or pattern_study |
| An existing score.json to fix | `edit score.json ... --render OUT` | unchanged |

If the request is ambiguous (full transcription or performance chart? what
paper size? section names?), choose the conventional default and say so.
Ask only if rights are unclear.

### 2. Transcribe (audio)
```bash
python -m drum_agent transcribe song.wav --rights own --title "Song" --artist "Band" -o out/
```
Useful hints, all of which change the result. Use them when you have evidence:
- `--drums-only`: the file is an isolated drum stem (much more accurate).
- `--bpm 96`, `--time-signature 6/8`, `--downbeat 1.23` (seconds of a beat 1).
- `--sections "Intro:1,Verse:5,Chorus:13"` (score.json bar numbers).
- `--start/--end` seconds to work on a passage; `--sensitivity 1.3` for soft playing.

The audio method and its measured accuracy are in
[reference/transcription-guide.md](reference/transcription-guide.md). Read it
before your first transcription in a session.

### 3. Read the evidence
Open `out/<stem>.report.md`. Check, in this order:
1. **Rendering checks**: all three comparisons OK and the MusicXML schema valid.
   If not, stop and fix (see troubleshooting).
2. **Tempo/meter/downbeat**: `tempo ambiguous`, `meter uncertain` and `downbeat
   placement uncertain` notes mean the grid itself may be wrong. That's the most
   damaging error, because every bar inherits it.
3. **Warnings**, e.g. the kick-density (bass bleed) warning.
4. **Flagged bars**, listed as `printed (score.json)` pairs, with reasons.
5. **Instrument counts** for plausibility (toms in a song with no fills?
   hundreds of kicks?).

### 4. Look at every page
Read each `out/<stem>-page*.png` (or `<stem>.png`) with the Read tool. Go
through [reference/qc-checklist.md](reference/qc-checklist.md): clef, staff
positions, voices, beams, rests, tuplets, articulations, section labels,
repeats, spacing, page turns. A chart that verifies but reads badly is not done.

### 5. Correct, then re-render
- Grid problems: re-run `transcribe` with `--bpm`, `--time-signature` or
  `--downbeat`. Don't hand-edit around a wrong grid.
- Local problems: `edit` with exact references, then re-render:
  ```bash
  python -m drum_agent edit out/song.json --relabel ride=hihat --bars 9-16 \
      --delete 12:7/8:kick --add 12:3/8:snare:ghost --render out/
  ```
  `BAR:POS:INST`: BAR is the score.json bar (second number in the report),
  POS in whole notes from beat 1 (`1/4` = beat 2, `3/8` = "and" of 2 in 4/4).
- After the user or you verify bars by ear: `edit ... --verified 9-16`.
Repeat steps 3 to 5 until the checks pass and the pages read cleanly.

### 6. Deliver
Report: the PDF/MusicXML/MIDI paths, chart type and status, what was verified
automatically (format agreement, schema) versus not (whether the notes match the
recording), the flagged bars, and any assumptions (tempo, meter, section names).

## Writing a chart by hand (chart spec)
For grooves, exercises and performance charts, write YAML and render it. The
format, symbols and examples from simple to full song are in
[reference/chart-spec.md](reference/chart-spec.md) and
[reference/examples.md](reference/examples.md). Rules:
- One string per instrument per bar; `|` splits beats so each beat can have its
  own subdivision (`"xxx|x-x|xxxx|r~~~"`).
- Write fills and variations out; never repeat a groove over a fill. The
  engraver compresses only *identical* bars into simile marks and repeats.
- A performance chart must say so (`chart_type: performance_chart`).

## Notation standard
Weinberg / Percussive Arts Society layout; hands stems-up, feet stems-down. The
full map is in [reference/notation.md](reference/notation.md); the authoritative
spec is `docs/NOTATION_SPEC.md`. Don't override positions unless the user asks;
then use `--kit my_kit.json`, and the Drum Key on page 1 will show the change.

## When things go wrong
See [reference/troubleshooting.md](reference/troubleshooting.md): LilyPond
errors, verification mismatches, unsupported rhythms (quintuplets), MIDI
without channel 10, slow or noisy audio.
