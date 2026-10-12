# QC checklist (read every page image)

Tick each item on every page. Fix the cause and re-render; never deliver with
an item failing.

## Automated (from report.md)
- [ ] LilyPond MIDI, MusicXML and MIDI file each match score.json (three "OK" lines)
- [ ] MusicXML 4.0 schema: valid
- [ ] No LilyPond warnings in the Warnings section
- [ ] Chart type and status are right for what was actually done

## Page and header
- [ ] Title centred, artist as subtitle, "Transcribed by" at the right, chart-type line present
- [ ] Tempo mark (and "Swing"/feel text if any) at the start
- [ ] Drum Key present when more than 3 instruments are used
- [ ] Page numbers from page 2; no page with a single system unless it's the last
- [ ] Uncertainty footnote present if any bar is marked "(?)"

## Staff
- [ ] Percussion clef on every system; time signature at the start and at every change
- [ ] Hi-hat/cymbals on or above the top line with x heads; snare 3rd space;
      kick 1st space; toms descending
- [ ] Hands stems up, feet stems down; no stems crossing to the wrong voice
- [ ] Hi-hat foot (x below the staff) stems down

## Rhythm
- [ ] Each bar adds up (LilyPond would fail otherwise, but check pickups)
- [ ] Beams follow beats; 4/4 straight 8ths beamed in fours; 6/8 in threes
- [ ] Rests: whole-bar rest centred; no rest crossing the middle of a 4/4 bar;
      rests in the lower voice don't collide with the kick
- [ ] Tuplet brackets/numbers on triplets and sextuplets, not on swung 8ths
- [ ] No tied drum notes except rolls

## Articulations
- [ ] Accents above the upper voice, not on the noteheads
- [ ] Ghost notes in parentheses; flams/drags as small graces with slur
- [ ] Open hi-hat "o", closing "+", rolls as tremolo slashes
- [ ] Section labels boxed, at the start of a system where possible

## Repeats and layout
- [ ] Simile marks only over bars identical to the previous one; count numbers
      readable; nothing written out that is simile-marked elsewhere
- [ ] Repeat barlines with "×N" when a phrase repeats; volta structure matches the form
- [ ] Bars numbered at system starts; numbers match the report's "printed" numbers
- [ ] Systems balanced (no lonely bar stretched across a line; short last line ragged)
- [ ] Nothing collides: text, accents, ledger lines, tuplet numbers

## Musical sense (transcriptions)
- [ ] Tempo and meter match what you hear (the most damaging errors)
- [ ] Backbeat on 2 and 4 (in rock/pop) — otherwise the downbeat is off
- [ ] Instrument counts plausible; no toms where there are no fills
- [ ] Flagged bars listed in your delivery message
