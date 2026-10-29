# Implementation audit (2026-10-29)

What exists, what works (with the evidence), what doesn't and why, and the order of the
work that followed. Written before the changes of the same day; section 8 records how
each item ended.

## 1. Architecture and capabilities

One Python package, `drum_agent`, used three ways: a CLI (`python -m drum_agent ...`), a
FastAPI web studio (`serve`, `drum_agent/web/`), and a desktop app for Windows
(`drum_agent/desktop.py`, PyInstaller + Inno Setup, `packaging/`). 95 commits on
`claude/peaceful-noether-qz2xmc`; the repository's default branch
(`claude/eager-keller-91y28i`) holds an earlier state; one release (`app-windows-9`).

| Layer | Where | What it does |
|---|---|---|
| Score model (single source of truth) | `model.py`, `kit.py` | bars, exact `Fraction` positions, instruments, per-bar performed start times |
| Audio pipeline | `audio/prepare.py` -> `separate.py` -> `detect.py` + `classifier.py` -> `beats.py` -> `quantize.py` -> `structure.py`, `transcribe.py` | decode (ffmpeg/soundfile, 44.1 kHz mono, limits), HTDemucs drum separation, onset candidates, neural classifier (11 classes), beats/downbeats/meter/tempo changes, quantization into bars, sections, uncertain-bar flags, playability check |
| Engraving and exports | `export/` (LilyPond, MusicXML, MIDI), `verify.py` | PDF/PNG via LilyPond only, MusicXML validated against its XSD, MIDI; a verification report |
| Song lookup | `song/lookup.py`, `song/local.py`, `song/fetch.py`, `song/run.py` | MusicBrainz/iTunes/Deezer metadata; the user's music folders; direct audio URLs with a rights basis; yt-dlp video search and download |
| Web backend | `web/app.py`, `studio.py`, `jobs.py`, `store.py`, `sources.py`, `providers.py`, `online.py`, `claude.py` | REST API; SQLite store; one background job thread, persisted and resumed after restarts; source resolution; provider adapters; optional Claude section naming and beat-prompt reading |
| Web frontend | `web/static/` (no build step) | search, song page, job progress, workspace (engraved pages, editable grid, Web Audio player, versions), My Charts, Settings, beat generator |
| Desktop | `desktop.py`, `packaging/` | personal mode on 127.0.0.1, pywebview window, shipped LilyPond/FFmpeg/HTDemucs |

## 2. Verified working (evidence)

- **Tests**: 792 fast tests pass (`pytest -m "not slow"`, 94 s, today); the full suite's
  baseline is in section 8.
- **Transcription on real recordings** (MDB Drums, 23 real multitrack recordings with
  reference annotations, CC BY-NC-SA, `scripts/eval_real.py`): held-out test split, onset F
  at 50 ms, all five classes, drum stems 0.772, band mixes 0.591, band mixes with the drums
  separated first 0.733 (GitHub run 40824145970). Per-class and per-recording numbers:
  `docs/MODELS.md`, `docs/LIMITATIONS.md`.
- **Synthetic charts with exact answers** (`scripts/eval_notation.py`, 40 runs): notation F
  0.963 as given, 0.969 with separation (run 40826408065); right bar counts, tempo and meter.
- **Packaged Windows app**: built, installed and driven by `packaging/smoke_test.py` on
  GitHub's Windows runners (runs 40827343924, 40828728039, 40830128911): every tool ready,
  a beat engraved, an uploaded take separated, transcribed and engraved, the window opens
  the studio (screenshot), first start 11 s.
- **Provider adapters**: Spotify (client-credentials search) and the YouTube Data API
  (`search.list` + `videos.list`) are implemented against the documented endpoints and
  covered by tests with recorded responses; each reports ok / not configured / the error.
- **No invented music**: Claude names sections and reads beat descriptions only; it cannot
  add, move or change a note (`web/claude.py`, validated output). Chart events come from
  detections, documented rule-based inference (e.g. playability fixes, flagged) or user
  edits; every chart version records its origin.

