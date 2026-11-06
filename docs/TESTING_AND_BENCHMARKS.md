# Testing and benchmarks

How the Drum Agent is tested, how to run each suite, and the recorded results. A result
goes here only after it was actually run; each entry names the machine, the date and the
commit.

## Suites

| Suite | Command | What it proves | Needs |
|---|---|---|---|
| Fast tests | `python -m pytest -q -m "not slow"` | notation, rhythm spelling, layout, exports with read-back, MIDI and game-chart import, chart specs and the 113-chart library rules, edit, rights, song lookup (recorded responses), web API, studio, desktop helpers, settings file | LilyPond (most tests engrave) |
| Everything | `python -m pytest -q` | the fast tests plus audio end to end (synthesized recordings transcribed and scored), every library chart rendered, CLI song runs, browser journeys (`tests/test_web_e2e.py`) | FluidSynth + FluidR3_GM.sf2 (audio fixtures); Node + Playwright + pdftotext for the browser journeys |
| Detection accuracy | `python scripts/eval_detection.py` | stroke-level onset F per instrument on synthesized charts (several kits, band mixes, humanized timing) | FluidSynth + soundfont |
| Notation accuracy | `python scripts/eval_notation.py --jobs 4` | end to end: right bar, position and instrument, plus flag precision/recall | FluidSynth + soundfont |
| Real recordings | `python scripts/eval_real.py --split train` (`--separate` for drums-first, `--pipeline transcribe` for the finished chart, `--detector`) | on MDB Drums (23 real multitracks, CC BY-NC-SA, about 330 MB in a local cache), per class: precision, recall and F at 50 and 30 ms, timing error, recall in fast passages, a confusion matrix of what was written instead, and extra strokes. Each run is kept in `benchmarks/results/`. The `test` split is held out: run it once per model version | network for the first download |
| Other transcription models | `python scripts/eval_backends.py --model oaf\|adt_str` (`--download` first; `--evidence '<json>'` as a second opinion for the classifier) | the same MDB scoring for Onsets & Frames drums (ONNX) and ADT_STR, alone or as `classifier.Evidence`. Benchmark only | onnxruntime (oaf); torch, transformers, omegaconf, pretty_midi (adt_str); the separated stems from an `eval_real.py --separate` run |
| Whole app on a real recording | `python scripts/acceptance_run.py` | the studio's API end to end on one MDB track: upload, job, chart, edit, save, reopen, export, and the chart's strokes scored against the annotations | a running studio |
| Packaged Windows app | `packaging/smoke_test.py` (CI `windows-app.yml`) | the installed app: tools ready, a beat, an upload separated and transcribed, a song found in a music folder, real catalog search | the built app |

### Running on Windows (this repository's setup)

`py -3.12 scripts/dev_setup.py` prepares `.venv` and `tools/`. The suites need the tools on
`PATH`. In PowerShell:

```powershell
$r = "C:\Users\USER\PycharmProjects\drum-agent"
$env:DRUM_AGENT_LILYPOND = "$r\tools\lilypond\bin\lilypond.exe"
$env:TORCH_HOME = "$r\tools\torch"
$env:DRUM_AGENT_SOUNDFONT = "$r\tools\soundfonts\FluidR3_GM.sf2"
$env:PATH = "$r\tools\ffmpeg\bin;$r\tools\fluidsynth\bin;" + $env:PATH
$env:PYTHONUTF8 = "1"
& "$r\.venv\Scripts\python.exe" -m pytest -q -m "not slow"
```

## Results

### Recorded before this round (from the repository's history)

| Date | Where | Suite | Result |
|---|---|---|---|
| 2026-10-29 | Linux CI, commit `b5cde57` | everything | 936 passed, 1 warning, 7 min 41 s |
| 2026-10-29 | Linux | fast tests | 792 passed, 94 s |
| 2026-10-29 | CI image run 40905703452 | acceptance on MDB "Britpop" band mix, drums separated | F 0.901 (P 0.864, R 0.942, timing 8.9 ms); 15 of 257 strokes missed, 38 extra |
| 2026-10-18 | Linux | eval_real, held-out test split | band mix separated 0.733; drum stem 0.772 (detector level) |
| 2026-10-29 | Linux CI run 40826408065 | eval_notation (40 runs) | notation F 0.963 as given, 0.969 with separation |

### This round

