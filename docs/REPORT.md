# Final report

What was built, how it was checked, and what is still unverified. Every number
here was measured in this repository; nothing is estimated.

## 1. What was wrong

The repository was empty: no commits, no code, no skill (details in
[AUDIT.md](AUDIT.md)). There was nothing that could produce drum notation, no
internal representation, no engraving engine and no tests. Pretrained drum
separation or transcription models could not be downloaded in this
environment, so audio detection had to be built from signal processing.

## 2. What changed and why

- **One score format** (`drum_agent/model.py`): exact `Fraction` positions,
  instruments from one kit table (`kit.py`). Every output is generated from
  it, so the formats can't disagree.
- **A rhythm speller** (`rhythm.py`) implementing the notation rules (beats
  never hidden, rests by metrical level, tuplets, rolls), shared by the
  LilyPond and MusicXML writers.
- **Real engraving** with LilyPond 2.26 (`export/lilypond.py`), MusicXML 4.0
  (`export/musicxml.py`) and MIDI (`export/midi.py`). No fallback produces a
  chart without LilyPond.
- **Automatic verification** (`verify.py`): LilyPond's own MIDI, the MusicXML
  (notes, articulations, meters, schema) and our MIDI (notes, tempo map,
  barlines) are each read back and compared with the score.
- **Layout** (`layout.py`): simile marks, repeats with ×N, multi-bar rests,
  balanced line breaks, sections on new systems, page fitting.
- **Inputs**: chart specs (YAML/JSON), General MIDI drum tracks (with pickup,
  meter, tempo and marker handling), and audio (NMF detection, beat/meter/
  downbeat, quantizer with feel, short-bar detection, uncertainty flags).
- **Rights gate** (`rights.py`): note-for-note audio transcription needs a
  stated rights basis; `analyze` gives tempo, meter and form only.
- **The `drum-chart` skill** and its references, tested through real headless
  Claude Code sessions.
- **Two independent code reviews** (timing/import, notation, robustness/
  safety). Every confirmed finding was fixed with a regression test, including
  a kit-file code-execution hole and three ways the tool could overwrite a
  user's file.

## 3. Engine and convention

LilyPond 2.26.0 renders the PDF/PNG. The notation follows the Weinberg/PAS
drum-set convention: hands stems up, feet stems down, cymbals with x
noteheads above the staff, a Drum Key whenever anything beyond kick, snare
and hi-hat is used. The full contract is [NOTATION_SPEC.md](NOTATION_SPEC.md);
`tests/test_kit.py` enforces that the kit table matches it.

## 4. The skill

`.claude/skills/drum-chart/`:
- `SKILL.md`: non-negotiables (rights, honest status, no invented header text),
  workflow steps 0-6, the input-path table, delivery rules.
- `reference/notation.md`, `chart-spec.md`, `examples.md`,
  `transcription-guide.md` (method, measured accuracy, failure modes),
  `qc-checklist.md`, `troubleshooting.md`.

Use: ask Claude Code for "a drum chart of ..." (the skill is auto-discovered)
or run `/drum-chart <file or description>`.

Tested through `claude -p` in fresh clones, five scenarios:

| Scenario | Result |
|---|---|
| Groove described in words | pass; its finding (a hand-entered chart reported as "Verified by a human") led to the `entered` status |
| MIDI take with pickup, 12/8 bridge, tempo change | pass: notation F 1.000 (381/381), pickup, meters, tempi and sections exact |
| Audio, no rights stated | pass: no transcription, asked about rights, offered `analyze` |
| Audio, "I own it", no slash command | pass: auto-discovered, `--rights own`, notation F 0.882 vs. the source chart |
| Fix an existing chart | pass: exactly one kick added, bar 4 hi-hat → ride, nothing else changed |

## 5. Working formats

| Format | Produced by | Checked by |
|---|---|---|
| PDF + PNG pages | LilyPond | LilyPond's MIDI vs. the score (notes, tempo map); visual review |
| MusicXML 4.0 | own writer | read back (notes, articulations, meters); XSD schema |
| MIDI (`.mid`) | own writer | read back (notes, tempo map, barlines) |
| LilyPond source (`.ly`) | own writer | compiled every run |
| Score (`.json`) | the IR | reloads; schema version checked |
| Report (`.report.md/.json`) | pipeline | lists every check and the flagged bars |

