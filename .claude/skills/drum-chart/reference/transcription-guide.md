# Audio transcription: method, measured accuracy, failure modes

Read this before transcribing audio. It tells you what the detector can and
can't hear, so you know which parts of a chart to distrust.

## What the pipeline does
1. **Front end** (`drum_agent/audio/features.py`, `detect.py`): 44.1 kHz mono,
   96-band mel spectrogram (hop 256 ≈ 5.8 ms). Unless `--drums-only`, harmonic/
   percussive separation (HPSS) suppresses sustained instruments, processed in
   30 s chunks.
2. **Candidates**: Superflux onset strength on the spectrogram (its
   percussive part in a band mix). On real recordings these candidates
   cover 86-100% of every drum's strokes; deciding what each one was is the
   hard part.
3. **Classification** (`classifier.py`, the default): a small neural network
   looks at 1300 level-invariant numbers per candidate (attack frames, the
   decay up to ~200 ms, the percussive part, the energy added over ringing
   cymbals) and gives 11 probabilities: kick, snare, cross-stick, closed,
   open and pedal hi-hat, ride, ride bell, crash, tom, other percussion. It
   was trained on synthesized drumming from 40+ sampled kits in many rooms,
   mixes and band settings (`docs/MODELS.md`). Rules follow: one hi-hat
   state per instant, at most two hand strokes, a pedal under a stick stroke
   dropped. Which tom: NMF evidence when it is decisive, else pitch within
   the recording (highest = Tom 1). Flams from the grace stroke's energy;
   accents and ghosts from each drum's typical level in this recording.
   `--detector nmf` gives the original template detector (68 GM templates,
   rules) for comparison.
4. **Grid** (`beats.py`): drum-weighted beat tracking; tempo candidates
   (×½, ×⅔, ×¾, ×1, ×4/3, ×1.5, ×2) scored by grid fit, backbeat spacing and a tempo prior
   (roll and grace strokes don't count as pulse; near ties are ranked by a steady grid when the winning beats had to bend);
   meter 3 vs 4 by bar-repetition; downbeat by kick/crash/backbeat placement.
   Where crashes move off beat 1 for good, a short bar (2/4, 3/4, 1/4) is
   inserted and the song re-quantized; inserted bars are always flagged.
5. **Quantizer** (`quantize.py`): per beat, picks the grid (straight 8ths/16ths/
   32nds, triplets, sextuplets) minimizing timing error plus complexity; detects
   swing/triplet feel; keeps a tempo map; flags bars with weak evidence.
6. **Structure** (`structure.py`): section boundaries at meter/tempo changes
   or groove changes marked by a crash or fill; letters A, B, C... Rename with
   `--sections` or `edit --sections`.

## Measured accuracy
Full tables: `docs/LIMITATIONS.md`. **Real recordings first** (MDB Drums,
`scripts/eval_real.py`, onset F at 50 ms, 11 held-out recordings):

| Class | Drum stem | Full band mix |
|---|---|---|
| Kick | 0.96 | 0.71 |
| Snare | 0.87 | 0.69 |
| Hi-hat | 0.72 | 0.61 |
| Toms | 0.50 | 0.31 |
| Cymbals (crash, ride) | 0.27 | 0.09 |
| All five | 0.77 | 0.59 |

So on a real recording: trust kick and snare most, check every hi-hat bar,
expect to add crashes and some tom strokes by ear, and ask for a drum stem
(`--drums-only`) when the user has one.

Synthesized audio (exact answers; the Jazz and Brush kits never trained on):
stroke-level onset F 0.96-0.98 on every GM kit with or without a band
(unfamiliar synthetic timbres 0.83), and end to end at notation level (right
bar, position and instrument) mean 0.963 over ten charts × four conditions,
the full 60-bar song 0.95-0.99. Synthesized audio is far easier than a real
mix; never quote these numbers for a real recording.

## Failure modes and what to do
| Symptom in report or PDF | Likely cause | Fix |
|---|---|---|
| Tempo twice or half what you hear; "tempo ambiguous" | double/half-time ambiguity | re-run with `--bpm` |
| A swing tune at 3/4 of its tempo, its ride written in dotted 8ths and 16ths | swung 8ths line up with a 16th grid at 3/4 speed | re-run with `--bpm` |
| Every backbeat on 1 and 3 | downbeat a beat off | `--downbeat <seconds of a beat 1>` |
| Waltz written in 4/4, "meter uncertain" | meter detection | `--time-signature 3/4` |
| Bridge in 12/8 starts or ends a bar late | section meter boundary | edit, or transcribe the passage with `--start/--end --time-signature 12/8` |
| A flagged 2/4 or 3/4 bar you don't hear | crashes moved off beat 1 (inserted short bar) | listen; if the band stayed in 4/4, re-run with `--time-signature 4/4` and fix accents by hand |
| "barring kept" note in the report | crash accents off beat 1 that did not prove a shifted downbeat | check whether a short bar was played there |
| Many extra kicks, "kick density" warning | bass guitar bleed | use a drum stem (`--drums-only`) or delete by hand |
| Hi-hat written as ride or vice versa | similar cymbal spectra | `edit --relabel ride=hihat --bars A-B` after listening |
| Extra hi-hat strokes in a jazz or brush take | brush sweeps and ride wash read as hi-hat | delete them by ear (`edit --delete`) |
| Crashes missing in a band mix | crash masked by the mix | add with `edit --add BAR:0:crash` |
| Ghost notes missing | masked by hi-hat | add by ear; raise `--sensitivity 1.3` carefully |
| Drags never appear | not detected | add with `:drag` by ear |
| Crashes or rides missing (real recording) | the weakest class | add with `edit --add BAR:POS:crash` |
| Odd meters (5/4, 7/8) from audio | not supported | use a MIDI track or write a chart spec |
| Sections only lettered A, B, C | no lyrics/harmony analysis | `--sections "Intro:1,Verse:5,..."` |

## Rights
`transcribe` refuses to run without `--rights`. `analyze` (tempo, meter,
sections, no notes) needs no rights basis. Streaming services are metadata
only (DRM); `song` gets audio from the user's files, a direct link, or a
video page through the user's own yt-dlp, and with `--rights` the user names
the recording (`--pick N` for a library file, `--url URL` for a video). A
download is never a rights basis: record the source and any licence in the
score's source/notes.
