# Measured accuracy and limitations

Two different questions, two different answers:

- **Is the engraving right?** Every export is checked automatically against
  the score it was made from: LilyPond's own MIDI, the MusicXML (notes,
  articulations, meters, schema) and our MIDI (notes, tempo map, barlines).
  For hand-written charts and MIDI input this makes the PDF/MusicXML/MIDI
  trustworthy, and 441 automated tests (including random-score fuzzing) back
  it up.
- **Are the notes right?** For audio this can only be measured where the
  answer is known. All numbers below come from **synthesized** recordings of
  original charts (FluidSynth General MIDI kits, optional bass and keys,
  optional humanized timing). Real recordings are harder: room sound,
  compression, real cymbals and a full mix. Expect lower accuracy there and
  listen to every chart before relying on it.

## Audio transcription, measured

### Notation level (scripts/eval_notation.py)
Notation F counts a stroke as right only if it is in the right bar, at the
right position, on the right instrument. Ten charts, four conditions each:

| Chart | Standard kit, drums only | Jazz kit (held out), drums only | Standard kit + bass/keys | Jazz kit + bass/keys, ±8 ms humanized |
|---|---|---|---|---|
| 02 eighth-note rock | 1.000 | 1.000 | 1.000 | 1.000 |
| 03 16th syncopation | 0.981 | 1.000 | 1.000 | 0.954 |
| 05 open/closed/half-open hi-hat | 0.979 | 0.979 | 0.946 | 0.644 |
| 06 tom fill over the barline | 1.000 | 1.000 | 0.973 | 0.974 |
| 07 ghosts, accents, flams, rolls | 0.273 * | 0.273 * | 0.270 * | 0.889 |
| 10 pickup, 12/8 bridge, tempo change | 0.938 | 0.938 | 0.924 | 0.775 |
| 11 tom grooves and fills | 0.936 | 0.914 | 0.888 | 0.902 |
| 12 two short bars (2/4, 3/4) | 0.994 | 1.000 | 0.989 | 0.788 |
| 13 crash accents on beat 3 | 0.991 | 0.972 | 0.948 | 0.952 |
| Northbound, full 60-bar song | 0.982 | 0.983 | 0.972 | 0.948 |

Mean 0.897, median 0.972 over the 40 runs.

\* Case 07 is read at double tempo without a hint (see below). With
`--bpm 92` it scores 0.85 or more (tested in `tests/test_audio_e2e.py`).

### Stroke level (scripts/eval_detection.py)
Onset F at 50 ms, pooled over six charts (722 strokes per condition):

| Condition | Overall | Weak classes |
|---|---|---|
| Standard kit, drums only | 0.988 | crash 0.85, floor tom 0.80 |
| Room kit, drums only | 0.978 | floor tom 0.57, crash 0.77, open hi-hat 0.80 |
| Jazz kit (held out), drums only | 0.989 | open hi-hat 0.88 |
| Brush kit (held out), drums only | 0.965 | snare 0.92 (soft brushes), floor tom 0.73 |
| Standard kit + bass/keys | 0.973 | crash 0.51, open hi-hat 0.62 |
| Jazz kit + bass/keys, ±10 ms humanized | 0.900 | crash 0.30, open hi-hat 0.22, floor tom 0.73 |
| Unfamiliar synthetic timbres (numpy kit) | 0.610 | snare 0.16, cymbals ~0.1, toms 0.0 |

### Review flags
Bars marked "(?)" are those with low-confidence strokes or a structural
decision (e.g. an inserted short bar). Across the runs above, 52% of
flagged bars contained an error and flags caught 44% of the wrong bars.
**Flags help you find problems; they don't replace listening to every bar.**

### Long recordings
An 8.5-minute band mix (`scripts/stress_long.py`) took 195 s and peaked at
1.1 GB of memory on a 4-CPU machine (3 minutes: about 80 s, 0.6 GB). It
reached notation F 0.967, with all three 2/4 bars found and every
cross-format check passing. Memory grows with length; very long files
(20+ minutes) need several GB.

