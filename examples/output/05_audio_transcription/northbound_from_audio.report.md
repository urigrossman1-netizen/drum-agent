# Drum chart report: Northbound (transcribed from audio)

* Chart type: **Full Drum Transcription**
* Status: **Automatic transcription, unverified**
* Rights basis: original
* Source: audio file northbound.wav
* Bars: 60; notated strokes: 925

## Rendering correctness (automated)
* Engraved with LilyPond 2.26.0
* engraved score (LilyPond MIDI): OK (925/925 events)
* engraved score tempo map: OK (60/60 events)
* MusicXML: OK (925/925 events)
* MusicXML articulations: OK (87/87 events)
* MusicXML meters: OK (60/60 events)
* MIDI: OK (926/926 events)
* MIDI tempo map: OK (60/60 events)
* MIDI barlines: OK (60/60 events)
* MusicXML 4.0 schema: valid

## Transcription confidence
* This chart was produced automatically. A valid PDF does **not** mean the notes are right; listen along before relying on it.
* Bars needing verification, marked (?) in the PDF: 4 (4), 5 (5), 6 (6), 8 (8), 9 (9), 11 (11), 13 (13), 14 (14), 15 (15), 17 (17), 21 (21), 24 (24), 25 (25), 26 (26), 27 (27), 28 (28), 29 (29), 30 (30), 31 (31), 33 (33), 34 (34), 35 (35), 36 (36), 40 (40), 48 (48), 52 (52), 60 (60)
  (printed bar number, then the score.json bar number that `python -m drum_agent edit` uses)
  * score bar 4: 4 low-confidence hit(s): snare
  * score bar 5: 4 low-confidence hit(s): hihat_open, kick, snare
  * score bar 6: 1 low-confidence hit(s): hihat_open
  * score bar 8: 1 low-confidence hit(s): hihat_open
  * score bar 9: 2 low-confidence hit(s): hihat_open, snare
  * score bar 11: 2 low-confidence hit(s): hihat_open, snare
  * score bar 13: 5 low-confidence hit(s): snare
  * score bar 14: 5 low-confidence hit(s): snare
  * score bar 15: 5 low-confidence hit(s): snare
  * score bar 17: 1 low-confidence hit(s): ride
  * score bar 21: 1 low-confidence hit(s): kick
  * score bar 24: 2 low-confidence hit(s): kick, snare
  * score bar 25: 2 low-confidence hit(s): hihat, hihat_open
  * score bar 26: 2 low-confidence hit(s): hihat_open, snare
  * score bar 27: 2 low-confidence hit(s): hihat_open, snare
  * score bar 28: 2 low-confidence hit(s): hihat_open, snare
  * score bar 29: 1 low-confidence hit(s): hihat_open
  * score bar 30: 2 low-confidence hit(s): hihat_open, snare
  * score bar 31: 1 low-confidence hit(s): hihat_open
  * score bar 33: 5 low-confidence hit(s): snare
  * score bar 34: 7 low-confidence hit(s): kick, snare
  * score bar 35: 6 low-confidence hit(s): snare
  * score bar 36: 2 low-confidence hit(s): kick
  * score bar 40: 2 low-confidence hit(s): snare
  * score bar 48: short bar (2/4) inserted: the downbeat shifts here
  * score bar 52: 2 low-confidence hit(s): snare
  * score bar 60: 6 low-confidence hit(s): kick, tom1
* tempo estimate: 83.35 BPM (quarter note)
* meter: 4/4 (confidence 1.0)
* feel: straight
* detected onsets: 925
* instrument counts: {'snare': 250, 'kick': 247, 'ride': 185, 'hihat': 156, 'floor_tom': 46, 'hihat_open': 15, 'tom2': 12, 'crash': 11, 'tom1': 3}
* low confidence hits: 83
* sections: ['A: bar 1, 24 bars, hihat, 7 fill bar(s)', 'B: bar 25, 20 bars, hihat, 7 fill bar(s)', 'C: bar 45, 4 bars, hihat, 1 fill bar(s)', 'D: bar 49, 12 bars, ride, 3 fill bar(s)']
* notes: ['tempo ambiguous: 83 BPM chosen, 167 BPM also plausible (score 0.92 of best); pass --bpm if the chart reads at the wrong speed', 'bar 48: the downbeat shifts by 2 beat(s) (crashes moved from beat 1 to beat 3); a 2/4 bar was inserted (bars after it repeat earlier ones 0.93 vs 0.71). Verify by ear.', 'Section letters are pattern-based; rename them with --sections once you know the song form.', 'Hi-hat pedal strokes are not detected (no detector class); add them by hand if needed.']

## Files
* json: `northbound_from_audio.json`
* ly: `northbound_from_audio.ly`
* pdf: `northbound_from_audio.pdf`
* png1: `northbound_from_audio-page1.png`
* png2: `northbound_from_audio-page2.png`
* engraved_midi: `northbound_from_audio.midi`
* musicxml: `northbound_from_audio.musicxml`
* midi: `northbound_from_audio.mid`
