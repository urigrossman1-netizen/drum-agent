# Drum Agent

Drum transcription and drum-chart engraving. For any request to make, transcribe
or fix a drum chart, use the `drum-chart` skill (`.claude/skills/drum-chart/`).

## Commands
- Run: `python -m drum_agent <render|midi|gamechart|song|transcribe|analyze|edit|synth|evaluate|verify|doctor>`
- Studio (web app): `python -m drum_agent serve --seed-examples` (needs `pip install -e '.[web]'`; docs/WEB_APP.md).
  Personal app, where a typed song is found in the user's music folders and charted: `serve --personal`, or the
  desktop app `python -m drum_agent app` (`drum_agent/desktop.py`; Windows installer: `packaging/`).
  Beat generator: `drum_agent/generate/` (tests/test_generate.py). Browser end-to-end tests of both journeys:
  `python -m pytest -q tests/test_web_e2e.py` (slow; Playwright via node, needs pdftotext)
- Chart library: `library/rudiments` (40 PAS rudiments) and `library/grooves` (73 grooves and fills);
  `tests/test_library.py` holds them to the house rules
- Fast tests: `python -m pytest -q -m "not slow"` (about 1 min); all: `python -m pytest -q`
- Transcription accuracy: `python scripts/eval_notation.py --jobs 4` and `python scripts/eval_detection.py`
  (synthetic, exact answers); real recordings: `python scripts/eval_real.py --split train` (MDB Drums,
  downloaded to a local cache; the `test` split is held out, run it once per model version)

## Rules for changing the code
- `drum_agent/model.py` (the IR) is the single source of truth. Renderers read it; they
  never invent rhythm. Positions are exact `Fraction`s of a whole note from the bar start.
- Instrument positions, noteheads and MIDI notes live only in `drum_agent/kit.py`
  and must match `docs/NOTATION_SPEC.md` (`tests/test_kit.py` enforces it).
- Notation changes: add or extend a chart in `tests/cases/` and look at the rendered
  PNG before and after; a passing test alone doesn't prove the engraving reads well.
- Detection changes: measure with both eval scripts before and after; don't accept a
  change that regresses held-out kits (jazz, brush) or band mixes. No chart-specific constants.
  The onset classifier's weights (`drum_agent/data/onset_classifier.npz`) come from
  `scripts/adt/train.py`; see docs/MODELS.md for its data and how it was chosen.
- Never add a fallback that produces a chart without LilyPond.
- Never weaken the rights gate in `drum_agent/rights.py`: every transcription needs a stated
  basis. The one basis for commercial songs, `personal` (the user's own practice, approved by
  the project owner on 2026-10-29), is accepted only where one person uses the tool on their
  own computer (the CLI, `serve --personal`, the desktop app), never on a shared server, and
  the app never shares or publishes a personal chart. Recordings come only from the user's
  own files (an upload, or their music folders on their own computer) or a direct link to an
  audio file. Video sites and streaming services (YouTube, Spotify, Apple Music, Deezer...)
  are used only through their official APIs, for metadata, links and embedded players: no
  scraping, no undocumented endpoints, never their audio (project owner's rule, 2026-10-29).
