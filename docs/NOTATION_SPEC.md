# Drum Agent Notation Specification

This document is the contract for every score the Drum Agent produces. The
LilyPond engraver, the MusicXML exporter, the MIDI exporter and the
`drum-chart` skill all follow it. Mappings live in code in
`drum_agent/kit.py` (one table), so this document and the output cannot drift
apart silently. `tests/test_kit.py` asserts the table below.

## 1. Basis and sources

* **Primary standard:** Norman Weinberg, *Guidelines for Drumset Notation*
  (Percussive Notes, June 1994), expanded as the Percussive Arts Society's
  *Guide to Standardized Drumset Notation* (1998/2002). LilyPond 2.26 ships
  this layout as `weinberg-drums-style` (`ly/drumpitch-init.ly`, which cites
  the article). We start from that table.
* **Adjustment for the standard 5-piece kit:** Weinberg's table places "high
  tom" on the top line, shared with the ride. Mainstream drum books (Hal
  Leonard transcriptions, Modern Drummer) and MuseScore's default drumset put
  Tom 1 in the top space (E5) and Tom 2 on the fourth line (D5). We follow that
  so the top line belongs only to the ride.
* **Engraving rules** (rests, beaming, beat visibility) follow common
  practice as described in Elaine Gould, *Behind Bars* (Faber, 2011):
  every beat stays visible, rests never hide the middle of a 4/4 bar, and
  beams follow the beat.
* **Engine references:** LilyPond 2.26 Notation Reference §2.5.1 "Common
  notation for percussion" (read from the 2.26.0 documentation source,
  `Documentation/en/notation/percussion.itely`); the MusicXML 4.0 schema
  (`drum_agent/schemas/musicxml-4.0/musicxml.xsd`).

Publishers don't all agree on tom and cymbal placement, so every chart that
uses more than kick, snare and hi-hat (open and half-open hi-hat count as
hi-hat) prints a **Drum Key** on page 1. A key for a big kit wraps onto
further lines; it never runs off the page.

## 2. Staff

* A five-line staff with a percussion clef. Notes are given by staff
  position, written here as the treble-clef pitch of that position (the
  middle line is B4).
* **Two voices.** The default voicing, `cymbals-up`, is the one in the
  user's reference chart (and in Guitar Pro and Songsterr charts):
  * **Voice 1, stems up: cymbals.** Hi-hat played with sticks, ride, crash,
    china, splash, cowbell.
  * **Voice 2, stems down: drums and feet.** Snare, cross-stick, rimshot,
    toms, bass drum(s), hi-hat pedal.

  The alternative, `--voicing hands-up` (Weinberg / Percussive Arts Society
  drum-book layout), puts everything the hands play in voice 1 (cymbals,
  snare, toms) and only the feet in voice 2. Staff positions and noteheads
  are the same in both; only the stem direction of snare and toms changes.
* **Sticking** (R, L, B for both hands) prints on one line under the staff,
  centred under the stroke it belongs to. **Cues** ("hey", "Band in",
  "Gtr. solo") print in italics above the staff at the start of the bar.
* **Swing**: a chart written in straight 8ths with `swing` set prints the
  word with its rhythm, ♫ = ♩♪ under a triplet bracket.
* A lower voice with no hits for a whole bar shows a whole-bar rest. An
  upper (cymbal) voice with no hits in a bar where the drums play (a fill, or
  a pickup) is left blank: its whole rest would sit in the top space, on the
  tom noteheads. If both voices are silent, one whole-bar rest is printed.
* A snare or tom roll with the bass drum under it moves up to voice 1 for
  that bar (in the cymbals-up voicing), so the kick is never part of the
  rolled chord.
* **One-voice charts.** When one voice has no hits anywhere in the chart (a
  snare rudiment, a snare-and-bass-drum march), the other is engraved as a
  single voice: stems up, accents above the staff, no rests for the empty
  voice. A bar whose roll moved up over the kick is the exception: that bar
  alone is in two voices, the hands up and the feet down (as in the hands-up
  voicing), so its other snare strokes keep their stems and accents above and
  no rest prints over them (if a tom or snare stroke starts during the roll,
  only the roll moves up). The MusicXML writes the single voice, its empty
  bars included, under one voice number.