(Windows 11 laptop: i5-1145G7, 4 cores, 15.7 GB RAM, no CUDA; Python 3.12.10.)

| Date | Commit | Suite | Result |
|---|---|---|---|
| 2026-11-04 | phase 0, before fixes | fast tests, first run on Windows | 785 passed, 15 failed, 7 skipped. Causes in `docs/DEVELOPMENT_PROGRESS.md`: 3 real bugs, the rest test portability and one leaking new test |
| 2026-11-04 | phase 0, most fixes | fast tests | 805 passed, 1 failed (a stage-list assumption, then fixed), 1 skipped (symlinks need Developer Mode). 6 min 42 s: LilyPond engraving is slower on Windows, and the studio was transcribing at the same time |
| 2026-11-04 | phase 0, all fixes (`a52328f`) | fast tests | **807 passed, 1 skipped** (symlinks), 0 failed, 4 min 21 s; the later settings-file tests (10) pass on their own |
| 2026-11-04 | phase 0 | Windows app from the desktop shortcut (`scripts\windows\drum_agent.cmd`) | up in about 8 s: personal mode, every check OK, separation from the shipped weights, sampled drums on |
| 2026-11-04 | phase 0 | studio end to end on Windows: "Northbound" (repository's own song) synthesized as a 3-minute band mix, uploaded, transcribed with drum separation | notation F 0.984 (P 0.982, R 0.986), 60/60 bars, tempo and meter right; all 8 export checks OK; job 4 min 37 s on a shared CPU |
| 2026-11-04 | phase 1 (`0807c20`) | fast tests | **820 passed, 1 skipped**, 0 failed |
| 2026-11-04 | phase 1 | A/B: the previous commit vs phase 1 on 5 recordings (4 test charts with a band, the 3-minute Northbound mix), both detectors | identical notes, bars and analysis: the provenance work changed no result |
| 2026-11-04 | phase 1 (`9a7d6ae`) | `eval_real.py --split train --separate`, detector level (`benchmarks/results/2026-11-04_phase1-dev-detector`) | all 5 classes F: drum stems **0.856**, band mix 0.696, separated 0.773. Within 0.001 of the Linux numbers of October (0.856 / 0.696 / 0.774). New measures below |
| 2026-11-04 | phase 1 (`9a7d6ae`) | same, chart level (`--pipeline transcribe`; `benchmarks/results/2026-11-04_phase1-dev-chart`) | the same pooled F (0.856 / 0.696 / 0.773), every class within 0.003 of the detector level. Below, point 7 |
| 2026-11-04 | phase 1 (`9a7d6ae`) | both levels run a second time, after the records were fixed to name their commit | **every number identical** (2,005 and 2,008 values). The detector record's 13,653 s includes a pause of hours (the computer most likely slept); the chart run, which does more, took 148 s |
| 2026-11-05 | phase 2 (`fa16547`, then the revert) | fast tests | **827 passed, 1 skipped**, 0 failed, both before and after the band-mix check was taken out |
| 2026-11-05 | phase 2 (`fa16547`, band-mix check on) | `eval_real.py --split train --separate`, detector and chart level (`phase2-dev-detector`, `phase2-dev-chart`) | separated band mixes 0.773 → 0.792 with the check (hi-hat 0.815 → 0.853, kick 0.847 → 0.880; precision 0.776 → 0.854, recall 0.769 → 0.739). Drum stems 0.856 and band mixes 0.696 unchanged |
| 2026-11-05 | phase 2, without (`676cc5e`) and with the check (`fa16547`) | `eval_notation.py --conditions std_band,jazz_band_h` (20 synthetic band mixes, separated) | notation F 0.9643 → 0.9705: standard kit 0.961 → 0.969, held-out jazz kit (humanized) 0.967 → 0.972; two runs lower (−0.007, −0.010) |
| 2026-11-05 | phase 2 (`fa16547`) | `eval_real.py --split test --separate`, held out, run once with the check and once without (`phase2-test-detector`, `phase2-test-detector-no-band-check`, `phase2-test-chart`) | **without 0.732, with 0.723**: hi-hat 0.700 → 0.676, kick 0.945 → 0.932. Loud band mixes lost real hi-hats (Hendrix 0.888 → 0.696). The check fails the adoption rule and was **reverted**. Drum stems 0.772 and band mixes 0.591, as in October |
| 2026-11-05 | retraining (`1c91256`) | `eval_real.py --split train --separate` with `DRUM_AGENT_ONSET_MODEL` pointing at each candidate (`phase2b-dev-*`) | drum stems / band mix / separated: shipped 0.856 / 0.696 / 0.773; v5a 0.847 / 0.671 / 0.770; v5 0.834 / 0.672 / 0.756; shipped + v5a 0.855 / 0.699 / 0.777; shipped + v5 0.852 / 0.706 / 0.773. All lose cymbals (0.05–0.11 on stems): **none adopted**, held-out split not run (`docs/MODELS.md`) |
| 2026-11-06 | phase 4 | fast tests | **948 passed, 1 skipped**, 0 failed |
| 2026-11-06 | phase 4 | browser pane, by hand (Playwright needs Node, which this PC lacks; `tests/test_web_e2e.py` skipped) | seek, pause, 75% with the pitch kept, section loop; Opus against the WAV: same length, 0 samples of shift; Adjust tool, 18 edits and undo; Beginner version made and opened; a new beat's scheduled strokes match its chart; page fits a 375 px screen |
| 2026-11-05 | phase 2 (`fa16547`) | `eval_backends.py`: other models alone and as a second opinion (`phase2-dev-oaf-*`, `phase2-dev-adt-str-*`) | Onsets & Frames ONNX alone 0.557 / 0.495 (drum stems / separated); ADT_STR alone 0.745 / 0.731. Neither adopted; details in `docs/MODELS.md` |

### What the new measures show (MDB Drums development split, 2026-11-04)

1. **Fast passages are the weakest point.** These are strokes no more than 100 ms apart on one drum: 16th-note hi-hats at fast tempi, rolls, fills. Their recall:

   | Input | Fast-passage recall | All strokes |
   |---|---|---|
   | drum stems | 0.794 | 0.888 |
   | band mix | 0.251 | 0.702 |
   | band mix, separated | 0.265 | 0.769 |

   Separation barely helps fast passages.

   **Corrected in phase 2:** 249 of the 287 fast strokes are in one recording (BebopJazz, a fast swung ride pattern). So this mostly measures that recording, not fast playing in general. What does hold generally is style: on separated band mixes the three jazz recordings score 0.59, the other nine 0.89.
2. **Snare written as hi-hat.** In separated band mixes, 223 of 1,304 snare strokes come out as hi-hat. A further 270 are missed.
3. **Cymbals.** 60 of 267 cymbal strokes are written as hi-hat, and 112 are missed.
4. **Strokes written where nothing was played.** About half are hi-hat: 240 of 498 in separated mixes, and 369 of 610 on drum stems. The "extra" in the summary lines is larger (detector level: 853 separated, 720 on stems) because it also counts strokes written on the wrong drum.
5. **Timing.** Matches are tight: F at 30 ms is within 0.003–0.024 of F at 50 ms, and the mean error is 9–11 ms.
6. **Toms.** The development split holds only 15 tom strokes, so tom numbers there are not meaningful. The held-out split has more.
7. **The finished chart keeps what the detector found.** At chart level (`--pipeline transcribe`), every note in the finished chart is scored. Every class is within 0.003 F of the detector level, and the pooled F is the same: 0.856, 0.696 and 0.773. The notation steps (merging two strokes into one grid slot, flams, rolls, cymbal smoothing) cost only a few fast strokes: fast-passage recall is 0.003–0.007 lower.
   - **Limit:** chart level scores each note at the time the detector heard it. It shows which strokes reach the chart and as which drum, but not whether each note sits in the right place on the grid. MDB Drums annotates stroke times without beats or bars, so grid placement on real recordings is not measured. It is measured on synthesized recordings, where the answer is exact (`eval_notation.py`).
8. **An open question: 80sRock.** The annotations have kick (63), snare (35) and crash (5), with no hi-hat. The detector writes a hi-hat on almost every beat of the drum stem: 51 strokes, each within 30 ms of an annotated stroke. There are two possible explanations:
   - the annotators left out a quarter-note hi-hat;
   - the classifier hears this 1980s-style kick and snare attack as a hi-hat.

   Telling them apart needs a listen. The track accounts for 51 of the 369 extra hi-hat strokes on drum stems.

These set the targets for phase 2 (other transcription models and fusion): snare against hi-hat, cymbals, and fast passages (see the correction under point 1).
