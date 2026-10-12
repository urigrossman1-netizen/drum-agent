# Phase 1 audit and implementation plan

Written at the start of the upgrade (October 2026). Kept as the record of what
existed, why it couldn't produce real drum charts, and the order in which the
work was done.

## Findings

**The repository was empty.** `urigrossman1-netizen/drum-agent` had no
commits: the local checkout had no history, and GitHub returned
`409 Git Repository is empty` for the default branch. Other branches didn't
exist. The user's other repositories (learnforge, van, vercel.json,
kwolegekey, VANGUARD) were searched for drum, transcription, notation or
skill code; none contained any. No `drum-chart` skill existed in the
repository, in `~/.claude/skills`, or in any plugin. So there was no working
functionality to preserve, and nothing to break. The system was designed and
built from scratch, as additions to an empty repository.

The environment had Python 3 and network access to PyPI, GitLab and
`raw.githubusercontent.com`. lilypond.org, musescore.org and librosa.org were
blocked by the network policy, github.com returned 403 for direct downloads,
and Hugging Face / pytorch.org were unreachable. No pretrained drum-separation
or drum-transcription model (Demucs, ADTOF, Omnizart) could be downloaded.

## The nine audit questions

1. **How does the agent find or receive a song?** It didn't exist. Decision:
   the agent only works on files the user supplies (audio, MIDI, chart specs).
   It never fetches audio from streaming services and never bypasses DRM.
2. **How does it obtain and analyze audio?** Nothing existed. Built:
   librosa/soundfile/ffmpeg loading, a mel-spectrogram front end,
   harmonic/percussive separation, onset detection and NMF against drum
   templates (see ARCHITECTURE.md).
3. **How does it identify instruments, rhythms, fills and changes?** Nothing
   existed. Built: per-onset classification with musical rules; beat, tempo,
   meter and downbeat estimation; a quantizer with feel detection; section and
   fill detection.
4. **What internal representation does it use?** None. Built: one IR
   (`drum_agent/model.py`) with exact rational positions, the single source of
   truth for every output.
5. **How does the representation become a chart?** Nothing existed. Built:
   one rhythm speller feeding a LilyPond writer and a MusicXML writer, plus a
   MIDI writer from the same events, and a verifier that reads all of them
   back.
6. **Which notation tools exist?** None were installed. Evaluated and
   installed: LilyPond 2.26.0 (official GitLab binary), MuseScore 3.2.3
   (apt; too old for reliable command-line drum export, used only as an
   import check), Verovio 6.3 (pip; second renderer for MusicXML), FluidSynth
   with the FluidR3 GM soundfont (for audio fixtures).
7. **What does the existing skill teach, and where does it fail?** There was
   no skill. Created `.claude/skills/drum-chart/` following the current Claude
   Code skills documentation.
8. **What works and must be preserved?** Nothing pre-existing. From then on,
   every working feature got regression tests before the next one was built.
9. **Biggest obstacles.**
   - Engraving: drum notation has two voices, unusual noteheads and
     beat-aware rest and beam rules that a naive renderer gets wrong. Answer:
     a real engraving engine (LilyPond) driven by a careful rhythm speller.
   - Transcription: without downloadable neural models, detection has to come
     from signal processing; cymbals, ghost notes and drums masked by a band
     mix are hard. Answer: NMF with musically informed rules, honest
     confidence flags, and measurement on audio with known ground truth.
   - Trust: a valid PDF says nothing about whether the notes are right.
     Answer: the report separates rendering correctness (automatic
     cross-format checks) from transcription confidence (flags, plus
     listening).

## Ordered plan, as executed

1. Prove the engine: install LilyPond 2.26 and render an original
   hi-hat/snare/kick pattern with a simultaneous hit; inspect the PDF.
2. Write the notation spec (`docs/NOTATION_SPEC.md`) from LilyPond's
   percussion documentation, the Weinberg/PAS guidelines and MuseScore's
   drumset map.
3. Build the kit table, IR, rhythm speller, layout planner, and the LilyPond,
   MusicXML and MIDI exporters, with cross-format verification and XSD
   validation.
4. Build the chart-spec input format and the 10 required notation regression
   cases; review every rendered page.
5. Build MIDI import and the quantizer (swing, triplets, tempo maps).
6. Build audio transcription and measure it on synthesized audio with known
   ground truth (seen and held-out kits, band mixes, humanized timing); then
   test on real Creative Commons recordings.
7. Write the skill, a correction workflow (`edit`), and examples.
8. Write the remaining tests (CLI, edit, fuzzing, audio end-to-end, skill
   consistency); run a code review and stress tests; document limitations.