## 3. Instrument map

| id | Instrument | Staff position | Notehead | Voice (default voicing) | GM note |
|---|---|---|---|---|---|
| `crash2` | Crash cymbal 2 | B5 (space above 1st ledger line) | × | 1 up | 57 |
| `china` | China cymbal | C6 (2nd ledger line) | × | 1 up | 52 |
| `splash` | Splash cymbal | B5 | ⊗ (circled ×) | 1 up | 55 |
| `crash` | Crash cymbal | A5 (1st ledger line) | × | 1 up | 49 |
| `hihat` | Hi-hat, closed, with sticks | G5 (space above staff) | × | 1 up | 42 |
| `hihat_open` | Hi-hat, open | G5 | × with **o** above | 1 up | 46 |
| `hihat_half` | Hi-hat, half-open | G5 | × with half-open circle (⊘) above | 1 up | 46 |
| `ride` | Ride cymbal | F5 (top line) | × | 1 up | 51 |
| `ride_bell` | Ride bell | F5 | ◇ (diamond) | 1 up | 53 |
| `tom1` | High tom (Tom 1) | E5 (top space) | ● | 2 down | 48 |
| `cowbell` | Cowbell | E5 | ▲ (triangle) | 1 up | 56 |
| `tom2` | Mid tom (Tom 2) | D5 (4th line) | ● | 2 down | 45 |
| `snare` | Snare drum | C5 (3rd space) | ● | 2 down | 38 |
| `cross_stick` | Cross-stick (side stick) | C5 | × | 2 down | 37 |
| `rimshot` | Snare rimshot | C5 | ● with a slash through it | 2 down | 40 |
| `floor_tom` | Floor tom | A4 (2nd space) | ● | 2 down | 43 |
| `floor_tom2` | Low floor tom | G4 (2nd line) | ● | 2 down | 41 |
| `kick` | Bass drum | F4 (1st space) | ● | 2 down | 36 |
| `kick2` | Second bass drum / double pedal | E4 (bottom line) | ● | 2 down | 35 |
| `hihat_pedal` | Hi-hat with foot | D4 (space below staff) | × | 2 down | 44 |
| `hihat_splash` | Hi-hat foot splash | D4 | × with **o** below | 2 down | 44 |

Position values in code use LilyPond's convention: 0 is the middle line and
each step is half a staff space (snare = 1, kick = −3, hi-hat = 5).

The mapping can be changed for a project with a JSON kit file
(`--kit my_kit.json`, schema in `drum_agent/kit.py`). The legend always
reflects the mapping actually used.

## 4. Rhythm

### 4.1 Source of truth
Every hit is stored as an exact rational position inside its bar
(`fractions.Fraction`, in whole notes). Durations are *notated*, not
performed: a drum stroke doesn't sustain, so a note's written value is
chosen for readability. No floating-point grid is used in notation.

### 4.2 Beats
* **Simple meters** (2/4, 3/4, 4/4, 5/4, 2/2 …): the beat is the denominator.
* **Compound meters** (6/8, 9/8, 12/8, and the /16 equivalents): the beat is
  a dotted value (three eighths in 6/8).
* **Irregular meters** (5/8, 7/8, 11/8 …): the beat groups come from the bar
  (`beat_groups`, default 5/8 = 2+3, 7/8 = 2+2+3, 11/8 = 2+2+2+2+3) and are
  printed through LilyPond's `beatStructure` as well as our beaming.
* A **pickup** (anacrusis) is the tail of a full bar. Only the first bar may
  be shorter than its time signature.

### 4.3 Writing notes within a beat
1. Each beat gets the **simplest grid** that holds all of its onsets, in this
   order: 1, 2, 4, 3, 8, 6, 12 per beat in simple meter, and 1, 3, 6, 2, 4, 12
   per beat in compound meter.
