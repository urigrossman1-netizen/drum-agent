# Audio transcription: method, measured accuracy, failure modes

Read this before transcribing audio. It tells you what the detector can and
can't hear, so you know which parts of a chart to distrust.

## What the pipeline does
1. **Front end** (`drum_agent/audio/features.py`, `detect.py`): 44.1 kHz mono,
   96-band mel spectrogram (hop 256 ≈ 5.8 ms). Unless `--drums-only`, harmonic/
   percussive separation (HPSS) suppresses sustained instruments, processed in
   30 s chunks.
2. **Stroke detection**: Superflux onset strength, then semi-adaptive NMF:
   68 drum templates (FluidSynth GM kits) with three stacked time frames
   (attack, +17 ms, +46 ms), plus a frozen "accompaniment" basis learned from
   the harmonic part, so bass and keys aren't explained as drums.
3. **Classification**: each onset's activation share per instrument region,
   adaptive (Otsu) floors, then rules: one of hi-hat/ride/crash per stroke, at
   most two hand strokes at once, a tom needs real tom energy (not bass),
   crash-on-snare suppression. Open/closed hi-hat from decay ring; flams from a
   grace bump 12-70 ms before a stroke (or two strokes 12-45 ms apart); accents and ghosts relative to local
   dynamics.
4. **Grid** (`beats.py`): drum-weighted beat tracking; tempo candidates
   (×½, ×⅔, ×¾, ×1, ×4/3, ×1.5, ×2) scored by grid fit, backbeat spacing and a tempo prior;
   meter 3 vs 4 by bar-repetition; downbeat by kick/crash/backbeat placement.
   Where crashes move off beat 1 for good, a short bar (2/4, 3/4, 1/4) is
   inserted and the song re-quantized; inserted bars are always flagged.
5. **Quantizer** (`quantize.py`): per beat, picks the grid (straight 8ths/16ths/
   32nds, triplets, sextuplets) minimizing timing error plus complexity; detects
   swing/triplet feel; keeps a tempo map; flags bars with weak evidence.
6. **Structure** (`structure.py`): section boundaries at meter/tempo changes
   or groove changes marked by a crash or fill; letters A, B, C... Rename with
   `--sections` or `edit --sections`.

## Measured accuracy (synthetic audio, ground truth known)
Full tables: `docs/LIMITATIONS.md`. Stroke level, by `scripts/eval_detection.py`
on FluidSynth renderings of the regression charts (722 reference strokes per
condition), 50 ms tolerance. "Held-out" kits were not used to build the templates.

| Condition | Onset F | Weak classes |
|---|---|---|
| Standard kit, drums only | 0.988 | crash 0.85, floor tom 0.80 |
| Room kit, drums only | 0.978 | floor tom 0.57, crash 0.77, open hi-hat 0.80 |
| Jazz kit (held out), drums only | 0.989 | open hi-hat 0.88 |
| Brush kit (held out), drums only | 0.965 | snare 0.92 (soft brushes), floor tom 0.73 |
| Standard kit + bass/keys | 0.973 | crash 0.51, open hi-hat 0.62 |
| Jazz kit + bass/keys, ±10 ms humanized | 0.900 | crash 0.30, open hi-hat 0.22, floor tom 0.73 |
| Unfamiliar synthetic timbres (numpy kit) | 0.610 | snare 0.16, cymbals ~0.1, toms 0.0 |

Hi-hat **foot** strokes are not detected at all; add them by hand.

Notation level (every stroke in the right bar, at the right position, on the
right instrument), end to end from audio by `scripts/eval_notation.py`: ten
charts × four conditions, mean 0.897, median 0.972. The full 60-bar song scored
0.948-0.983; case 07 reads at double tempo without `--bpm` (0.27; 0.85+ with
`--bpm 92`). Bar flags "(?)": 52% of flagged bars contained an error, and flags
caught 44% of the wrong bars, so flags help you find problems but every bar
still needs a listen.

**These numbers come from synthesized audio.** Real recordings (room sound,
compression, cymbal wash, bleed) are harder. Expect more errors, especially in
cymbals and ghost notes, and always listen. On three real Creative Commons
recordings the tempo/meter was ambiguous in two of them (see LIMITATIONS).

## Failure modes and what to do
| Symptom in report or PDF | Likely cause | Fix |
|---|---|---|
| Tempo twice or half what you hear; "tempo ambiguous" | double/half-time ambiguity | re-run with `--bpm` |
| Every backbeat on 1 and 3 | downbeat a beat off | `--downbeat <seconds of a beat 1>` |
| Waltz written in 4/4, "meter uncertain" | meter detection | `--time-signature 3/4` |
| Bridge in 12/8 starts or ends a bar late | section meter boundary | edit, or transcribe the passage with `--start/--end --time-signature 12/8` |
| A flagged 2/4 or 3/4 bar you don't hear | crashes moved off beat 1 (inserted short bar) | listen; if the band stayed in 4/4, re-run with `--time-signature 4/4` and fix accents by hand |
| "barring kept" note in the report | crash accents off beat 1 that did not prove a shifted downbeat | check whether a short bar was played there |
| Many extra kicks, "kick density" warning | bass guitar bleed | use a drum stem (`--drums-only`) or delete by hand |
| Hi-hat written as ride or vice versa | similar cymbal spectra | `edit --relabel ride=hihat --bars A-B` after listening |
| Crashes missing in a band mix | crash masked by the mix | add with `edit --add BAR:0:crash` |
| Ghost notes missing | masked by hi-hat | add by ear; raise `--sensitivity 1.3` carefully |
| Drags never appear | not detected | add with `:drag` by ear |
| Odd meters (5/4, 7/8) from audio | not supported | use a MIDI track or write a chart spec |
| Sections only lettered A, B, C | no lyrics/harmony analysis | `--sections "Intro:1,Verse:5,..."` |

## Rights
`transcribe` refuses to run without `--rights`. `analyze` (tempo, meter,
sections, no notes) needs no rights basis. Don't fetch audio from streaming
services; work only with files the user supplies or that carry a suitable
licence (record its attribution in the score's source/notes).
