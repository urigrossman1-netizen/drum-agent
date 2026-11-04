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