2. Grids of 3, 6 or 12 in simple meter become a triplet bracket
   (`3:2`, written in 8ths, 16ths or 32nds). Grids of 2 or 4 in compound meter
   become duplets/quadruplets (`2:3`, `4:6`).
   A 16th-note triplet and an 8th in one beat (in either order) are written
   as a `3:2` over that half beat and a plain 8th, one beam over the beat,
   not as a `6` ending on a dotted 8th; a pickup that starts on the half beat
   with a 16th-note triplet is a `3` too. Six even sextuplets, or triplets in
   both halves, stay a `6`.
3. Quarter-note triplets: if two adjacent beats (one half of a 4/4 bar) have
   onsets only on thirds of that span, they become one `3:2` bracket of
   quarter notes.
4. A note lasts until the next onset **in the same voice** or the end of the
   beat, whichever is first. It takes the longest single value that fits
   (plain or single-dotted), and any time left over becomes rests. Drum notes
   are therefore never tied, except rolls.
5. Notes never cross a beat boundary. The exception is rolls (§5).

### 4.4 Rests
* Rests are split along the bar's metrical hierarchy: bar → half bar (in
  2/4, 4/4, 2/2 and 12/8 only) → beat → half beat → … A rest covers a node
  of that hierarchy completely or is split further.
* So in 4/4 a half rest appears only on beat 1 or beat 3, never across the
  middle of the bar. An empty bar gets a whole-bar rest. In compound meter
  an empty beat gets a dotted-quarter rest.
* Simple meter has no dotted rests. A gap of three 16ths at the start of a
  beat is an 8th rest followed by a 16th rest.

### 4.5 Beaming
* Notes of an 8th or shorter are beamed **within a beat**, and rests
  between beamed notes sit under the beam.
* **4/4 exception:** two adjacent beats in the same half-bar that both hold
  plain 8th notes (no rests, no shorter values, no tuplets) are beamed as one
  group of four, like the reference chart and LilyPond's 4/4 default.
* Tuplet groups are beamed within their bracket. A tuplet whose notes are
  beamed together shows its number only; the bracket prints when they aren't
  (a quarter and an 8th, a tuplet that starts or ends on a rest), in the PDF
  and in the MusicXML (`bracket="no"` / `"yes"`). A flam or drag on a
  tuplet's first note sits before the tuplet, outside the bracket.
* Beams are computed **once**, in `drum_agent/rhythm.py`. Both the LilyPond
  source (explicit `[ ]`) and the MusicXML (`<beam>` levels and hooks) are
  written from that one result, so the two formats always agree.

## 5. Articulations and techniques

| Technique | IR field | Notation | MusicXML | MIDI |
|---|---|---|---|---|
| Accent | `accent` | `>` on the stem side | `<accent/>` | velocity ≥ 115 |
| Ghost note | `ghost` | parenthesized notehead | `<notehead parentheses="yes">` | velocity ≤ 40 |
| Open hi-hat | instrument `hihat_open` | **o** above | `<technical><open/>` | note 46 |
| Closed after open | (derived) | **+** above the first closed stroke after an open one | `<technical><stopped/>` | note 42 |
| Half-open hi-hat | instrument `hihat_half` | ⊘ above | `<technical><half-muted/>` | note 46, lower velocity |
| Flam | `flam` | one slashed 8th grace note on the same instrument, with a slur | `<grace slash="yes"/>` | extra soft hit 30 ms earlier |
| Drag (ruff) | `drag` | two 16th grace notes | two `<grace/>` notes | two soft hits earlier |
| Roll | `roll` (duration) | three tremolo strokes in total (quarter `:32` = 3 slashes; 8th = 2 + beam; 16th = 1 + beams); ties if the roll crosses a beat | `<tremolo type="single">` | repeated 32nds |
| Choke | `choke` | small italic "choke" | `<words>choke</words>` | note-off after a 16th |

