# The web app

Type a song, pick the recording, give the app audio you have the right to transcribe,
and get a complete, playable drum chart you can read on screen, print, or download as
PDF, MusicXML or MIDI.

```bash
pip install -e '.[web]'                       # FastAPI, uvicorn, httpx, the Anthropic SDK
python -m drum_agent doctor                   # LilyPond, ffmpeg, the classifier weights
python -m drum_agent serve --seed-examples    # http://127.0.0.1:8000
```

`--seed-examples` stores the Northbound example song (an original composition) as an
existing chart, so the catalog isn't empty. A song list (for instance the 100-song
workbook exported as CSV with `title` and `artist` columns) is added with
`python -m drum_agent catalog import songs.csv`: each song is stored as `NEEDS_SOURCE`.
No chart is generated and nothing is analysed until an authorized recording is supplied.

Configuration is in `.env.example`. Every key stays on the server.

## The flow

1. **Search** (`GET /api/search?q=Title - Artist`). The chart catalog is searched
   first. Then MusicBrainz, iTunes and Deezer are searched (no keys needed), plus
   Spotify and YouTube when their keys are set. Results show title, artist, album,
   year, duration, ISRC, the providers that know the recording, and its version.
   Versions are studio, live, remaster, demo, acoustic, remix, instrumental or cover,
   read from the title and album. Each recording gets a stable id: from its ISRC, else
   from the provider's track id, else from the title, artist and version. Every
   provider reports its state: searched, unavailable (with the reason) or not
   configured. A failed provider is never shown as an empty result. If nothing is
   found, the song can be added by hand.
2. **Source resolution** (`drum_agent/web/sources.py`). The app checks, in order:
   - `EXISTING_CHART`: a chart is already stored.
   - `AUTHORIZED_ASSET`: the operator put the recording in `DRUM_AGENT_ASSET_DIR`
     with a rights basis in `assets.json`.
   - `USER_UPLOAD`: the user uploaded the recording.
   - `LICENSED_SOURCE`: a licensed audio provider. None is configured in this build,
     and the app says so.
   - `NEEDS_SOURCE`: the recording is identified, but no authorized audio is
     available. The page offers an upload.

   Spotify and YouTube are metadata only. The server never downloads, caches or
   transcribes their audio or previews.
3. **Upload** (`POST /api/songs/{id}/upload`). An upload is a file plus a rights
   basis: own, permission, licensed, public_domain or original. The rights gate
   (`drum_agent/rights.py`) runs before anything is decoded.
   `drum_agent/audio/prepare.py` then checks the extension, the size, the file
   signature and the ffprobe stream properties. It decodes the audio to the internal
   format (44.1 kHz, 2 channels, 16-bit WAV) with the timeline untouched. It refuses
   files that are truncated (a decode shorter than the header announces), too short,
   too long or silent, each with a reason the page shows. Each model resamples from
   the internal file to what it needs; the classifier uses 44.1 kHz mono.
   The same file uploaded again is the same source, and gets the same job.
