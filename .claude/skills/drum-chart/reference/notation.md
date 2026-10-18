# Notation quick reference

Authoritative spec: `docs/NOTATION_SPEC.md`. Mapping in code: `drum_agent/kit.py`.

## Staff and voices
- Five-line staff, percussion clef. Positions are given as treble-clef pitches.
- Default voicing **cymbals-up** (the user's reference chart; also Guitar Pro
  and Songsterr charts):
  - **Voice 1 (stems up): cymbals.** Hi-hat with sticks, ride, crash, china,
    splash, cowbell.
  - **Voice 2 (stems down): drums and feet.** Snare, cross-stick, rimshot,
    toms, bass drum(s), hi-hat pedal. A snare/tom roll with the kick under it
    moves up for that bar, so the kick is never part of the rolled chord.
- `--voicing hands-up` gives the Weinberg/PAS drum-book layout: everything the
  hands play stems up, only the feet down. Positions and noteheads don't change.
- A silent drum voice gets a whole-bar rest; a silent cymbal voice over drums
  (a fill, a pickup) is left blank; if both are silent, one rest.
- A chart with no cymbal at all (snare rudiment, march) is one voice, stems up,
  accents above; only a bar whose roll moved up over the kick has two voices
  (the hands up, the feet down).
- Sticking (R, L, B) prints on one line under the staff; cues ("hey",
  "Band in") print in italics above the staff at the start of their bar.

## Instrument map (chart-spec names in brackets)
| Instrument | Position | Head | Stem (cymbals-up) |
|---|---|---|---|
| China [cn] | C6 | x | up |
| Crash 2 [cr2] / Splash [spl] | B5 | x / circled x | up |
| Crash [cr] | A5 (ledger line) | x | up |
| Hi-hat [hh], open [o on hh line], half-open [h] | G5 | x (+ o / ⊘ above) | up |
| Ride [rd], ride bell [rb] | F5 (top line) | x / diamond | up |
| Tom 1 [t1] / cowbell [cb] | E5 | normal / triangle | down / up |
| Tom 2 [t2] | D5 | normal | down |
| Snare [sn], cross-stick [cs], rimshot [rs] | C5 | normal / x / slashed | down |
| Floor tom [ft], floor tom 2 [ft2] | A4, G4 | normal | down |
| Bass drum [bd], bass drum 2 [bd2] | F4, E4 | normal | down |
| Hi-hat foot [hf], foot splash [hhs] | D4 | x (+ o below) | down |

## Articulations
| Mark | Meaning | Chart-spec symbol |
|---|---|---|
| > | accent | `X` or `>` |
| ( ) around head | ghost note | `g` |
| small slashed grace + slur | flam | `f` (`F` = accented flam) |
| two small 16th graces | drag (ruff) | `d` (`D` = accented drag) |
| 3 tremolo strokes (fewer with beams) | roll | `r` then `~` to extend |
| o above hi-hat | open | `o` on the hh line |
| + above hi-hat | closed (only after an open one) | automatic |
| "choke" | cymbal choke | `c` |

## Rhythm rules the engraver applies
- Each beat gets the simplest grid that holds its strokes: 8ths, 16ths, 32nds,
  triplets (3:2), sextuplets (6:4); compound beats use 8ths/16ths, duplets 2:3.
- A 16th-note triplet and an 8th in one beat: a "3" over the half beat and a
  plain 8th (also as a pickup from the half beat). A tuplet beamed together
  shows its number only; the bracket prints only over an unbeamed tuplet.
- A note lasts until the next stroke in its voice or the end of the beat. Drum
  notes are never tied, except rolls.
- Rests follow bar > half bar > beat. No half rest across the middle of 4/4.
- Beams group by beat. In 4/4, two beats of plain 8ths beam as one group of four.
- Exactly identical bars become simile marks (counted), and identical phrases
  become repeat barlines with "×N" (the shortest phrase that repeats:
  `|: A B :| ×8`). Fills and flagged bars are always written out.
- Two or more empty bars in a row become one multi-bar rest with its count.
- Sections start a new system. A short section (under 40% of a line) may share:
  the next section follows it if that whole section fits, otherwise it joins
  the end of the previous line. Lines are balanced (6 bars → 3 + 3).
- 2/8 and 3/8 are beamed as one group, with a dotted-quarter tempo mark in 3/8.

## Headers
The chart-type line is always printed: Full Drum Transcription / Performance
Chart: grooves and roadmap, not a note-for-note transcription / Pattern Study,
plus "Automatic transcription, unverified" when applicable.
