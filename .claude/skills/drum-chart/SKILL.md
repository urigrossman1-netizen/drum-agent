---
name: drum-chart
description: >-
  Create professionally engraved drum sheet music (PDF, MusicXML, MIDI) from an
  audio recording, a MIDI drum track, or a described groove or arrangement, and
  verify it. Use when the user asks for a drum chart, drum transcription, drum
  sheet music, drum notation, a drum part or drum-book page for a song, or wants
  an existing drum chart checked or fixed.
when_to_use: >-
  Requests like: transcribe the drums in this song; write out this beat; make a
  drum chart for my song; drum sheet music; notate this groove; turn this MIDI
  drum track into a chart; my chart has the wrong kick pattern in bar 12.
argument-hint: "[audio/MIDI/chart file or description]"
---

# Drum chart

You produce real, engraved drum notation with the Drum Agent in this repository
(`python -m drum_agent`, run from the repository root). Every chart is engraved
by LilyPond from one structured score (`score.json`) and exported to PDF,
MusicXML and MIDI, which are checked against each other automatically.

## Non-negotiables

1. **The deliverable is the engraved PDF/MusicXML.** Never present ASCII grids,
   text beat descriptions, or your own drawings as the chart. Chart-spec grids
   are an *input* format only.
2. **Never invent notes.** If the audio doesn't support a stroke, it doesn't go
   on the page. Unclear bars stay flagged "(?)" until someone listens.
3. **Rights before transcription.** Note-for-note transcription of a recording
   needs `--rights` with one of: `own` (the user made or owns the recording),
   `permission` (the rights holder allowed it), `licensed` (a licence covers
   transcription), `public_domain`, `original` (the user's own composition).
   Use a value only when the user's words support it. If they don't: ask which
   applies, offer `analyze` (tempo, meter, form; no notes) and run it only if
   they accept or only asked for those, and offer to help find a licensed chart
   (ask for title and artist; suggest the publisher's official transcription or
   an authorised sheet-music retailer; don't claim a specific chart exists
   unless you checked). Never download from streaming sites or bypass DRM.
4. **Rendering correctness is not transcription correctness.** "All checks OK"
   means the formats agree with score.json. It does not mean the notes match the
   recording. Say which one you've verified.
5. **Label the chart honestly.** Chart type: `full_transcription` (every bar
   transcribed), `performance_chart` (grooves and roadmap, not note-for-note) or
   `pattern_study`. Status is set by the input path: `unverified_auto` (audio),
   `unverified_import` (MIDI), `entered` (a chart spec you or the user wrote).
   Only a human who checked it against the recording makes it `verified`
   (`edit --verified`); never call a chart "verified" yourself.
6. **Header text comes from the user.** Title, artist and transcriber only from
   the user's own words; omit what they didn't give. List any header or label
   text you chose (title, section names, feel) as an assumption.

## Workflow

### 0. Environment
Run `python -m drum_agent doctor`. If LilyPond is missing, install it
(`scripts/install_lilypond.sh`, or `apt-get install lilypond` for 2.24+).
Don't work around a missing engine.

### 1. Decide the input path and chart type

| The user has... | Do | Chart type / status |
|---|---|---|
| Audio they may transcribe (rights stated) | `transcribe AUDIO --rights R -o OUT` | full_transcription / unverified_auto |
| Audio, rights unclear | ask; offer `analyze AUDIO` (see rule 3) | none |
| A MIDI drum track (e-kit, DAW) | `midi FILE.mid -o OUT`: exact strokes, but the bar grid still needs checking | full_transcription / unverified_import |
| A described groove or arrangement | write a chart spec, `render SPEC.yaml -o OUT` | performance_chart or pattern_study / entered |
| An existing score.json to fix | `edit score.json ... --render OUT` | unchanged |

If the request is ambiguous (full transcription or performance chart? paper
size? section names?), choose the conventional default and say so.

### 2. Produce the score
Audio:
```bash
python -m drum_agent transcribe song.wav --rights own --title "Song" --artist "Band" -o out/song
```
Hints that change the result; use them when you have evidence:
`--drums-only` (isolated drum stem, much more accurate), `--bpm 96`,
`--time-signature 6/8`, `--downbeat 1.23` (seconds of a beat 1),
`--sections "Intro:1,Verse:5,Chorus:13"` (score.json bar numbers),
`--start/--end` (a passage), `--sensitivity 1.3` (soft playing).
Read [reference/transcription-guide.md](reference/transcription-guide.md)
before your first audio transcription in a session: it lists what the
detector misses.

MIDI:
```bash
python -m drum_agent midi take.mid --title "Take" -o out/take
```
The importer reads pickups (a short opening meter, or meter changes and markers
that sit off the barlines) and uses the file's markers as section names. A
pickup it can't infer shifts every bar: pass `--pickup 1/4` (length in whole
notes). Check the `pickup:` line and every warning it prints.

