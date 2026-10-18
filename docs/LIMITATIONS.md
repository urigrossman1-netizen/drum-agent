# Measured accuracy and limitations

Two different questions, two different answers:

- **Is the engraving right?** Every export is checked automatically against
  the score it was made from: LilyPond's own MIDI, the MusicXML (notes,
  articulations, meters, schema) and our MIDI (notes, tempo map, barlines).
  For hand-written charts, the chart library and MIDI or game-chart input
  this makes the PDF/MusicXML/MIDI trustworthy, and 786 automated tests
  (including random-score fuzzing and all 113 library charts) back it up.
- **Are the notes right?** For audio this can only be measured where the
  answer is known: synthesized recordings of original charts (exact answers)
  and MDB Drums, 23 real recordings with every stroke annotated. Real
  recordings are harder, and the numbers below show how much. Listen to every
  chart before relying on it.

All audio numbers are for the default detector, the onset classifier
(`docs/MODELS.md`), unless marked "NMF" (the original template detector,
still available as `--detector nmf`).

## Real recordings (scripts/eval_real.py)

MDB Drums: 23 MedleyDB recordings (rock, jazz, funk, reggae, punk, metal,
gospel, Latin...), each as the isolated drum mix and the full band mix,
~8000 annotated strokes, CC BY-NC-SA 4.0 (downloaded to a local cache, never
committed). Onset F at 50 ms per class: kick (KD), snare (SD), hi-hat (HH),
toms (TT), cymbals (CY). The MIREX 2017 split: the 12 training recordings
were used to choose between model versions; the 11 test recordings were run
once, for this table.

**Held-out test recordings (11):**

| | KD | SD | HH | TT | CY | KD/SD/HH | all 5 |
|---|---|---|---|---|---|---|---|
| Drum stem, classifier | 0.963 | 0.866 | 0.723 | 0.495 | 0.270 | 0.837 | **0.772** |
| Drum stem, NMF | 0.969 | 0.685 | 0.704 | 0.193 | 0.170 | 0.770 | 0.662 |
| Full band mix, classifier | 0.706 | 0.688 | 0.611 | 0.307 | 0.094 | 0.664 | **0.591** |
| Full band mix, NMF | 0.570 | 0.434 | 0.621 | 0.057 | 0.162 | 0.546 | 0.421 |

Development recordings (12): drum stems 0.856 (NMF 0.791), band mixes 0.696
(NMF 0.484).

What this means for a chart made from a real recording:
- **Kick and snare** are mostly right on a drum stem (0.96, 0.87), and about
  two in three strokes are right in a full mix.
- **Hi-hat** is right about three times in four; open versus closed and
  hi-hat versus ride are the usual confusions, and brushes and dense jazz
  ride patterns produce extra hi-hat strokes.
- **Toms** are found about half the time on a stem and a third in a mix.
- **Cymbals (crash, ride, china, splash) are the weakest class**: about one
  in four on a stem, and in a full band mix the classifier finds fewer than
  the old detector did (0.09 vs 0.16). Expect to add crashes by ear.
- A drum stem (from the session, an e-kit, or a separation tool) is much
  better than a full mix: pass `--drums-only`.

## Synthesized audio, measured

### Notation level (scripts/eval_notation.py)
Notation F counts a stroke as right only if it is in the right bar, at the
right position, on the right instrument. Ten charts, four conditions each:

| Chart | Standard kit, drums only | Jazz kit (held out), drums only | Standard kit + bass/keys | Jazz kit + bass/keys, ±8 ms humanized |
|---|---|---|---|---|
| 02 eighth-note rock | 1.000 | 1.000 | 1.000 | 1.000 |
| 03 16th syncopation | 0.987 | 1.000 | 0.987 | 0.987 |
| 05 open/closed/half-open hi-hat | 0.958 | 0.958 | 0.958 | 0.968 |
| 06 tom fill over the barline | 0.980 | 1.000 | 0.974 | 0.987 |
| 07 ghosts, accents, flams, rolls | 0.930 | 0.922 | 0.906 | 0.879 |
| 10 pickup, 12/8 bridge, tempo change | 0.987 | 0.987 | 0.979 | 0.785 |
| 11 tom grooves and fills | 0.899 | 0.954 | 0.902 | 0.920 |
| 12 two short bars (2/4, 3/4) | 0.992 | 0.992 | 0.992 | 0.967 |
| 13 crash accents on beat 3 | 0.974 | 0.974 | 0.977 | 0.969 |
| Northbound, full 60-bar song | 0.978 | 0.991 | 0.978 | 0.951 |

