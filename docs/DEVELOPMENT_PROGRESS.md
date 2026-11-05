# Development progress

The living record of what is done, with its evidence. Statuses:
- **Complete and verified**: built, and a named test or recorded run shows it working.
- **Implemented, not fully verified**: built, but part of it has never run for real (usually missing credentials).
- **Partially implemented**: some of the requirement is built.
- **Not implemented**.
- **Blocked**: waiting on something outside the code.

## Requirement matrix

Product requirements from the 2026-11-03 brief, section 21. Last updated 2026-11-04.

| Requirement | Expected | Status | Evidence / what is missing |
|---|---|---|---|
| Existing project | preserved and improved | **In progress** | Work continues on branch `claude/transcription-platform`, made from `a9b52095`. Local recovery tag `pre-platform-v2`. Nothing was rewritten |
| Historical work | recovered wherever accessible | **Complete and verified** | `docs/PROJECT_RECOVERY_REPORT.md`: 14 cloud sessions, 1 claude.ai chat, 5 artifacts, the repository and its CI. The inaccessible material is listed there |
| Skills and integrations | inventoried, relevant ones used | **Complete** (inventory) | `docs/AVAILABLE_TOOLS_AND_SKILLS.md` |
| YouTube | song search and authorized playback | **Implemented, not fully verified** | Data API `search.list` / `videos.list` + `youtube-nocookie` embed (`web/providers.py`, `static/js/song.js`). Tested with recorded responses, never against the live API: needs `YOUTUBE_API_KEY` |
| Audio uploads | functional and validated | **Complete and verified** | `audio/prepare.py`, `web/sources.py`; `tests/test_web.py`; CI acceptance run on a real recording (run 40905703452) |
| Audio processing | real FFmpeg-based processing | **Complete and verified** | ffmpeg/ffprobe decode and validation (`audio/prepare.py`); FFmpeg ships with the app |
| Drum separation | actual source separation | **Complete and verified** | HTDemucs (`audio/separate.py`); MDB band mixes 0.591 → 0.733 F with it. Runs on this PC from the local weights (`doctor`, 2026-11-04). Since phase 1, a failure falls back to the band mix with a note instead of ending the job |
| Transcription | actual model inference | **Complete and verified** | onset classifier (`audio/classifier.py`), measured on the MDB Drums held-out split (re-measured on this PC in phase 2: drum stems 0.772, separated band mixes 0.732). Phase 2 measured two other models and a band-mix check; none was adopted (`scripts/eval_backends.py`, `docs/MODELS.md`) |
| Instrument detection | multiple individual drum classes | **Partially implemented** | 11 classes from audio. Never from audio: china, splash, crash2, rimshot, cowbell, half-open hi-hat. Cymbals 0.14 and toms 0.43 F on separated band mixes |
| Musical analysis | tempo, rhythm and structure | **Partially implemented** | Tempo, swing, tuplets, 3/4 and 4/4, 12/8 sections, short bars. Since phase 3: repeated sections recognized (A, B, A2), fills marked on bars, tempo/meter/downbeat/feel hints in the studio (upload, and "Chart again" in seconds from the stored strokes; `drum-agent rechart`). Missing: odd meters from audio (a second beat tracker, Beat This!, not yet tried) |
| Arrangement | complete-song representation | **Complete and verified** | Every bar of the recording is charted, with sections, repeats (A2) and fills marked: 60-bar synthetic song at notation F 0.978, 8.5-minute stress test; `tests/test_structure.py` (constructed bars and the library's fill chart g64; not measured on real recordings, whose annotations have no sections) |
| Chart generation | genuine drum notation | **Complete and verified** | LilyPond 2.26 engraving; MusicXML 4.0 (XSD); MIDI; three-way read-back on every export; 113-chart library |
| Playback | synchronized with the chart | **Partially implemented** | Recording plays on the chart's bar clock, with current-bar highlight, metronome, count-in, loop and speed (`tests/e2e/song.e2e.js`). Missing: timestamp seek, pitch-preserving speed, whole-section loop |
| Editing | user can correct detected hits | **Partially implemented** | Grid editor (add/remove, accent, ghost, flam, undo/redo, versions) and CLI `edit`. Since phase 1, every note keeps the detector strokes behind it and an "edited" mark, and every detection is kept beside the chart (`tests/test_detections.py`). Missing: velocity, change instrument, move |
| Exports | verified output formats | **Complete and verified** | PDF, PNG, MusicXML, MIDI and JSON; `verify.py`; `tests/test_exports.py`, `tests/test_fuzz_exports.py` |
| Testing | actual tests and documented results | **In progress** | 936 passed in CI (2026-10-29); fast suite on Windows 827 passed, 1 skipped (2026-11-05, phase 2); real-recording benchmark at detector and finished-chart level, each run kept in `benchmarks/results/`, other models included (`scripts/eval_backends.py`). `docs/TESTING_AND_BENCHMARKS.md` |
| Security | upload and API protection | **Partially implemented** | Upload validation, per-browser owner scoping, CSP and security headers, rights gate. Missing: rate limits, CSRF guard, streaming size cap, Host allowlist, decode outside the request |

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

**Not done yet:** Beat This! as a second beat tracker, which would give odd meters from audio.

**Tests:** 841 passed, 1 skipped.