Closed "+" marks are printed only on the first closed hi-hat after an open
or half-open one, not on every closed stroke. This is standard practice
and keeps the page uncluttered.

## 6. Bars, tempo and structure

* **Time signatures** are printed at the start and at every change.
* **Tempo:** a metronome mark at bar 1 and at every change, kept clear of
  a tuplet number beside it (a "3" lead-in) so the two never read as one. In compound
  meter (and 3/8) the beat unit is the dotted beat (dotted quarter in x/8).
  Short x/8 bars are beamed by beat: 2/8 and 3/8 as one group, 4/8 as 2 + 2. A detected swing feel adds the
  text "Swing" to the mark and the 8ths stay straight (standard practice).
  It is not written as triplets.
* **Section labels** (Intro, Verse, Chorus, Bridge, Solo, Outro, or A/B/C
  when names are unknown) are boxed labels at the start of a system. Each
  section starts a new system, with two exceptions that avoid a system
  holding one short bar stretched across the page: a short section (under
  40% of a line) is followed on its line by the next section when that whole
  section fits there; otherwise it joins the end of the previous line (up to
  a quarter more than a full line, never after a repeat), after a double
  barline.
* **Bar numbers** appear at the start of every system.
* **Repeats.** These are used only when the repeated music is *exactly*
  identical after quantization:
  * runs of identical single bars inside a section → one-bar simile marks
    (%) with a count every 4 bars;
  * a phrase of 2–8 bars repeated whole → repeat barlines with "×N"; the
    phrase that saves the most written bars wins, and the shorter one on a
    tie (`|: A B :| ×8`, not `|: A B A B A B A B :| ×2`).
  * two or more consecutive empty bars (same meter, no mark after the first)
    → one multi-bar rest (an H-bar with the count above), also in MusicXML
    (`<multiple-rest>`).
  * Fills, variations and the last bar of a phrase that differs are always
    written out. Repeats can be turned off (`--repeats none`) to write
    everything out.
* **Line breaks.** 4 bars per system by default. Dense bars (32nds,
  tuplets, many chords) reduce this to 3 or 2, and LilyPond spaces each
  system proportionally.

## 7. Page and header

* Title (song), subtitle (artist), transcriber credit on the right, and a
  **chart-type line** that is always present. A title, artist or copyright
  line too wide for the page (one that would reach more than halfway into the
  margins) is wrapped into centred lines of balanced width inside the margins
  (estimated from its letters, capitals and CJK characters counted wider; a
  word wider than a line is cut), never cut off at the page edges; the PDF's
  title metadata keeps it whole. The chart types:
  * `Full Drum Transcription`: every bar transcribed note for note.
  * `Performance Chart: grooves and roadmap, not a note-for-note transcription`.
  * `Pattern Study`: exercises and examples.
* Automatic transcriptions that a human hasn't verified carry
  `Automatic transcription, unverified` in the header. Bars with an
  uncertain or possibly missing stroke get a small "(?)" above the staff,
  explained in a footnote on page 1.
* A Drum Key staff on page 1 shows every instrument used, with labels.
* Paper is US Letter by default (`--paper a4` is available) at 20 pt staff
  size, which reads well on a music stand and on screen.

## 8. Export requirements

| Format | Producer | Purpose | Required |
|---|---|---|---|
| `.ly` | `export/lilypond.py` | engraving source | yes |
| `.pdf` | LilyPond 2.24+ (2.26 recommended) | the score | yes; failure is a hard error |
| `.png` | LilyPond | page previews for visual QA | yes |
| `.musicxml` | `export/musicxml.py` | editable in MuseScore, Dorico, Sibelius | yes; validated against the MusicXML 4.0 XSD |
| `.mid` | `export/midi.py` | playback and verification, GM channel 10 | yes |
| `.json` | `model.py` | the IR, the source of truth | yes |

If LilyPond is missing or fails, the agent stops with the LilyPond log. It
never falls back to drawing its own symbols.