## 6. Test suites and results

`python -m pytest -q`: **441 passed** (424 fast, 17 slow audio end-to-end) in 3 min 12 s
on a 4-CPU container, LilyPond 2.26.0.

- `tests/cases/` (10 notation charts) and `tests/audio_cases/` (3 audio charts).
- `tests/test_exports.py`: every case engraves cleanly and all formats agree.
- `tests/test_fuzz_exports.py`: random scores across seven meters.
- `tests/test_review_regressions.py`, `tests/test_cli.py`: one test per
  confirmed review finding.
- `tests/test_audio_e2e.py` (slow): chart → synthesized recording →
  transcription → scored against the chart.
- `scripts/eval_notation.py`: 10 charts × 4 conditions, mean notation F 0.897,
  median 0.972. `scripts/eval_detection.py`: onset F 0.900-0.989 on GM kits.

## 7. Difficult cases verified

Rendered and checked by eye as well as by the automatic checks:
- Flams and drags on a downbeat, at a meter change and at a line start
  (graces after the barline, `tests/cases/08`).
- Pickups (quarter and sub-beat), meter changes 4/4 → 12/8 → 4/4 with tempo
  marks in dotted quarters, tempo changes (`tests/cases/10`).
- 3/4, 7/8 (2+2+3), 5/4, 6/8, 12/8, 5/8, 3/8, 2/4 (`tests/cases/09`).
- Triplets, sextuplets, 32nds, rests by metrical level (`tests/cases/08`).
- Ghost notes, accents, rolls (tied across beats, dotted-half), flams
  (`tests/cases/07`).
- Open/closed/half-open hi-hat with "+" after an open note, hi-hat foot
  (`tests/cases/05`).
- Tom fills across the barline (`tests/cases/06`).
- Repeats: simile runs, `|: A B :| ×8`, rests inside repeats, tempo or meter
  changes inside a phrase (written out, not repeated).
- Multi-bar rests split at tempo, section and meter changes.
- A 17-instrument Drum Key that wraps inside the page.
- From audio: a 60-bar song with a 2/4 bar (notation F 0.948-0.983 across conditions),
  short bars inserted from crash placement, an 8.5-minute mix (195 s, 1.1 GB).
- Hostile text (quotes, backslashes, `#(...)`, control characters) printed
  literally; a kit file trying to run a command is refused.

## 8. Limitations (unverified or weak)

Full list with numbers: [LIMITATIONS.md](LIMITATIONS.md). In short:
- **All accuracy numbers come from synthesized audio.** Real recordings were
  only spot-checked (three Creative Commons files, no ground truth); expect
  lower accuracy and listen to every bar.
- Hi-hat foot strokes are not detected; drags are never detected; ghost notes
  next to the hi-hat and cymbals in band mixes are weak.
- Tempo can come out doubled or halved; odd meters from audio are not
  supported (MIDI and chart specs handle them).
- "(?)" flags catch 44% of wrong bars: they help, but don't replace listening.
- No neural source separation was available; `--drums-only` with a stem from
  another tool is the best path for full mixes.

## 9. Exact commands

```bash
pip install -e ".[test]" && scripts/install_lilypond.sh && python -m drum_agent doctor
python -m drum_agent render examples/specs/03_full_song_northbound.yaml -o out/northbound
python -m drum_agent midi take.mid --title "Take" --rights own -o out/take
python -m drum_agent transcribe song.wav --rights own --title "Song" -o out/song
python -m drum_agent analyze song.wav
python -m drum_agent edit out/song/song.json --add 12:3/8:snare:ghost --render out/song
python -m drum_agent verify out/song/song.json
python -m pytest -q -m "not slow"     # fast suite
python -m pytest -q                   # everything, including audio end to end
python scripts/eval_notation.py --jobs 4 && python scripts/eval_detection.py
```

Rendered examples: `examples/output/` (01-04 from chart specs, 05 from audio).