### Real recordings
Tested on three Creative Commons recordings from librosa's example data. There
is no ground truth, so only what the report says was checked:
- **Drums and bass (Admiral Bob, "Choice"; CC BY-NC).** Called 3/4 at 102 BPM
  with 136 BPM nearly as plausible (a 4:3 tempo confusion), and 13 of 15 bars
  flagged. The report does warn that this chart can't be trusted, but the grid
  is probably wrong: run it again with `--bpm`/`--time-signature` from
  listening.
- **Accelerating solo snare (Brian McFee; CC BY 4.0).** 50 snare strokes,
  2 bars flagged; tempo and meter ambiguity reported. With a steadily
  changing tempo the bar grid is approximate.
- **A waltz (Setuniman, "sweet waltz"; CC BY-NC).** Pattern repetition
  slightly favoured 3 beats (0.65 vs 0.58), but not by the required margin,
  so it was called 4/4 with "meter uncertain". With `--time-signature 3/4` it
  comes out as 31 bars of 3/4. This case is why the "meter uncertain"
  threshold is 0.7.

Charts of non-commercial-licensed material are not committed.

## Known limitations
1. **Hi-hat pedal strokes are not detected** (no detector class). Add them
   with `edit --add`.
2. **Ghost notes** next to a hi-hat are often missed. Drags are never
   detected, and flams are not recognized in band mixes (they come out as
   single strokes).
3. **Open/closed/half-open hi-hat and crash** are weak in band mixes (open
   hi-hat F 0.22-0.62, crash 0.30-0.51): the mix masks the cymbal wash.
   Hi-hat versus ride can also flip on real cymbals.
4. **Tempo can come out doubled or halved** (case 07 reads at 184 instead of
   92). The report says "tempo ambiguous" when it is close; pass `--bpm`.
5. **Meter.** 4/4, 3/4, 6/8 and 12/8 are detected, along with a switch to
   12/8 for a section (the boundary can be a bar off) and short bars that
   shift the downbeat (2/4, 1/4, 3/4 inside 4/4, found from crash
   placement). This needs crashes that sound clearly: in the humanized jazz
   band mix, case 12's short bars were missed. A meter given with
   `--time-signature` holds for the whole take (no section meters, no
   inserted short bars). Odd meters (5/4, 7/8) from audio are not supported:
   use MIDI or a chart spec.
6. **Bass bleed.** In full mixes bass notes can turn into kicks. A density
   warning catches the extreme cases; an isolated drum stem (`--drums-only`)
   avoids it.
7. **Unfamiliar timbres.** The templates come from General MIDI kits. Very
   different drums (electronic kits, heavily processed sounds) are detected
   poorly (numpy kit 0.61).
8. **Sparse passages.** Calibration is relative to the recording, so an
   isolated stroke after a long silence can be misread (a lone crash read as
   a snare), and a long cymbal ring-out can create phantom strokes. Noise
   below -60 dBFS is ignored.
9. **Section names** are letters (A, B, C); name them with `--sections` or
   `edit --sections`.
10. **No source separation.** No neural drum-separation or transcription
    model could be installed in this environment; detection is signal
    processing plus rules. With a drum stem from another tool, use
    `--drums-only`.

## Notation limits
- Rhythms finer than 32nds or sextuplets (quintuplets, 64ths) can't be
  written; such strokes have to be simplified, which the report says.
- Rolls are written as tremolo (unmeasured) rolls; buzz versus measured
  rolls are not distinguished.
- One percussion staff for a standard kit. Auxiliary percussion beyond the
  kit table (`drum_agent/kit.py`) needs a kit override.
- The MusicXML imports cleanly into MuseScore 3.2 and Verovio. MuseScore 3.2
  regroups 7/8 beams on import (an old-version quirk); the file itself
  follows the 4.0 schema.
