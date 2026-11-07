# Development progress

The living record of what is done, with its evidence. Statuses:
- **Complete and verified**: built, and a named test or recorded run shows it working.
- **Implemented, not fully verified**: built, but part of it has never run for real (usually missing credentials).
- **Partially implemented**: some of the requirement is built.
- **Not implemented**.
- **Blocked**: waiting on something outside the code.

## Requirement matrix

Product requirements from the 2026-11-03 brief, section 21. Last updated 2026-11-07.

| Requirement | Expected | Status | Evidence / what is missing |
|---|---|---|---|
| Existing project | preserved and improved | **Complete, awaiting merge** | Built on branch `claude/transcription-platform` from `a9b52095`, in pull request #2. Local recovery tag `pre-platform-v2`. Nothing was rewritten |
| Historical work | recovered wherever accessible | **Complete and verified** | `docs/PROJECT_RECOVERY_REPORT.md`: 14 cloud sessions, 1 claude.ai chat, 5 artifacts, the repository and its CI. The inaccessible material is listed there |
| Skills and integrations | inventoried, relevant ones used | **Complete** (inventory) | `docs/AVAILABLE_TOOLS_AND_SKILLS.md` |
| YouTube | song search and authorized playback | **Implemented, not fully verified** | Data API `search.list` / `videos.list` + `youtube-nocookie` embed (`web/providers.py`, `static/js/song.js`). Tested with recorded responses, never against the live API: needs `YOUTUBE_API_KEY` |
| Audio uploads | functional and validated | **Complete and verified** | `audio/prepare.py`, `web/sources.py`; `tests/test_web.py`; CI acceptance run on a real recording (run 40905703452) |
| Audio processing | real FFmpeg-based processing | **Complete and verified** | ffmpeg/ffprobe decode and validation (`audio/prepare.py`); FFmpeg ships with the app |
| Drum separation | actual source separation | **Complete and verified** | HTDemucs (`audio/separate.py`); MDB band mixes 0.591 → 0.733 F with it. Runs on this PC from the local weights (`doctor`, 2026-11-04). Since phase 1, a failure falls back to the band mix with a note instead of ending the job |
| Transcription | actual model inference | **Complete and verified** | onset classifier (`audio/classifier.py`), measured on the MDB Drums held-out split (re-measured on this PC in phase 2: drum stems 0.772, separated band mixes 0.732). Phase 2 measured two other models and a band-mix check; none was adopted (`scripts/eval_backends.py`, `docs/MODELS.md`) |
| Instrument detection | multiple individual drum classes | **Partially implemented** | 11 classes from audio. Never from audio: china, splash, crash2, rimshot, cowbell, half-open hi-hat. Cymbals 0.14 and toms 0.43 F on separated band mixes |
| Musical analysis | tempo, rhythm and structure | **Partially implemented** | Tempo, swing, tuplets, 3/4 and 4/4, 12/8 sections, short bars. Since phase 3: repeated sections recognized (A, B, A2), fills marked on bars, tempo/meter/downbeat/feel hints in the studio (upload, and "Chart again" in seconds from the stored strokes; `drum-agent rechart`). Odd meters aren't detected from audio: 5/4, 6/4, 7/4 and 9/8 can be given as hints, while 7/8 and 5/8 can't. A second beat tracker, Beat This!, was measured and didn't detect them either (`scripts/compare_beat_trackers.py`) |
| Arrangement | complete-song representation | **Complete and verified** | Every bar of the recording is charted, with sections, repeats (A2) and fills marked: 60-bar synthetic song at notation F 0.978, 8.5-minute stress test; `tests/test_structure.py` (constructed bars and the library's fill chart g64; not measured on real recordings, whose annotations have no sections) |
| Chart generation | genuine drum notation | **Complete and verified** | LilyPond 2.26 engraving; MusicXML 4.0 (XSD); MIDI; three-way read-back on every export; 113-chart library |
| Playback | synchronized with the chart | **Complete and verified** | Recording plays on the chart's bar clock, with current-bar highlight, metronome, count-in, loop and speed (`tests/e2e/song.e2e.js`). Since phase 4: a time line to seek, a real pause, section loops, speed with the pitch kept, a compressed copy to listen to (`tests/test_listen.py`; in a real browser by `tests/e2e/song.e2e.js`, which passed in CI on 2026-11-07) |
| Editing | user can correct detected hits | **Partially implemented** | Grid editor (add/remove, accent, ghost, flam, undo/redo, versions) and CLI `edit`. Since phase 1, every note keeps the detector strokes behind it and an "edited" mark, and every detection is kept beside the chart (`tests/test_detections.py`). Since phase 4 an Adjust tool sets a note's loudness, drum and place. Not done: dragging notes (loudness is a slider, moving is by buttons) |
| Exports | verified output formats | **Complete and verified** | PDF, PNG, MusicXML, MIDI and JSON; `verify.py`; `tests/test_exports.py`, `tests/test_fuzz_exports.py` |
| Testing | actual tests and documented results | **Complete and verified** | In CI on commit `016b128` (2026-11-07): fast tests 1,028 passed on Linux and on Windows, browser journeys 4 passed, and the server image and the built Windows app each passed a full run. On this PC: fast 1,027 passed, slow 131 passed (3 more timed out while the laptop slept and pass when run again). The other slow tests run only on this PC, not in CI. Real-recording benchmark at detector and finished-chart level, each run kept in `benchmarks/results/`, other models included (`scripts/eval_backends.py`). `docs/TESTING_AND_BENCHMARKS.md` |
| Security | upload and API protection | **Complete and verified** | Upload validation, per-browser owner scoping, CSP and security headers, rights gate. Since phase 5: size cap while streaming, decoding in the job, rate limits, a cross-site write guard, a Host allowlist in personal mode, HSTS (`web/guard.py`, `tests/test_guard.py`), pinned downloads (`tests/test_supply_chain.py`). A security review of the branch found nothing at its confidence bar (2026-11-06), and the server image passed the whole workflow in CI with these protections on. The rate limits' numbers haven't met real traffic |

## Log

### 2026-11-03: recovery and audit
- Recovered the history: `docs/PROJECT_RECOVERY_REPORT.md`.
- Ran three parallel read-only audits: the audio pipeline and data model, the web app with its integrations and security, and the model landscape and licences.
- Plan approved: phases 0–6 (setup and docs; raw predictions and truthful measurement; multiple transcription backends; musical understanding; practice and editing; hardening; final verification).

### 2026-11-04: phase 0, this PC
- Installed with winget: Git 2.56, Python 3.12.10, GitHub CLI 2.103.
- Cloned into `C:\Users\USER\PycharmProjects\drum-agent`. Branch `claude/transcription-platform`. Line endings kept LF: the repo-local `core.autocrlf=false`, and `.gitattributes` gives CRLF to `.cmd` files only.
- Created the `.venv` (Python 3.12) with numpy, CPU torch 2.15, torchaudio 2.11, demucs 4.1.0, and the package with `[test,web,desktop]`.
- Fetched the tools with `packaging/fetch_tools.py --separation --sounds`:
  - LilyPond 2.26.0;
  - FFmpeg;
  - HTDemucs weights;
  - **new:** FluidSynth 2.6.2 and FluidR3_GM.sf2 (SHA-256 pinned), so the Windows app and Windows development get the real sampled drums. Before this, the soundfont was found only at Linux paths.
- New: `.env` settings file support for `serve` and the desktop app (`drum_agent/envfile.py`, tests in `tests/test_envfile.py`). Windows launchers `scripts/windows/drum_agent.cmd` (app window) and `studio.cmd` (browser). One-command setup `scripts/dev_setup.py`.
- `python -m drum_agent doctor`: all required dependencies present, plus FluidSynth, soundfont and FFmpeg; drum separation available from the local weights.
- Docs: recovery report, tools inventory, licence audit, pipeline, this file.

**First test runs on Windows (the suite had only ever run on Linux).**

Run 1: 785 passed, 15 failed. Wall time was inflated because the laptop slept overnight; keep-awake is now requested for long runs. Causes and fixes:

| Cause | Kind | Fix |
|---|---|---|
| `OnsetClassifier` left its `.npz` open; Windows locks open files, so `train.py` could not replace or delete a model | real bug, all platforms (a leaked handle) | `with np.load(...)` (`audio/classifier.py`) |
| `deploy_space.py` listed the Space's files with backslashes | real bug on Windows | `as_posix()` |
| The suggested `--rights` re-run command put a Windows path through POSIX quoting (backslashes became escapes) | real bug on Windows | forward slashes (`song/run.py`) |
| Tests pointed "~" at a temp folder through `HOME`; Windows uses `USERPROFILE`, which LilyPond's fontconfig also reads | test portability | `fake_home` fixture in `tests/conftest.py`: on Windows, `expanduser` is redirected in-process only |
| The symlink-loop test can't create symlinks without Developer Mode | environment | skip with the reason |
| `needs_fluidsynth` looked for the soundfont at Linux paths only | test portability | uses `synth.find_soundfont()` |
| A stage-list assertion assumed separation is never installed | test portability | expects "separate" when `separate.available()` |
| My new `test_tools_lookup` leaked `DRUM_AGENT_MODE=personal` into later tests (this caused the ten web failures) | my own test bug | restore through `monkeypatch.setenv` before `delenv` |

Run 2: 805 passed, 1 failed (the stage-list test, fixed above), 1 skipped (symlinks).
Run 3: **807 passed, 1 skipped, 0 failed** (4 min 21 s).

**Usable on this PC.**
- The **Drum Agent (dev)** desktop shortcut (`scripts/dev_setup.py --shortcut`) starts the app window in about 8 s: personal mode, every check OK, separation from the local weights, and the real sampled drums.
- `scripts\windows\studio.cmd` serves the same studio at http://127.0.0.1:8000.
- Phase 0 is complete except for two things that need the owner: the API keys go into `.env`, and GitHub needs a sign-in before the first push.

**Claude integration made ready for current models (`web/claude.py`).** Default model `claude-opus-5-5` (`DRUM_AGENT_ANTHROPIC_MODEL` only overrides it, so the key is the only required setting), effort `low`, `max_tokens` 16,000 (thinking can't be turned off and counts against the cap), and server-side refusal fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) through `client.beta.messages.create`. Tests updated. The SDK's mapping of 401/404/429/500 errors still works.

**End to end on this PC, through the studio.**

- Input: "Northbound" (the repository's own 60-bar song), synthesized as a 3-minute band mix (room kit, bass and keys, ±6 ms humanized), uploaded with rights basis "original".
- Job time: 4 min 37 s while the test suite shared the CPU (prepare 3 s, separation 210 s, detection 25 s, beats 11 s, engraving 8 s, page images 12 s).
- Chart: 60 bars at 84 BPM in 4/4, all correct. Notation F 0.984 (P 0.982, R 0.986; 853 strokes in the reference, 856 written). Weakest: floor tom recall 0.90 and 6 phantom hi-hat pedal strokes.
- Every export check OK.
- 29 of 60 bars carry "(?)", mostly near-miss flags: too many for a chart this accurate (to look at in phase 3).
- A synthesized recording is easier than a real one; real band mixes measure 0.73 (`docs/LIMITATIONS.md`).

**Bug found and fixed: a folder named "~".** `.env.example` sets `DRUM_AGENT_DATA_DIR=~/.drum_agent/web`. A shell expands the `~`; the new `.env` reader didn't, and neither did the store, so the studio wrote its data into a folder literally named "~" inside the repository. Both now expand a leading "~" (`envfile._expand_home`, `store.default_data_dir`), with tests.

### 2026-11-04: phase 1, keep every prediction; measure truthfully

**The detection log** (`drum_agent/audio/detections.py`), written beside every transcription as `<stem>.detections.json`. It holds:
- every onset candidate the detector looked at, with the onset classifier's 11 probabilities, the classes rules removed (and why) or why it was skipped;
- every stroke it accepted, and its fate: notated (bar, position), a flam's grace, merged into a slot already taken, or dropped with the reason.

It is carried through the whole pipeline:
- `_merge_flams`, `_drop_flam_crashes` and `_smooth_cymbals` in `audio/detect.py`;
- the quantizer's merges, off-grid onsets and hi-hat conflicts (`QuantizeResult.trace`);
- roll notation.

Tests require that no stroke is left "unaccounted".

**Each note's provenance.** `Hit.raw` (the stroke ids behind it) and `Hit.edited` (a person added or changed it). Both are optional fields, so schema 1 is unchanged and old charts load.
- `edit` (CLI) marks what it changes. When it overwrites a score in place it first keeps `<stem>.original.json`, once.
- The studio marks edits when a version is saved (`edit.mark_edits` against the parent version) and copies the detection log into every later version.

**Fixes.**
- A separation failure falls back to the band mix with a note (it aborted the job before).
- `--bpm` is converted to the dotted-quarter beat for compound meters (6/8 at quarter = 120 charted at 180 before).
- The report shows merged and dropped strokes (`pipeline.py` read a key that audio never set).

**The real-recording benchmark** (`scripts/eval_real.py`) now reports:
- F at 30 ms as well as 50 ms;
- recall in fast passages (strokes no more than 100 ms apart on one drum);
- a confusion matrix: what was written instead of each missed stroke, plus extra strokes;
- `--detector`.

Each run is kept in `benchmarks/results/<date>_<label>.json/.md` with its commit, classifier version and machine. Chart-level runs (`--pipeline transcribe`) no longer separate "mix" behind the user's back.

**Checks.**
- Fast tests: 820 passed, 1 skipped.
- Same results as before: the commit before phase 1 and phase 1 were run on 5 recordings with both detectors, and gave identical notes, bars and analysis.

**Results on the MDB Drums development split** (12 real recordings; `benchmarks/results/2026-11-04_phase1-dev-*`). F for all 5 classes:

| Input | Detector | Finished chart |
|---|---|---|
| drum stem | 0.856 | 0.856 |
| band mix | 0.696 | 0.696 |
| band mix, drums separated | 0.773 | 0.773 |

Within 0.001 of the October numbers from Linux (0.856 / 0.696 / 0.774).

What the new measures found (detail in `docs/TESTING_AND_BENCHMARKS.md`):
- Fast passages: 0.79 recall on a drum stem, but 0.25–0.27 in a band mix, separated or not. (Corrected in phase 2: 249 of the 287 fast strokes are in one bebop recording, so this is mostly that recording. The general weak spot is jazz.)
- In separated band mixes, 223 of 1,304 snare strokes are written as hi-hat.
- About half the strokes written where nothing was played are hi-hat.
- The finished chart loses almost nothing to notation: within 0.003 F of the detector on every class.
- Grid placement on real recordings is not measured, because the annotations have no beats or bars. That fits phase 3, alongside the second beat tracker.
- An open question for phase 2: on 80sRock a hi-hat is written on almost every beat where the annotations have none.

**Fixed along the way (phase 1).** The first two records said "commit: None": the background shell had no `git` on its PATH. `eval_real.py` now finds Git in its standard install folders and, when it can't, says why (`9a7d6ae`). Both levels were then run again on `9a7d6ae`, and every number came out identical.

### 2026-11-04/05: phase 2, other models and a second opinion

The owner's target for this phase: charts at least 0.90 accurate.

**Where the misses are.** The detection log shows what happened to every missed stroke.
- Phantom strokes are the biggest precision loss. A hi-hat is added to a snare or kick 400 times on drum stems; the classifier is confidently wrong (half have probability above 0.76).
- Separation loses snares. On separated band mixes, 508 of 1,304 snares are missed: 171 never become a candidate, 337 get a low snare probability.
- Style matters most. Jazz recordings score far lower than the rest.
- Measured threshold sweeps show the classifier's per-drum thresholds are already close to the best for overall F.

**Models tried** (`scripts/eval_backends.py`; benchmark only, nothing ships):
- **Onsets & Frames drums, ONNX** (E-GMD, Apache-2.0). Fast (51× real time).
  - The only available conversion has two dead outputs (always exactly 0), one of them the closed hi-hat, so it has no hi-hat.
  - Alone: 0.557 on drum stems, 0.495 separated (`phase2-dev-oaf-alone`).
  - As a second opinion: +0.001 on drum stems, +0.004 separated (`phase2-dev-oaf-evidence`).
- **ADT_STR** (transformer, CC BY-SA, sample rights unclear).
  - Its decoder re-runs every token at each step: dense jazz took over 9 minutes for 103 s of audio. A cached decoder runs at about 1.5× real time.
  - Its float mask (−1e4) lets earlier positions see later tokens with these weights. So the cached, strictly causal decoding isn't token-identical: on 4 recordings it scored the same on stems and 0.03 lower on separated mixes.
  - Alone (cached decoding): 0.745 on drum stems, 0.731 separated (`phase2-dev-adt-str-alone`).
  - As a second opinion: +0.010 on drum stems, +0.009 separated (`phase2-dev-adt-str-evidence`; development split only, not taken to the held-out split).
- **DrumScript** (rule-based, alpha, Python < 3.13) was not run. Neither learned model came close to the onset classifier.
- **Not adopted.** Neither model improves on the onset classifier enough to justify a 289 MB download, an unclear licence (ADT_STR) or a conversion without a hi-hat (Onsets & Frames).

**Tried, and taken out after the held-out test: the band mix as a second opinion.** After separation, the classifier first ran on the band mix as given; a hi-hat or kick heard only in the separated drums then had to clear twice its threshold. The idea: separation leaves snare residue that sounds like a hi-hat, and turns snare and bass into phantom kicks, while a real hi-hat or kick is in the mix too. It was committed (`fa16547`), measured, and reverted:

| Separated band mixes | Without the check | With the check |
|---|---|---|
| development split (12), all 5 | 0.773 | 0.792 |
| synthetic band mixes, notation F (20 runs) | 0.9643 | 0.9705 |
| **held-out test split (11), all 5** | **0.732** | **0.723** |
| held-out: hi-hat / kick | 0.700 / 0.945 | 0.676 / 0.932 |

- **On the held-out recordings it lost.** In loud, guitar-heavy mixes the hi-hat is buried, so the band-mix pass doesn't hear it and the check deleted real hi-hats: Hendrix 0.888 → 0.696, Punk −0.052, Country1 −0.049, Gospel −0.031.
- **Where it helped:** jazz (+0.006 to +0.021) and the Beatles track (+0.044).
- **Decision:** the adoption rule fixed in the plan (overall F up, no class down more than 0.02 on the held-out split) fails, so the app keeps phase 1's behaviour.
- **Kept:** the mechanism, `classifier.Evidence` (another model's strokes move the thresholds per drum family, or add strokes), used by `scripts/eval_backends.py` and available to future models.
- **Records:** `benchmarks/results/2026-11-05_phase2-{dev,test}-*`.

**Where the app stands** (held-out test split, this PC, no change from phase 1):

| | Drum stems | Separated band mixes |
|---|---|---|
| all 11 recordings | 0.772 | 0.732 |
| rock, pop, country, gospel, metal, punk (7) | 0.883 | 0.873 |
| jazz (4) | 0.696 | 0.637 |

On the development split, the same split by style: other styles 0.913 / 0.893, jazz 0.775 / 0.594.

**On the 0.90 target.** Not reached:
- **Other styles:** about 0.87–0.91.
- **Jazz:** 0.59–0.78.
- **What would get there:** a classifier that is better on real recordings. The errors left are its own: phantom hi-hats on snares, snares lost in separation, and jazz ride and comping.
- **What is used up:** threshold tuning and second opinions were measured here and are nearly exhausted.
- **Next lever:** retraining with data aimed at those errors.

**Tests:** 827 passed, 1 skipped (`tests/test_evidence.py`, `tests/test_eval_backends.py` new).

### 2026-11-05: retraining the onset classifier (owner's request: "Retrain classifier")

- **Setup on Windows.**
  - `scripts/adt/fetch_sources.py` fetched the five Debian packages the training sources come from (530 MB, checked against packages.debian.org's SHA-256).
  - `oneshots.py` built the one-shot library: 44 kits in 86 s.
- **Data aimed at the measured errors:**
  - a "nohat" style: snares and kicks without a hi-hat;
  - `train.py build --separate`: band clips go through HTDemucs.
  - Tests in `tests/test_adt_generate.py`.
- **Built:** 4,600 clips, 535,840 labelled candidates, in about 5 hours.
- **Trained:** two networks, v5a (without separated clips) and v5 (with them).
- **Not adopted.** Neither network, nor either one averaged with the shipped pair, improves on the development split by more than 0.004 overall. All of them lose cymbals by 0.05–0.11 on drum stems. With no finalist, the held-out split was not run. The full table and what it showed are in `docs/MODELS.md` ("The retraining round").
- **What it showed:**
  - The phantom hi-hats are the classifier's reading of real snares, not a pattern learnt from synthesized grooves.
  - Training on separated clips teaches false strokes.
  - The remaining gap is synthesized against real recordings. Closing it needs real annotated recordings; those we know of are licensed non-commercial or evaluation-only, which the project excluded.
- **Kept:** the Windows training setup and the two build options, for a later round.

### 2026-11-05: phase 3, musical understanding (part 1)

**Charting again in seconds.**
- The detection log (format 2) now keeps the detector's final strokes at full precision, plus the near misses.
- `transcribe.rechart` charts a recording again from that log with other tempo, meter, downbeat or feel hints, without reading the audio. Separation and detection, the minutes of a job, aren't repeated.
- Given the same hints, it produces the same chart (`tests/test_rechart.py`).
- Ways to use it:
  - CLI: `drum-agent rechart chart.json --bpm/--time-signature/--downbeat/--feel`.
  - Studio: "Chart again" in a chart's Details panel makes a new version (`POST /api/charts/{id}/rechart`).
  - Uploads take the same hints; they are part of the job's identity (`tests/test_web_rechart.py`).
- Checked in the studio in the browser pane: a demo take charted again in 3/4 became version 2 (11 bars of 3/4 from 8 of 4/4).
- Hand edits are not carried over, and the form says so.
- Older charts (format 1 logs) don't offer it.

**Sections and fills** (`audio/structure.py`, `tests/test_structure.py`).
- A section whose bars match an earlier one's takes its letter again, numbered: A, B, A2, B2, C. The similarity is kept in the roadmap and the report.
- A busy bar (toms, a snare run) unlike its section's usual kick, snare and tom pattern gets a "Fill" cue. A busy groove played throughout gets none.
- On the library's fill chart g64, exactly its two fills are marked.
- Rendered and looked at.
- Fixed:
  - A change of cymbal into a new section was missed when the fill bar before it had none.
  - The studio's checks panel printed a stray "null".

**A second beat tracker, Beat This! (CPJKU, MIT; final0 checkpoint): measured, not adopted** (`scripts/compare_beat_trackers.py`, 2026-11-06). The comparison used synthesized charts with known tempo and meter, each drums only and with a band:
- **The ten standard 4/4 charts.**
  - Both trackers get the tempo right.
  - Our bar counts are exact or one off.
  - Beat This!'s downbeats are noisy: wrong bar counts on 13 of 20, and the 60-bar Northbound drum stem became 106 bars.
- **The library's odd-meter grooves** (g58–g63: 7/8, 5/4, 5/8, 9/8).
  - Ours can only answer 3/4 or 4/4.
  - Beat This! found 1 to 4 beats per bar; only one 7/8 groove came out plausibly (3 beats, as 2+2+3).
  - So it doesn't give odd meters either.
- **Meanwhile:** 5/4, 6/4, 7/4 and 9/8 can be given as a hint (`--time-signature`, or "Chart again" in the studio). 7/8 and 5/8 still need MIDI, a game chart or a chart spec.

**Tests:** 841 passed, 1 skipped.

### 2026-11-06: phase 4, practice, editing, explanation

**Listening** (`web/listen.py`, `player.js`, `workspace.js`, `tests/test_listen.py`).
- A time line seeks anywhere in the song. Pause now carries on from where it stopped; before, Play always went back to the selected bar. Stop goes back to the selection.
- Each section has a Loop button in the Sections panel.
- The recording is heard from an Opus copy, about eight times smaller than the WAV. In the browser its decoded length matched the WAV's and a cross-correlation found no shift (0 samples).
- Practice speed keeps the pitch. **Changed from the plan**, which said `HTMLMediaElement.preservesPitch`: a media element can't start on the audio clock, so section loops would gap and drift against the strokes. The server makes the recording at each speed instead (FFmpeg `atempo`), and it's decoded and played on that clock. In tests, strokes land within 30 ms of where the player expects them and a 440 Hz tone stays within 5 Hz at 0.5, 0.75 and 1.25.
- Checked in the browser pane on the demo take: seek while stopped and playing, pause and carry on, 75% while playing (the old speed plays on until the new one is ready, then it restarts at the same place), a one-bar loop at 75% over three passes, and back to 100%.

**Editing** (`grid.js`).
- The Adjust tool sets a note's loudness, puts it on another drum and moves it a grid step, over the barline too. It refuses a step that's taken. Every change goes through undo.
- A ghost note raised past what its mark allows stops being one, and the same for an accent lowered: otherwise the slider would change nothing you can hear.
- Cells show their loudness.
- Checked in the browser pane: 18 edits on one note, undone back to the saved version, with no engraving error.

**Practice versions** (`simplify.py`, `tests/test_simplify.py`, `tests/cases/16_practice_version.yaml`).
- Beginner and Intermediate charts are new versions labelled in the PDF and MusicXML headers and on the page. Run over all 73 grooves in the library: only notes of the source, valid, no played bar silent, velocities unchanged.
- Rendered a funk groove with ghost notes and a shuffle at both levels and looked at them: the header fits and they read as easier parts.
- They never take the transcription's place: `_save_chart` keeps the origin `simplified` through edits and restores, and `store.latest_chart` skips them.
- The rules are fixed and don't know the song: see `docs/LIMITATIONS.md`.

**Explanation** (`web/claude.py`, `tests/test_explain.py`).
- "Explain this chart" is written from the chart's facts only, and every bar it names is checked against the chart. It's kept with the version, so asking again costs nothing.
- Without the key the panel says it isn't configured and the API answers 503.
- **It has never run against the live API.** No key is set on this PC; a stand-in client answers in the tests.

**Found on the way.** After a change, the browser kept an old copy of one script beside new ones and the page stayed blank. The server sent no cache rules for scripts, and the installed app could hit the same thing after an update. The page now loads its files from a path that changes with each build, and they're checked on each load (`tests/test_web.py`).

**Not run:** the Playwright browser tests (`tests/test_web_e2e.py`). This PC has no Node. One of them changed (`beat.e2e.js` now presses Stop, not Pause, before it expects to start from bar 1). In their place, the beat journey (create, play with the scheduled strokes compared with the chart, stop, tempo, undo) and the phone width were checked by hand in the browser pane.

**Tests:** 948 passed, 1 skipped (fast suite).

### 2026-11-06: phase 5, hardening

**Request guard** (`web/guard.py`, `tests/test_guard.py`).
- The personal app answers only to its own names. A body is refused by its declared size, or cut off while it streams once past the limit. Writes need the `X-Drum-Agent` header. A shared server has token buckets per visitor and per address, and sends HSTS over HTTPS.
- Tried against the running server with curl: a wrong Host, a write without the header, a form post from another origin, a CORS preflight and an oversized declared body are all refused.

**Uploads.** The request now checks only what needs no decoder; the job decodes. A file only decoding can judge fails the job, and neither it nor its source is kept. In the browser pane: a silent WAV uploaded through the real form failed with its reason, the form came back without "Try again", and a good file went through.

**Data.** A copy has its own source row, so it keeps the recording when the original is deleted; older copies get theirs at start-up. A `personal` asset is refused on a shared server. The live studio no longer caches anything between runs. A chart whose recording is gone no longer offers it. MusicBrainz is asked at most once a second.

**Supply chain** (`tests/test_supply_chain.py`). LilyPond, FFmpeg and cloudflared are exact files with SHA-256s; torch, torchaudio and demucs are pinned. The pinned Windows LilyPond and FFmpeg were fetched through `fetch_tools.py` and matched, and that FFmpeg has libopus and `atempo`. The Linux and Mac LilyPond hashes were computed from their downloads here. The cloudflared hash comes from GitHub's release data and hasn't been checked against a download.

**CI** (`.github/workflows/tests.yml`). Fast tests on Linux and Windows, browser journeys on Linux. **It has never run:** nothing has been pushed yet. The Docker and Windows builds with the pinned versions haven't run either.

**Reviews.**
- Security review of the branch: nothing at its confidence bar. Ownership and XSS conclusions come from reading the code; LilyPond escaping was tested with 36 hostile cases on the real binary. It noted LilyPond 2.26 has no safe mode, so `ly_string` is the only barrier (`docs/WEB_APP.md`).
- Code review: ten findings, all fixed, with tests for the server-side ones. The main ones: a re-upload after the audio was lost never decoded; a job queued on a refused upload crashed; typed edits used up the Claude limit; the song's source panel could point at a practice version.

**Tests:** 1,027 passed, 1 skipped (fast suite).

### 2026-11-07: phase 6, final verification

**On this PC.**
- Fast suite: 1,027 passed, 1 skipped.
- Slow suite: 131 passed, 4 skipped (the browser journeys, no Node here), 3 failed. All 3 were LilyPond timeouts caused by the laptop sleeping from 00:50 to 17:51 during the run (Windows' power log). Run again, the three charts pass in 8 s together.
- `acceptance_run.py` on a real annotated recording (MDB Britpop, shared server, drum separation on): passed. Finished chart F 0.904 for that one track (P 0.876, R 0.934), mean timing error 9.1 ms. It's a development-split recording, not a measure of the whole.

**The exports of that chart, version 2.** Chart, MIDI and MusicXML each hold 273 strokes. The MusicXML is valid against the 4.0 schema and opens in Verovio. The PDF page was read by eye: it's labelled an unverified automatic transcription, and all 17 bars carry a review flag.

**In CI, pull request #2, the first run ever of these workflows.** The first run (commit `7ae798d`) had one failure, on Windows: a test helper grouped notes by rounded height and split a system when fonts moved the page. The test was fixed, not the app.

The final run, all on commit `016b128` (Tests run 42389149183, server image run 42389149234, Windows app run 42389149184):
- Fast tests: 1,028 passed on Linux, 1,028 passed on Windows.
- Browser journeys: 4 passed, in Chromium through Playwright. These ran for the first time on the code of phases 3 to 5, including the new steps: seek, 75% with the pitch kept, section loop, Adjust, practice version, silent upload.
- Server image with the pinned versions: built (2.53 GB). A visitor's whole workflow passed on the real recording with separation, F 0.899 there (0.896 in the first run, 0.904 on this PC). This one track's score moves by up to 0.008 between runs; why hasn't been looked into.
- Windows app with the pinned tools: built. The built app passed `packaging/smoke_test.py`: tools ready, a beat, an upload separated and transcribed, a song found in a music folder and charted, a real catalog search.
- Installer: `DrumAgent-Setup.exe` built (353 MB), installed silently, and the installed app started with its example chart in place after 15 s. Its window's screenshot was looked at by eye: the studio, "Engine ready", the example chart listed.

**Not done.**
- Step 2 of the plan's journey, a YouTube result playing in the official player: no YouTube key is set.
- "Explain this chart" against the live API: no Anthropic key is set.
- Spotify search on this line: no Spotify keys are set.
- The owner's 0.90 target: not reached (held-out split, finished charts: 0.772 on drum stems, 0.732 on separated band mixes).
- The slow tests other than the browser journeys ran only on this PC. CI runs the fast tests and the browser journeys.
- Publishing: the new installer and server image go out when pull request #2 is merged. Until then the download page has the 2026-10-30 installer.

