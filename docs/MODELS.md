# The onset classifier

What decides which drums sounded at each onset, how it was trained, on what,
and how it was measured. Numbers in this file come from the evaluation
scripts named next to them; `docs/LIMITATIONS.md` has the full tables.

## Why a learned classifier

The detector finds candidate onsets with superflux on the (percussive part of
the) spectrogram. On real recordings (MDB Drums, below) those candidates
cover 86-100% of the strokes of every drum class, so finding strokes was
never the main problem: deciding what each stroke *was* is. The original
detector decided with template NMF and hand-written rules, and its templates
came from one General MIDI soundfont. On real kits it called rides "snare",
missed most ghost notes, fired toms on snares and cymbal wash on kicks.

`drum_agent/audio/classifier.py` replaces that decision with a small neural
network, trained on synthesized drumming from many sampled kits in many
recording conditions.

## What it sees

Per candidate onset, 1300 numbers (all log-mel, 96 bands from 30 Hz to
17 kHz, 5.8 ms frames), level-invariant (relative to the stroke's own peak):

- the frame before the onset and seven attack frames (-6 to +29 ms);
- the decay, pooled over 35-58, 58-93, 93-139 and 139-209 ms (open versus
  closed hi-hat, crash versus ride, tom ring);
- the percussive part (HPSS) of the attack, so a band's sustained notes
  don't look like a stroke;
- the new energy against the frame before (what this stroke added on top of
  ringing cymbals);
- loudness relative to the recording, onset strength, and the gaps to the
  previous and next candidates.

## What it says

Eleven independent probabilities: kick, snare, cross-stick, closed hi-hat,
open hi-hat, hi-hat pedal, ride, ride bell, crash (china and splash
included), tom, other percussion (tambourine, cowbell, claps: recognized so
they are *not* called hi-hat or snare, then dropped). A per-class threshold
(chosen on held-out synthetic clips) turns them into strokes; `--sensitivity`
scales the thresholds.

Then the rules that are physics, not guesses: one hi-hat state per instant,
at most two hand strokes at once, a stick on the hi-hat makes a pedal stroke
at the same instant redundant. Which tom a tom stroke is on comes from the
template NMF when its evidence is decisive for most tom strokes (it compares
whole spectra, so it separates two toms with the same fundamental), and
otherwise from pitch clusters within the recording (highest = Tom 1).
Loudness relative to each drum's typical stroke gives ghost notes and
accents, as before.

Each network is a multi-layer perceptron (1300 → 512 → 256 → 11, ReLU,
dropout 0.2), trained with plain numpy (Adam, class-balanced binary
cross-entropy, cosine learning-rate schedule, 30 epochs). The shipped model
is an **ensemble of two such networks** whose probabilities are averaged:

| Member | Training clips | What it adds |
|---|---|---|
| v2 | 5000: seeds 1-2000 and 200001-203000, 18 styles | the base model |
| v3 | the same 5000 plus 1500 tom-groove-heavy clips (seeds 300001-301500) | kick and snare under a floor tom, tom grooves |

v3 alone fixed kicks under floor-tom ostinatos but lost snares under crash
and kick; v2 alone the reverse. The average keeps the better of each
(measurements below). Thresholds are the members' mean. Inference is numpy;
the weights are `drum_agent/data/onset_classifier.npz` (6 MB, built with
`scripts/adt/train.py ensemble v2.npz v3.npz --version "4 (v2+v3)" --out
drum_agent/data/onset_classifier.npz`; `--out` has no default, and an
ensemble given as an input contributes each of its networks). `--detector nmf`
keeps the original detector available for comparison.

## Training data

All synthetic: no real recording was used for training.

1. **One-shots** (`scripts/adt/oneshots.py`): every drum of every kit at six
   velocities, ~4600 samples from 44 kits.
2. **Performances** (`scripts/adt/generate.py`): random but idiomatic drumming
   in 18 styles (rock, funk, jazz ride with pedal hi-hat, shuffle, metal,
   reggae, Latin, ballad with cross-stick, train beat, electronic, ...), with
   fills, ghost notes, flams, rolls, choked open hi-hats and crashes on phrase
   starts, plus "isolated" clips of random strokes and combinations (sound
   identity without rhythm cues).
3. **Recording conditions**: per-drum channel strips (EQ, compression, gated
   reverb on snare and toms), level balances from hi-hat 18 dB under the kick
   upwards, rooms (synthetic reverb, RT60 0.15-1.6 s), bus EQ, compression,
   saturation, vintage/dark chains (steep low-pass 3.5-12 kHz, band-limited
   "old tape" chains, reduced sample rates, hiss and hum), and in 60% of clips
   a band (bass, chords, lead and pads from General MIDI instruments, distorted
   guitars included) mixed from 10 dB under to 4 dB over the drums; 30% of
   clips go through MP3 coding.
4. **Labels**: every candidate onset gets the classes of the ground-truth
   strokes nearest to it (within 40 ms); candidates with none are negatives,
   which is how the band's own onsets are learned as "no drum".

`scripts/adt/train.py build` runs the detector's own front end and feature
code on each clip, so training and use see identical features.
`DRUM_AGENT_STYLES="toms:5,rock:1"` weights the styles of a supplementary
build (how v3's extra clips were made, with the mix in the table below).

### Rebuilding each member's data

`train.py build` writes 100 clips a shard into `~/.cache/drum-agent/adt/shards`,
and `train.py train` reads every shard in that directory. A clip is fixed by
its seed, the style mix and the generator that drew it, and each change to
`scripts/adt/generate.py` draws different clips for the same seed. So each
seed range is rebuilt from a checkout of the commit that made it (checked:
the rebuilt clips' features and labels are identical to the shards the
shipped members were trained on):

| Seeds | Checkout | Command (`python scripts/adt/train.py ...`) | Used by |
|---|---|---|---|
| 1-2000 | `1a6e780` (first generator: no channel strips, gated reverb or vintage chains) | `build --clips 2000` | v2, v3 |
| 200001-203000 | `227d045` (the recording conditions above) | `build --clips 3000 --start-seed 200001` | v2, v3 |
| 300001-301500 | `e257b26` (adds the toms style; today's generator draws the same clips) | `build --clips 1500 --start-seed 300001` with `DRUM_AGENT_STYLES="toms:5,isolated:1,rock:1,funk:1,metal:1,ballad:1,halftime:1"` | v3 |

v2 is `train --hidden 512,256 --epochs 30 --version 2 --out v2.npz` with the
first two ranges in the shard directory, v3 the same with `--version 3 --out
v3.npz` and all three (without `--out`, `train` writes over the shipped
weights).
All three ranges use the same one-shot library (`oneshots.py`, whose default
output hasn't changed).

### Sources and licences

The samples are only rendered into training audio; none is redistributed.

| Source | Licence | Used for |
|---|---|---|
| FluidR3 GM, Frank Wen (Standard, Room, Power, Electronic, TR-808 kits and variants) | MIT | drums, band |
| csound GM bank (`sf_GMbank.sf2`) | public domain | drums, band |
| AVL Drumkits: Black Pearl, Red Zeppelin, Blonde Bop, Glen MacArthur | CC BY-SA 3.0 | drums |
| Hydrogen kits: Audiophob | CC0 | drums |
| Hydrogen kits: rumpf kit, Emanuel Rumpf | CC BY 3.0 | drums |
| Hydrogen kits: BJA Pacific, Luc Tunguay | CC BY-SA 3.0 US | drums |
| Hydrogen kits: ForzeeStereo, Colombo Acoustic (M. Guglielmetti), Millo kits (E. Grilli), The Black Pearl (G. MacArthur), VariBreaks, Electric Empire, Gimme A Hand | GPL-2 / GPL-2+ | drums |
| MuseScore General | MIT | band |
| TimGM6mb, Tim Brechbill | GPL-2 | band |

Whether model weights are a derived work of their training audio is not
settled law. To train without any share-alike or GPL source, run
`scripts/adt/oneshots.py --permissive-only` and set `DRUM_AGENT_PERMISSIVE=1`
for `train.py build` (FluidR3, csound, Audiophob, rumpf; expect lower accuracy
on real acoustic kits).

### Kept out of training

- Every FluidR3 sample used only by its Jazz (32) and Brush (40) kits, so
  those stay unseen in `scripts/eval_detection.py` and `eval_notation.py`.
  (Their cymbals and toms are shared with the Standard kit, which the
  original detector's templates also used, so "held out" there was always
  partial.)
- All of MDB Drums. Its MIREX 2017 training half was used to *choose* between
  model versions; the test half was run once, for the shipped model.

## Measurement

How the model was chosen: each candidate was measured with
`scripts/eval_detection.py` and `scripts/eval_notation.py` (synthesized
charts, exact answers, the Jazz and Brush kits held out) and with
`scripts/eval_real.py --split train` (the 12 MDB Drums development
recordings). The 11 test recordings were run once, for the chosen model
(before the ring-out gate in `classifier.py` was added; the gate changed none of
the development or synthetic results).

| Model | Notation F (40 synthetic runs) | Real drum stems, dev / test | Real band mixes, dev / test |
|---|---|---|---|
| NMF templates (original) | 0.948 | 0.791 / 0.662 | 0.484 / 0.421 |
| v2 | 0.941 * | 0.850 / - | 0.687 / - |
| v3 | 0.958 | 0.855 / - | 0.674 / - |
| **v2 + v3 ensemble (shipped)** | **0.963** | **0.856 / 0.772** | **0.696 / 0.591** |

\* v2 was measured before a tempo fix that rescued one of its runs (case 07,
jazz kit with band, read at double tempo); v3 and the ensemble were measured
after it.

Onset F at 50 ms, all five MDB classes (kick, snare, hi-hat, toms, cymbals).
Per-class tables, the synthetic stroke-level results and what they mean for
a chart are in `docs/LIMITATIONS.md`. The weakest class on real recordings is
cymbals (crash, ride: 0.27 on drum stems, 0.09 in band mixes on the test
recordings).
