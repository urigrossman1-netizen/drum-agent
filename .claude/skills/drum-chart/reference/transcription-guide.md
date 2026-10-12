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
5. **Quantizer** (`quantize.py`): per beat, picks the grid (straight 8ths/16ths/
   32nds, triplets, sextuplets) minimizing timing error plus complexity; detects
   swing/triplet feel; keeps a tempo map; flags bars with weak evidence.
6. **Structure** (`structure.py`): section boundaries at meter/tempo changes
   or groove changes marked by a crash or fill; letters A, B, C... Rename with
   `--sections` or `edit --sections`.

## Measured accuracy (synthetic audio, ground truth known)
Measured by `scripts/eval_detection.py` on FluidSynth renderings of the
regression charts (722 reference strokes per condition), 50 ms tolerance.
"Held-out" kits were not used to build the templates.

| Condition | Onset F | Weak classes |
|---|---|---|
| Standard kit, drums only | 0.987 | crash 0.85, floor tom 0.80 |
| Room kit, drums only | 0.977 | floor tom 0.62, crash 0.77 |
| Jazz kit (held out), drums only | 0.986 | open hi-hat 0.88 |
| Brush kit (held out), drums only | 0.959 | snare 0.89 (soft brushes) |
| Standard kit + bass/keys | 0.964 | crash 0.50, open hi-hat 0.63 |
| Jazz kit + bass/keys, ±10 ms humanized | 0.885 | crash 0.25, open hi-hat 0.26, kick 0.91 |
| Unfamiliar synthetic timbres (numpy kit) | 0.619 | snare 0.18, cymbals ~0.1 |

Hi-hat **foot** strokes are not detected at all (F 0.0); add them by hand.

Notation-level accuracy (every stroke at the exact bar position with the
right instrument), end to end from audio: 0.92-1.0 on most regression charts
with band accompaniment; a 173 s synthetic full song reached 0.967. Bar flags
"(?)" caught 77% of the bars that contained an error, and 69% of flagged bars
did contain one.

**These numbers come from synthesized audio.** Real recordings (room sound,
compression, cymbal wash, bleed) are harder. Expect more errors, especially in
cymbals and ghost notes, and always listen.

## Failure modes and what to do
| Symptom in report or PDF | Likely cause | Fix |
|---|---|---|
| Tempo twice or half what you hear; "tempo ambiguous" | double/half-time ambiguity | re-run with `--bpm` |
| Every backbeat on 1 and 3 | downbeat a beat off | `--downbeat <seconds of a beat 1>` |
| Waltz written in 4/4, "meter uncertain" | meter detection | `--time-signature 3/4` |
| Bridge in 12/8 starts or ends a bar late | section meter boundary | edit, or transcribe the passage with `--start/--end --time-signature 12/8` |
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