4. **Transcription job** (`drum_agent/web/jobs.py`). The job runs on a worker thread
   and its state is stored in SQLite. Its stages are prepare, detect, beats,
   measures, sections, validate, render, view and save. The transcriber reports the
   first five itself as it reaches them, so the stage shown is the work being done.
   - Jobs are idempotent per recording (the audio's SHA-256) and engine version.
   - Cancellation takes effect at the next stage boundary.
   - A failed or cancelled job can be retried.
   - A job interrupted by a restart is queued again once, then reported as failed.
5. **Validation** (`drum_agent/validate.py`). These checks run on the score itself:
   - every bar holds exactly its time signature (only bar 1 may be a pickup);
   - every stroke lies inside its bar, on the 32nd-note or triplet grid;
   - no duplicate strokes, and every instrument is in the kit;
   - tempo between 20 and 400 BPM, and sections in order;
   - bar start times increase, and each bar lasts what its tempo says;
   - every stroke lies inside the notated timeline, which runs from the recording's
     first stroke to its last;
   - nearly every detected stroke is notated.

   Separately, the PDF (through LilyPond's MIDI), the MusicXML and the MIDI are
   checked against the score (`drum_agent/verify.py`).
6. **Status.** A chart is `COMPLETE` only when every check passes, the exports
   match, and no bar is flagged for review. Otherwise it is `NEEDS_CORRECTION`. A
   song's status is one of `NOT_STARTED`, `ANALYZING`, `TRANSCRIBING`, `VERIFYING`,
   `NEEDS_SOURCE`, `NEEDS_CORRECTION` or `COMPLETE`, derived from its jobs and charts.
   The printed chart still says "Automatic transcription, unverified": `COMPLETE`
   means complete and consistent. It does not mean a person checked every note.
7. **Chart view.** The page shows the engraved pages as SVG, drawn by LilyPond from
   the same `.ly` file as the PDF, with each barline tagged with its bar number. From
   the tags, `drum_agent/web/view.py` builds a box for every engraved bar. The page
   then offers:
   - jumping to a section or a bar number;
   - zoom;
   - stepping through the bars flagged for review;
   - following playback of the source recording, using the bars' performed start
     times from the score;
   - printing (print CSS lays the pages out one per sheet, like the PDF);
   - downloading the PDF, MusicXML or MIDI.
8. **Corrections make versions.** Confirming a flagged bar after listening, or
   renaming sections, creates a new chart version (v2, v3 ...) with its own
   validation and files. Earlier versions are kept.

## Claude

`POST /api/charts/{id}/suggest-sections` asks Claude to name the chart's sections
(Intro, Verse, Chorus ...). The transcriber only letters them A, B, C.

- **What is sent.** Claude gets a compact factual description of each section: its
  first bar and length, density, main cymbal, crashes, tom strokes, and which sections
  share a pattern. It also gets the title and artist. No audio, file paths or
  configuration are sent.
- **What comes back.** The answer is structured output (a JSON schema). It is then
  validated: one name per existing section, from a fixed vocabulary, at exactly the
  existing boundaries. Claude cannot add or move a boundary, or change a note or a
  tempo.
- **Applying it.** A suggestion changes nothing until the user applies it, which
  makes a new version.
- **Configuration.**
  - `ANTHROPIC_API_KEY` and `DRUM_AGENT_ANTHROPIC_MODEL` (a current model id from
    Anthropic's models overview). Without them the button is disabled and the API
    answers 503 `not_configured`.
  - The base URL is the public API unless `DRUM_AGENT_ANTHROPIC_BASE_URL` is set.
  - The timeout is 45 s with one retry.
- **Errors.** Authentication, permission, unknown model, rate limit, timeout,
  connection, refusal, truncation and an answer that doesn't fit the chart are each
  reported as such.

## Endpoints

See the docstring of `drum_agent/web/app.py`. `GET /api/health` reports:

- LilyPond, ffmpeg, ffprobe, the classifier weights and the database;
- each provider's state, and whether Claude is configured (never the key).

It answers 503 when a required dependency is missing.

Files are served only from a fixed list: `chart.pdf`, `chart.musicxml`, `chart.mid`,
`chart.json` and the `page-N.svg` pages. All ids are checked against their format
before any path is built. Uploaded file names are display names only: stored audio
is named by its SHA-256.

## Storage

`DRUM_AGENT_DATA_DIR` (default `~/.drum_agent/web`) holds:

- `drum_agent.sqlite3`, with the tables `songs`, `sources`, `jobs` and `charts`.
  Their columns are in `drum_agent/web/store.py`. Chart versions are immutable.
- `sources/<sha256>.wav`, the normalized audio, served back only to the chart's
  playback.
- `charts/<id>/`, which holds `chart.json` (the score), the PDF, MusicXML, MIDI,
  LilyPond source, reports, `validation.json`, `view.json` and the SVG pages.

The app has no user accounts: run it for yourself or behind your own authentication.
It doesn't redistribute uploaded audio or charts. Each file is served only to whoever
can reach the server.

## Transcription engine

The engine is the project's own:

- candidate onsets from the spectrogram;
- a trained onset classifier (`drum_agent/data/onset_classifier.npz`,
  [MODELS.md](MODELS.md));
- beat, meter and downbeat tracking;
- exact quantization into bars.

Its measured accuracy is in [LIMITATIONS.md](LIMITATIONS.md).

Demucs (drum-stem separation before detection) and Omnizart (an alternative drum
transcription model) were considered but not evaluated here. Both install from PyPI,
but their model checkpoints are downloaded from hosts this build environment can't
reach. They can't be measured, so neither is wired in. To evaluate one, run
`scripts/eval_real.py --split train` with and without it, per the rules in CLAUDE.md:
no regression on held-out kits or band mixes, and the test split run once.
