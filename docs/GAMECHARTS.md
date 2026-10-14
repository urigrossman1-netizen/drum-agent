# Game charts (Rock Band / Clone Hero)

`python -m drum_agent gamechart` engraves the drum part of a rhythm-game chart
you supply: a `notes.mid`, a `notes.chart`, or the song folder holding one.

```bash
python -m drum_agent gamechart "songs/My Song" -o out/mysong
python -m drum_agent gamechart notes.chart --difficulty hard --title "Song" -o out/song
python -m drum_agent gamechart notes.mid --no-pro --sections "Intro:1,Verse:5" -o out/song
```

Options: `--difficulty expert|hard|medium|easy` (default expert), `--no-pro`,
`--title`, `--artist`, `--transcriber`, `--rights`, `--feel`, `--sections`,
plus the export options shared with `render` and `midi` (`--formats`,
`--paper`, `--repeats`, `--kit`, `--voicing`, ...). The chart is written as a
full transcription with the status *imported, unverified*.

## How it is read

The chart's own tempo map and meters make the beat grid, and the strokes go
through the same quantizer as a MIDI import (`drum_agent/gamechart.py`,
modelled on `io_midi.py`), so every position is a spellable note value.

| Pad | Drum kit | MIDI note (Expert / Hard / Medium / Easy) | `.chart` lane |
|---|---|---|---|
| kick | bass drum | 96 / 84 / 72 / 60; 95 = Expert+ kick | 0; 32 = Expert+ kick |
| red | snare | 97 / 85 / 73 / 61 | 1 |
| yellow | hi-hat (cymbal) or tom 1 | 98 / 86 / 74 / 62 | 2 |
| blue | ride (cymbal) or tom 2 | 99 / 87 / 75 / 63 | 3 |
| green | crash (cymbal) or floor tom | 100 / 88 / 76 / 64 | 4 |

* **Cymbal or tom.** MIDI: yellow, blue and green are cymbals unless a tom
  marker (110 yellow, 111 blue, 112 green) is held at that tick. `.chart`:
  they are toms unless a cymbal flag (66 yellow, 67 blue, 68 green) sits at
  that tick.
* **Pro drums default.** A MIDI file without a single tom marker is an older,
  non-pro chart: yellow, blue and green are read as toms (the report says so
  and shows the `edit --relabel` that turns them into cymbals). `pro_drums =
  True` in song.ini turns the cymbal reading on. `--no-pro` forces toms in
  either format.
* **Dynamics.** MIDI: only with the text event `[ENABLE_CHART_DYNAMICS]` in
  the drum track, velocity 127 is an accent and velocity 1 a ghost note (not
  on the kick). `.chart`: accent flags 34-37 and ghost flags 40-43 (red,
  yellow, blue, green).
* **Disco flip.** `[mix N drums0d]` (N = 0 Easy to 3 Expert) swaps red and the
  yellow cymbal until the next `[mix N drums0]`, in a pro reading only;
  `drums0dnoflip` doesn't swap.
* **Meters, tempo, sections.** Meter and tempo come from the conductor track
  (MIDI) or `[SyncTrack]` (`B` = BPM x 1000, `TS 6 3` = 6/8). A meter event
  inside a bar starts a new bar there, as in the games, so the cut bar gets
  the meter of its length (a 4/4 bar cut after three beats is 3/4). Tempo
  marks go on barlines where the tempo moved by 2% or more, so a chart
  beat-mapped to a recording doesn't print a mark every bar. Sections come
  from the `EVENTS` track (`[section Verse 1]`, `[prc_verse_1]`) or `[Events]`
  (`section Verse 1`) and sit on the nearest barline. Empty bars before the
  drums come in are left out (the report says how many).
* **Metadata.** Title, artist and charter come from your options, then
  song.ini, then the `.chart`'s `[Song]` block, else the folder name. Nothing
  is looked up anywhere.

## What a game chart can't tell you

Game charts are simplified, and the report says so: one lane per pad colour,
so every yellow cymbal is a closed hi-hat (no open/closed, no hi-hat pedal),
cymbal identity is a guess (blue = ride, green = crash), and accents and ghost
notes exist only where the chart has dynamics. Not read: flam markers, drum
roll and swell lanes, star power, solos, fills and big-rock endings. Five-lane
charts (a second green lane) are refused. A `.sng` package must be extracted
first. Check the chart against the recording, and correct it with
`python -m drum_agent edit`.

Like `midi`, this converts strokes someone has already charted; no audio is
opened. Use `--rights` to record the basis on which you're making the chart.
