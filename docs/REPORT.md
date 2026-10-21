# Final report

What was built, how it was checked, and what is still weak. Every number here
was measured in this repository; nothing is estimated.

## 1. Starting point

The repository was empty: no commits, no code, no skill (details in
[AUDIT.md](AUDIT.md)). Pretrained drum separation or transcription models
could not be downloaded in this environment, so listening had to be built here:
first signal processing (NMF templates), then a neural onset classifier
trained on synthesized drumming.

## 2. What the agent does

| You give it | It does | Command |
|---|---|---|
| A song's name | identifies the recording from public metadata, finds audio (your files, a link, or a video page through your own yt-dlp; streaming services are metadata only), checks the length, then analyses, or transcribes once you state your rights | `song` |
| An audio file | transcribes it note by note (needs a rights basis), or gives tempo, meter and form only | `transcribe`, `analyze` |
| A MIDI drum track | imports it with pickups, meters, tempi and markers | `midi` |
| A Rock Band / Clone Hero chart | imports `notes.mid` or `notes.chart` exactly, tick by tick | `gamechart` |
| A described groove or a chart spec | engraves it | `render` |
| A chart that is wrong somewhere | edits strokes, bars and labels, then re-renders | `edit` |

Every run writes PDF, PNG, MusicXML 4.0, MIDI, LilyPond source, the score
(JSON) and a report, all generated from one score and read back against it.

## 3. What was built

- **One score format** (`drum_agent/model.py`): exact `Fraction` positions,
  instruments from one kit table (`kit.py`). The formats can't disagree.
- **Rhythm spelling** (`rhythm.py`): beats never hidden, rests by metrical
  level, tuplets (a 16th triplet and an 8th written "3" plus an 8th), rolls,
  flams and drags, beams by beat group, one voice when nothing sounds in the
  other.
- **Engraving** with LilyPond 2.26 in the look of the reference chart you
  sent: cymbals stems up, snare and kick down, hi-hat 8ths beamed in fours,
  sticking letters under fills, a "Swing" mark with its rhythm, cue text above
  the staff, rests in the lower voice, multi-bar rests, four bars per line.
  `--voicing hands-up` gives the Weinberg/PAS drum-book layout. A line that
  would run past the right margin is detected in the rendered page and
  re-planned.
- **Verification** (`verify.py`): LilyPond's own MIDI, the MusicXML (notes,
  articulations, meters, schema) and our MIDI (notes, tempo map, barlines)
  are each read back and compared with the score on every run.
- **Listening** (`audio/`): candidate onsets from the spectrogram, then an
  ensemble of two neural onset classifiers trained on 6500 synthesized clips
  from 44 sampled kits in many recording conditions (rooms, compression,
  band mixes, MP3, old-tape chains); beat, meter and downbeat tracking;
  playability rules; review flags ([MODELS.md](MODELS.md)).
- **Review flags**: bars with a low-confidence stroke, a stroke the
  classifier almost heard, a structural decision or an unplayable combination
  get "(?)" above the staff.
- **The library**: 113 charts, the 40 PAS rudiments and 73 grooves and fills
  (rock, funk, jazz, shuffles, Latin and Afro-Cuban, odd meters, linear
  fills), all rendered and held to the house rules by `tests/test_library.py`
  ([library/README.md](../library/README.md)).
- **Rights and safety** (`rights.py`, `song/`): note-for-note transcription
  needs a stated rights basis, and a basis found through a search needs an
  explicit choice of recording; streaming CDNs and DRM services are refused,
  at every redirect; downloads are bounded in size and rate.
- **The `drum-chart` skill** (`.claude/skills/drum-chart/`): the workflow,
  the rights check, transcription hints, the QC checklist and honest
  delivery, tested through real headless Claude Code sessions.

## 4. Measured accuracy

**Real recordings** (MDB Drums, 23 recordings with every stroke annotated;
onset F at 50 ms, all five classes). The 11 test recordings were held out and
run once:

| | Dev, drum stem | Dev, band mix | Test, drum stem | Test, band mix |
|---|---|---|---|---|
| Onset classifier (shipped) | 0.856 | 0.696 | 0.772 | 0.591 |
| NMF templates (first detector) | 0.791 | 0.484 | 0.662 | 0.421 |

Per class on the held-out drum stems: kick 0.96, snare 0.87, hi-hat 0.72,
toms 0.50, cymbals 0.27. **Cymbals in band mixes are the weakest point**
(0.09).

