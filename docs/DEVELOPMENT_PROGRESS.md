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
| Drum separation | actual source separation | **Complete and verified** | HTDemucs (`audio/separate.py`); MDB band mixes 0.591 → 0.733 F with it. Runs on this PC from the local weights (`doctor`, 2026-11-04) |
| Transcription | actual model inference | **Complete and verified** | onset classifier (`audio/classifier.py`), measured on the MDB Drums held-out split. More models and a comparison are phase 2 |
| Instrument detection | multiple individual drum classes | **Partially implemented** | 11 classes from audio. Never from audio: china, splash, crash2, rimshot, cowbell, half-open hi-hat. Cymbals 0.14 and toms 0.43 F on separated band mixes |
| Musical analysis | tempo, rhythm and structure | **Partially implemented** | Tempo, swing, tuplets, 3/4 and 4/4, 12/8 sections, short bars. Missing: odd meters from audio, repeated-section recognition, fills marked on bars, web hints |
| Arrangement | complete-song representation | **Partially implemented** | Every bar of the recording is charted, with sections and flags: 60-bar synthetic song at notation F 0.978, 8.5-minute stress test. Repeats aren't labelled as repeats |
| Chart generation | genuine drum notation | **Complete and verified** | LilyPond 2.26 engraving; MusicXML 4.0 (XSD); MIDI; three-way read-back on every export; 113-chart library |
| Playback | synchronized with the chart | **Partially implemented** | Recording plays on the chart's bar clock, with current-bar highlight, metronome, count-in, loop and speed (`tests/e2e/song.e2e.js`). Missing: timestamp seek, pitch-preserving speed, whole-section loop |
| Editing | user can correct detected hits | **Partially implemented** | Grid editor (add/remove, accent, ghost, flam, undo/redo, versions) and CLI `edit`. Missing: velocity, change instrument, move, a per-hit "edited" flag, and keeping the raw predictions |
| Exports | verified output formats | **Complete and verified** | PDF, PNG, MusicXML, MIDI and JSON; `verify.py`; `tests/test_exports.py`, `tests/test_fuzz_exports.py` |
| Testing | actual tests and documented results | **In progress** | 936 passed in CI (2026-10-29); fast suite on Windows 807 passed, 1 skipped (2026-11-04); benchmarks per backend come in phase 2. `docs/TESTING_AND_BENCHMARKS.md` |
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