Mean 0.963, median 0.977 over the 40 runs (the NMF detector: 0.948). Every
run found the right tempo, including case 07, which used to read at double
tempo.

### Stroke level (scripts/eval_detection.py)
Onset F at 50 ms, pooled over six charts (722 strokes per condition):

| Condition | Classifier | NMF | Weak classes (classifier) |
|---|---|---|---|
| Standard kit, drums only | 0.982 | 0.988 | open hi-hat 0.83, pedal hi-hat 0.80 |
| Room kit, drums only | 0.980 | 0.978 | open hi-hat 0.83, pedal hi-hat (1 stroke) |
| Jazz kit (held out), drums only | 0.984 | 0.989 | open hi-hat 0.83, pedal hi-hat 0.80 |
| Brush kit (held out), drums only | 0.967 | 0.965 | floor tom 0.73, pedal hi-hat 0.80 |
| Standard kit + bass/keys | 0.977 | 0.973 | open hi-hat 0.83 |
| Jazz kit + bass/keys, ±10 ms humanized | 0.956 | 0.900 | pedal hi-hat 0.67, kick 0.92 |
| Unfamiliar synthetic timbres (numpy kit) | 0.828 | 0.610 | ride 0.15, toms 0.0-0.25 |

On clean synthesized kits the classifier is within 0.006 of the template
detector, whose templates came from these very soundfonts; it is better in
band mixes, on unfamiliar sounds and on real recordings, which is why it is
the default.

### Review flags
Bars marked "(?)" are those with low-confidence strokes, a structural
decision (e.g. an inserted short bar) or strokes one drummer can't play
together. Across the runs above, 68% of flagged bars contained an error, but
flags caught only 12% of the wrong bars: the classifier is confident even
when wrong, and a missed stroke has no confidence at all. **Flags help you
find problems; they don't replace listening to every bar.**

### Long recordings
An 8.5-minute band mix (`scripts/stress_long.py`) took 195 s and peaked at
1.1 GB of memory on a 4-CPU machine with the NMF detector (3 minutes: about
80 s, 0.6 GB); the classifier adds about a second per minute of audio. Memory
grows with length; very long files (20+ minutes) need several GB.

Charts of non-commercial-licensed material are not committed.

## Known limitations
1. **Cymbals in real recordings** are found about one time in four (crash,
   ride, china, splash); in a full band mix fewer. Add crashes by ear.
2. **Ghost notes** next to a hi-hat are often missed; drags are never
   detected, and flams are recognized only when the grace stroke stands out.
3. **Open/closed hi-hat** and **hi-hat versus ride** can flip on real
   cymbals; brushes and busy jazz ride patterns add extra hi-hat strokes.
4. **Toms** on real recordings: about half are found on a drum stem, a third
   in a full mix, and which tom (high, mid, floor) comes from the pitch
   order within the recording.
5. **Tempo** can still come out doubled or halved on unusual material. The
   report says "tempo ambiguous" when it is close; pass `--bpm`.
6. **Meter.** 4/4, 3/4, 6/8 and 12/8 are detected, along with a switch to
   12/8 for a section (the boundary can be a bar off) and short bars that
   shift the downbeat (2/4, 1/4, 3/4 inside 4/4, found from crash
   placement). A meter given with `--time-signature` holds for the whole
   take. Odd meters (5/4, 7/8) from audio are not supported: use MIDI, a game
   chart or a chart spec.
7. **Bass bleed.** In full mixes bass notes can turn into kicks. A density
   warning catches the extreme cases; a drum stem (`--drums-only`) avoids it.
8. **Sparse passages.** Calibration is relative to the recording, so an
   isolated stroke after a long silence can be misread, and a long cymbal
   ring-out can create phantom strokes. Noise below -60 dBFS is ignored.
9. **Section names** are letters (A, B, C); name them with `--sections` or
   `edit --sections`.
10. **No source separation.** Detection works on the mix as given; with a
    drum stem from another tool, use `--drums-only`.

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