**Synthesized recordings of original charts** (exact answers): mean notation
F 0.963 over 40 runs (10 charts × standard kit, held-out jazz kit, band mix,
humanized band mix); stroke-level onset F 0.956-0.984 in six conditions,
held-out kits and band mixes included (0.83 on deliberately unfamiliar
synthetic timbres). Review flags: 67% of flagged bars hold an error, and the
flags catch 76% of the wrong bars.

Full tables and what they mean: [LIMITATIONS.md](LIMITATIONS.md).

## 5. How it was checked

- `python -m pytest -q`: **844 passed** in 4-6 minutes on a 4-CPU container with
  LilyPond 2.26.0: 710 fast tests and 134 slow ones (all 113 library charts
  rendered and read back, 17 audio end-to-end transcriptions, 4 CLI and song
  runs). Includes random-score fuzzing across seven meters and a regression
  test for every confirmed review finding.
- End to end by name: `song "Northbound" --no-online --library <folder>` found
  the recording, analysed it without `--rights`, refused `--rights` until the
  recording was picked, then transcribed it (`--pick 1`) at notation F 0.975
  against the chart it was synthesized from.
- Every notation change was also looked at as a rendered page; a passing
  test alone doesn't prove the engraving reads well.
- Detection changes were measured with both synthetic eval scripts and on the
  real-recording dev split before being accepted; no change was kept that
  regressed a held-out kit or a band mix.
- **Independent adversarial reviews**, each finding reproduced by a second
  agent before it was fixed: timing and import, notation, robustness and
  safety (round 1); game charts and song lookup; all 113 library charts
  (wrong clave kicks, crossed arms in fill stickings, comments that didn't
  match the pattern); the engine changes (tempo ties, voice handling, tuplet
  brackets, layout overflow, exact game-chart ticks); and the download and
  rights paths (host-name tricks, redirects through a streaming CDN, a
  trickling server, a search result picked without the user seeing it).

## 6. Difficult cases verified

Rendered and checked by eye as well as by the automatic checks:
- Flams and drags on a downbeat, at a meter change and at a line start.
- Pickups (quarter and sub-beat), meter changes 4/4 → 12/8 → 4/4 with tempo
  marks in dotted quarters, tempo changes, 3/4, 7/8 (2+2+3), 5/4, 6/8, 12/8,
  5/8, 3/8, 2/4.
- Triplets, sextuplets, a 16th triplet sharing a beat with an 8th, 32nds,
  rests by metrical level, ghost notes, accents, rolls tied across beats.
- Open, closed and half-open hi-hat, hi-hat foot, tom fills over the barline.
- Simile runs, `|: A B :| ×8`, multi-bar rests split at tempo, section and
  meter changes; a 17-instrument Drum Key.
- From audio: a 60-bar song with a 2/4 bar, short bars inserted from crash
  placement, an 8.5-minute band mix (145-165 s, 1.1 GB, notation F 0.977).
- Hostile text (quotes, backslashes, `#(...)`, control characters) printed
  literally; a kit file trying to run a command is refused.

## 7. Limitations

Full list with numbers: [LIMITATIONS.md](LIMITATIONS.md). In short:
- Real recordings are harder than synthetic ones: on a full band mix about
  three strokes in five are found right. Cymbals (one in four on a stem,
  fewer in a mix) and toms (half on a stem) are the weak classes. Listen to
  every bar, starting with the flagged ones.
- Drags are never detected; ghost notes next to the hi-hat are often missed.
- Tempo can still come out doubled or halved on unusual material, and fast
  swing at 3/4 of its tempo: check the report's tempo line and pass `--bpm`
  when it is wrong. Odd meters from audio are not supported (MIDI, game
  charts and chart specs handle them).
- No source separation: `--drums-only` with a stem from another tool is the
  best path for a full mix.

## 8. Exact commands

```bash
pip install -e ".[test]" && scripts/install_lilypond.sh && python -m drum_agent doctor
python -m drum_agent song "Song Title" --artist "Band"            # identify, find audio, analyse
python -m drum_agent transcribe song.wav --rights own --title "Song" -o out/song
python -m drum_agent midi take.mid --title "Take" --rights own -o out/take
python -m drum_agent gamechart "Songs/Band - Title" -o out/title
python -m drum_agent render library/rudiments/r16_single_paradiddle.yaml -o out/paradiddle
python -m drum_agent edit out/song/song.json --add 12:3/8:snare:ghost --render out/song
python -m pytest -q -m "not slow"     # fast suite
python -m pytest -q                   # everything, including audio end to end
python scripts/eval_notation.py --jobs 4 && python scripts/eval_detection.py
python scripts/eval_real.py --split train   # real recordings (MDB Drums, cached locally)
```

Rendered examples: `examples/output/` (01-04 from chart specs, 05 transcribed
from a synthesized band recording).
