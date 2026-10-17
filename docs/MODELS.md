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

The network is a multi-layer perceptron (1300 → 384 → 192 → 11, ReLU,
dropout 0.2), trained with plain numpy (Adam, class-balanced binary
cross-entropy, cosine learning-rate schedule). Inference is numpy too; the
weights are `drum_agent/data/onset_classifier.npz` (about 2 MB). `--detector
nmf` keeps the original detector available for comparison.

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
  model versions; the test half was run once per version for this file.

## Measurement

`scripts/eval_real.py` on MDB Drums (23 real MedleyDB recordings, drum stem
and full band mix, ~8000 annotated strokes, CC BY-NC-SA 4.0, downloaded to a
local cache, never committed), onset F at 50 ms for kick (KD), snare (SD),
hi-hat (HH), toms (TT) and cymbals (CY). See `docs/LIMITATIONS.md` for the
tables and the synthetic evaluations.