Described groove: see "Writing a chart by hand" below.

### 3. Read the report, after every render
Open `OUT/<stem>.report.md` with the Read tool every time you render, not just
the console lines. Check, in this order:
1. **Rendering correctness**: every check OK (notes, tempo map, meters,
   barlines, articulations) and the MusicXML schema valid. If not, stop and
   fix it (see troubleshooting).
2. **The grid**: `tempo ambiguous`, `meter uncertain`, `downbeat placement
   uncertain`, a `pickup` line, and any "falls inside a bar" warning. A wrong
   grid is the most damaging error, because every bar inherits it.
3. **Warnings**, e.g. the kick-density (bass bleed) warning.
4. **Flagged bars**, listed as `printed (score.json)` pairs with reasons.
5. **Instrument counts** for plausibility: toms in a song with no fills?
   Hundreds of kicks?

### 4. Look at every page
Read each `OUT/<stem>.png` or `OUT/<stem>-pageN.png` with the Read tool.
First, the downbeat test on page 1:
- Is the backbeat on 2 and 4 (rock, pop, funk)?
- Do crashes and section starts fall on beat 1?
- Do fills lead into a downbeat, rather than start one?

If any answer is no, the bar grid is wrong; fix that before anything else
(transcribe with `--bpm`/`--downbeat`, MIDI with `--pickup`).

Then open [reference/qc-checklist.md](reference/qc-checklist.md) with the
Read tool and go through every item. A chart that verifies but reads badly is
not done. In your delivery, name any item that failed or that you could not
check.

### 5. Correct, then re-render
- **Grid problems**: re-run with `--bpm`, `--time-signature`, `--downbeat` or
  `--pickup`. Don't hand-edit around a wrong grid.
- **Local problems**: use `edit` with exact references, then re-render:
  ```bash
  python -m drum_agent edit out/song/song.json --relabel ride=hihat --bars 9-16 \
      --delete 12:7/8:kick --add 12:3/8:snare:ghost --render out/song
  ```
  `BAR:POS:INST`: BAR is the score.json bar (the second number in the report).
  POS is in whole notes from beat 1: `1/4` is beat 2, `3/8` is the "and" of 2
  in 4/4.
- **After someone verified bars by ear**: `edit ... --verified 9-16`.

Then go back to step 3: read the new report and the new pages.

### 6. Deliver
Report:
- the PDF, MusicXML and MIDI paths;
- chart type and status, in plain words;
- what was verified automatically (format agreement, schema) versus not
  (whether the notes match the recording);
- flagged bars, quoted as printed on the chart, with the score.json number in
  parentheses where they differ ("bars 18-21 (score.json 22-25)"). Take numbers
  from the report; never estimate them;
- assumptions: tempo, meter, section names, header text, and choices you made
  that the request didn't specify;
- QC items that failed or couldn't be checked.

## Writing a chart by hand (chart spec)
For grooves, exercises and performance charts, write YAML and render it. The
format, symbols and examples from simple to full song are in
[reference/chart-spec.md](reference/chart-spec.md) and
[reference/examples.md](reference/examples.md). Rules:
- One string per instrument per bar. Every line of a bar must fit the meter:
  in 4/4, 4, 8, 12, 16, 24, 32 or 48 characters. With 16ths, write
  `"xxxx|xxxx|xxxx|xxxx"`: `|` splits beats, which makes miscounts obvious and
  lets each beat have its own subdivision (`"xxx|x-x|xxxx|r~~~"`).
- Write fills and variations out; never repeat a groove over a fill. The
  engraver compresses only *identical* bars into simile marks and repeats.
- Put the requested style or feel on the chart with `tempo_text` (Funk,
  Half-time feel, Shuffle, Swing).
- A performance chart must say so (`chart_type: performance_chart`).
- Then do steps 3 to 6 exactly as for audio: read the report, read every page,
  go through the QC checklist, deliver with assumptions.

## Notation standard
Weinberg / Percussive Arts Society layout: hands stems up, feet stems down.
The full map is in [reference/notation.md](reference/notation.md); the
authoritative spec is `docs/NOTATION_SPEC.md`. Don't override positions unless
the user asks; then use `--kit my_kit.json`, and the Drum Key on page 1 will
show the change.

## When things go wrong
See [reference/troubleshooting.md](reference/troubleshooting.md): LilyPond
errors, verification mismatches, unsupported rhythms (quintuplets), chart-spec
grid errors, MIDI without channel 10 or with a pickup, slow or noisy audio.
