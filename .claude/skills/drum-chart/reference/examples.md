# Examples, simple to full song

All examples are original material. Specs live in `examples/specs/`, rendered
results in `examples/output/<name>/` (PDF, PNG, MusicXML, MIDI, report).
Re-render any of them with:

```bash
python -m drum_agent render examples/specs/03_full_song_northbound.yaml -o examples/output/03_full_song_northbound
```

## 1. One groove and variations: `01_basic_rock_beat.yaml`
```yaml
title: Basic Rock Beat
chart_type: pattern_study
rights: original
tempo: 100
patterns:
  beat: {hh: "x-x-x-x-x-x-x-x-", sn: "----x-------x---", bd: "x-------x-------"}
  var2: {hh: "x-x-x-x-x-x-x-o-", sn: "----x-------x---", bd: "x-----x-x-x-----"}
  var3: {hh: "x-x-x-x-x-x-x-x-", sn: "----x--g-g--x--g", bd: "x-----x-x-x-----"}
sections:
  - label: Groove
    bars: [beat, var2, var3]
```
Shows: two voices, open hi-hat "o" with automatic "+" on the next closed note,
ghost notes in parentheses, Drum Key.

## 2. Triplet feels: `02_shuffle_and_swing.yaml`
- Half-time shuffle written in 8th-note triplets (12 characters per 4/4 bar),
  ghost notes on the middle partial, a triplet fill using `|` beat segments
  (`"-g-|-gX|xxx|X--"`).
- Jazz ride written in straight 8ths under `tempo_text: Swing`, feathered
  kick (`g` on bd) and hi-hat foot on 2 and 4 (`hf`).
- Shows: tuplet brackets, the 2-bar phrase compressed to a repeat "×3".

## 3. A complete song: `03_full_song_northbound.yaml`
Intro, two verses, pre-choruses, repeated choruses, a bridge with a 2/4 bar,
outro with a three-beat roll. 60 bars on 2 pages. Shows: boxed section labels,
crashes, tom fills, flams, accents, `repeat: 2` sections engraved as repeat
barlines "×2", simile marks with counts, a meter change with courtesy time
signature, and the final barline. Use it as the template for full charts.

## 4. A gig chart: `04_performance_chart.yaml`
`chart_type: performance_chart`: grooves + roadmap. The header says
"Performance Chart: grooves and roadmap, not a note-for-note transcription".
Fits one page (the layout pulls a near-empty last page back automatically).

## 5. From audio (you own the recording)
```bash
# Make a test recording from the full-song chart (FluidSynth + bass/keys):
python -m drum_agent synth examples/specs/03_full_song_northbound.yaml -o northbound.wav --accompaniment
python -m drum_agent transcribe northbound.wav --rights original --title "Northbound" \
    --sections "Intro:1,Verse 1:5,Pre-Chorus:13,Chorus:17" -o out/northbound
python -m drum_agent evaluate examples/specs/03_full_song_northbound.yaml out/northbound/northbound.json
```
`evaluate` compares a transcription with a known chart (notation-level
accuracy per instrument), which is how the numbers in
[transcription-guide.md](transcription-guide.md) were measured.

## 6. From a MIDI drum track
```bash
python -m drum_agent midi groove.mid --title "Groove" --rights own -o out/groove
```
Uses the MIDI tempo map; GM drum notes on channel 10 (`--channel N` otherwise).
