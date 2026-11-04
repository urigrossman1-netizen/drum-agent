# The audio transcription pipeline

How a recording becomes a drum score, stage by stage: what each stage does, its sample rate
and channels, where the code is, and what it keeps or throws away. It describes the code
as it is. Changes being made in the current round are tracked in
`docs/DEVELOPMENT_PROGRESS.md` and folded in here when they land.

Companion documents:
- `docs/ARCHITECTURE.md` is the whole system;
- `docs/MODELS.md` covers the onset classifier and the separation model;
- `docs/LIMITATIONS.md` has measured accuracy.

## Entry points

| Path | Entry | Notes |
|---|---|---|
| CLI | `cli.py` `cmd_transcribe` → `audio/transcribe.py:528 transcribe_file` → `load_audio` (`:39`) → `transcribe_audio` (`:76`) → `pipeline.export_all` | hints: `--bpm`, `--time-signature`, `--downbeat`, `--feel`, `--sections`, `--drums-only`, `--separate auto/on/off`, `--detector auto/classifier/nmf`, `--sensitivity`, `--start/--end` |
| Web studio and desktop app | upload → `web/sources.py prepare()` (validation, ffmpeg decode) → job `web/jobs.py _transcribe` → `load_audio` → `transcribe_audio(y, TranscribeOptions())` | the job always uses the default options: no hints yet |

## Stages

| # | Stage | Code | Signal | What it does |
|---|---|---|---|---|
| 0 | Validate and decode (web) | `audio/prepare.py`, `web/sources.py` | any → 44.1 kHz, 2 ch, 16-bit WAV | extension whitelist, magic bytes, ffprobe, size and duration limits (200 MB, 5 s to 20 min by default), silence (−60 dBFS) and truncation checks; stored under its SHA-256 |
| 1 | Load | `transcribe.py:39 load_audio` | → 44.1 kHz **mono** float | librosa (ffmpeg fallback). Stereo is averaged to mono here |
| 2 | Separate | `audio/separate.py:60 separate_drums`, chosen by `transcribe.py:190 use_separation` | mono duplicated to 2 ch at the model rate → drum stem → mono 44.1 kHz | HTDemucs (`htdemucs`, weights `955717e8`), CPU, `split=True, overlap=0.25`. Runs when torch and demucs are installed and the input is not marked drums-only. Weights load from `$TORCH_HOME/hub/checkpoints` when shipped (`shipped()`, `:31`). **The band mix is not used after this point** |
| 3 | Front end | `audio/detect.py:258 front_end` | 44.1 kHz; STFT 2048 / hop 256 (5.8 ms); 96 mel bands, 30 Hz to 17 kHz | peak-normalise, 0.25 s pad, HPSS for band mixes, superflux onset envelope, candidate onsets (high recall: 86–100% of every class on real recordings). STFT/HPSS are processed in 30 s chunks |
| 4 | Classify | `detect.py:284 detect` → `audio/classifier.py:261 classify_hits` (default) or `detect.py:379 _detect_nmf` (`--detector nmf`) | 1,300 features per candidate | numpy MLP ensemble, 11 classes (kick, snare, cross-stick, closed/open/pedal hi-hat, ride, ride bell, crash, tom, other), per-class thresholds scaled by `--sensitivity`. Rules: one hi-hat state per instant, at most two hand strokes, pedal under a stick stroke dropped. Toms named by NMF evidence or by pitch clusters (`name_toms`, `:220`) |
| 5 | Finish | `detect.py:300 _finish` | strokes | merge flams, drop flam-caused crashes, smooth cymbals, ghost/accent from each drum's typical strength (snare only, at least 8 strokes) |
| 6 | Grid | `audio/beats.py:313 estimate_grid` | stroke-weighted envelope at frame rate | tempo candidates (librosa tempo prior × {1, ¾, 4/3, ⅔, 1.5, ½, 2}), each tracked by librosa's DP beat tracker and scored by grid fit, backbeat and a tempo prior; meter 3/4 vs 4/4 by repetition; downbeat from kick/crash/backbeat placement; `--bpm`/`--time-signature`/`--downbeat` override |
| 7 | Quantize | `quantize.py:144 quantize` | onsets → bar positions (exact `Fraction`s) | per beat, the subdivision (1, 2, 3, 4, 6, 8, 12) with the lowest timing-error + complexity cost; swing feel detection; tempo map; uncertain-bar flags. Merges duplicates in a slot and resolves hi-hat conflicts |
| 8 | Measures and refinements | `transcribe.py:76` onward | bars | 12/8 section re-metering, short bars from downbeat crashes, roll notation (8+ consecutive 32nds), empty-bar trimming, kick-density (bass bleed) check |
| 9 | Sections | `audio/structure.py:41 find_sections`, `:69 label_sections` | bars | a new section at meter/tempo changes, or a cymbal or kick/snare pattern change with a downbeat crash or a preceding fill, at least 4 bars apart; labelled A, B, C… |
| 10 | Flags and analysis | `transcribe.py:155-186`, `playability.py` | score | status `unverified_auto`; bars flagged "(?)" for low confidence, near misses, unplayable combinations, structural decisions; `analysis` (detector, separation, tempo/meter confidence, counts) |
| 11 | Engrave and verify | `pipeline.export_all` | score → `.ly`, PDF, PNG, MusicXML, MIDI | LilyPond 2.26; MusicXML 4.0 checked against its XSD; every output read back and compared with the score |

## What an event keeps (`drum_agent/model.py`)

Each stroke is a `Hit` with these fields:
- `pos` (an exact `Fraction` of a whole note from the bar start) and `inst`;
- `velocity` (1–127; 35–110 from audio);
- `accent`, `ghost`, `flam`, `drag`, `roll`, `choke`, `sticking`;
- `confidence` (0–1, heuristic);
- `time`, the performed onset in seconds (5.8 ms frame resolution);
- `offset_ms`, performed minus quantized.

Each `Measure` keeps its `start_time` (the performed bar start). That is what lets the studio
play the recording in step with the chart.

**Not kept today:**
- class probabilities;
- strokes merged into a slot, dropped by the hi-hat rule, outside the grid, inside a notated roll, or a flam's grace stroke;
- which detector produced each stroke (recorded per score only);
- whether a person edited a stroke.

## Seams for other transcription models

- **Seam A.** In `detect.py:289` (the detector switch), a function `(FrontEnd, DetectOptions) → (list[DrumHit], extra)` returns through `_finish`. It reuses the front end, onset envelope and post-processing. A `DrumHit` carries:
  - `time` (seconds; subtract the 0.25 s pad);
  - `inst`;
  - `strength` (1.0 = a typical stroke; beat tracking uses it);
  - `velocity`;
  - `confidence`.
- **Seam B.** Replace the `detect()` call in `transcribe_audio` with anything that returns a `Detection`. Two constraints:
  - `onset_env` must be at hop 256 / 44.1 kHz;
  - `strength` must be supplied.
- **Full mix.** A model that wants the band mix, or stereo, needs `transcribe_audio` to keep the pre-separation signal, which it currently overwrites.

## Measured accuracy (summary)

From `docs/LIMITATIONS.md`: MDB Drums, held-out test split, onset F at 50 ms, detector level.

| Input | Overall | Kick | Snare | Hi-hat | Toms | Cymbals |
|---|---|---|---|---|---|---|
| Band mix, drums separated | 0.733 | 0.945 | 0.823 | 0.703 | 0.427 | 0.144 |
| Drum stem | 0.772 | 0.963 | 0.866 | 0.723 | 0.495 | 0.270 |

Synthetic charts with exact answers reach notation F 0.963–0.969.