## 3. Broken, incomplete or disconnected

1. **The YouTube audio path breaks the current rules.** `web/online.py`, the `find` job,
   `song/fetch.py` (`search_videos`, `download_with_ytdlp`) and the desktop installer use
   yt-dlp: its search reads YouTube's undocumented web endpoints and its download extracts
   the audio, which YouTube's terms don't permit. The project's rules now forbid both
   (official interfaces only; no scraping or unauthorized extraction).
2. **No separation between visitors on a shared server.** There is no authentication; the
   list endpoints return every project, and a song's id is derived from its title and
   artist (`store.song_id_for`), so two visitors charting the same song share one project,
   its uploads and its charts. Harmless on one person's computer; a privacy and rights
   problem on any public deployment.
3. **No listening along with the recording.** The workspace player synthesizes the chart's
   strokes (`static/js/player.js`); the uploaded recording is never played back, although
   every bar of an audio chart stores its performed start time (`Measure.start_time`), so
   the alignment exists.
4. **No production deployment.** The "website" was `live-studio.yml`: a GitHub-hosted runner
   exposed through a Cloudflare quick tunnel for at most 5.5 hours; no container image, no
   hosting configuration. Credentials in this environment: Vercel (connector) may list
   projects but is refused project and sandbox creation (403); the Google Cloud, AWS and
   `gh` tokens present here don't authenticate.
5. **YouTube and Spotify keys are not configured** anywhere (no environment variable, no
   secret referenced by a workflow), so those searches report "not configured" and have
   never run against the real services.
6. **Real catalog search can't be exercised from this development container**: its proxy
   refuses musicbrainz.org, itunes.apple.com and api.deezer.com (403). It works from
   GitHub's runners; the tests use recorded responses.
7. **Accuracy reporting** gives F only; precision, recall and timing error are not printed.

## 4. Root causes

- (1) The feature was built on the earlier instruction to chart a typed song automatically,
  with yt-dlp as the audio source on the user's own computer; the rule changed.
- (2) The studio was designed as a single-user tool (one person, own computer), then the
  same server was published through the live-studio tunnel without per-visitor scoping.
- (3) The player was built for practice (a clean drum sound, speed, loop), not for checking
  a transcription against its recording.
- (4)-(5) Account-level resources: no hosting account or API keys were ever provided to
  this environment.

## 5. Reused, not rebuilt

The whole audio pipeline and its evaluation scripts; the score model, engraving and
exports; the store, job runner, source resolution (its cases stay, minus the video ones);
the Spotify and YouTube Data API adapters; the music-folder search (`song/local.py`, until
now CLI-only); the workspace, grid editor, versions and player; the desktop app and its CI
build; the Windows release workflow.

## 6. Blockers and remedies

| Blocker | Remedy |
|---|---|
| No hosting account usable from here | the owner provides one (a token stored as a GitHub Actions secret); the container image and its CI test are prepared so deployment is one step |
| No YouTube Data API key / Spotify client credentials | the owner creates them (Google Cloud console, Spotify developer dashboard) and stores them as deployment secrets; the adapters are ready |
| No licensed audio provider | none exists in the project; audio comes from the user's own files (upload, or their music folders in the desktop app) |

## 7. Sequence

1. Remove the yt-dlp path; YouTube through the official Data API only (discovery, links).
2. Desktop: find the typed song in the user's own music folders (the automatic path that
   remains legitimate).
3. Per-visitor workspaces on shared servers.
4. Listen along with the original recording, aligned through the bar timeline.
5. Accuracy: precision, recall and timing error; the full workflow on a real recording.
6. Container image, CI build and smoke test against the real catalog services; the
   temporary live deployment; permanent hosting once an account exists.
7. Rebuild the Windows app; full regression; report.

## 8. Outcome

(Filled in as the work lands.)
