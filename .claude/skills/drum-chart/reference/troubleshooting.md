# Troubleshooting

Every failure in the Drum Agent is explicit: it stops with a message instead of
producing a degraded chart. Don't route around a failure (e.g. by drawing the
chart some other way). Fix the cause.

## Environment
| Message | Fix |
|---|---|
| `LilyPond was not found` | `scripts/install_lilypond.sh` (official 2.26 binary into /opt), or `apt-get install lilypond` (needs ≥ 2.24), or set `DRUM_AGENT_LILYPOND=/path/to/lilypond` |
| `LilyPond 2.22 is too old` | install 2.24+ as above; distro packages are often old |
| `fluidsynth` / soundfont missing (doctor) | only needed for `synth`/evaluation: `apt-get install fluidsynth fluid-soundfont-gm` |
| `ModuleNotFoundError: ...` | `pip install -e .` from the repo root (add `.[test]` for the test suite) |
| `PyYAML is required` | `pip install pyyaml`, or write the chart spec as JSON |

`python -m drum_agent doctor` lists every dependency and what it's for.

## Rendering
| Message | Meaning / fix |
|---|---|
| `LilyPond failed (exit 1): ...` | generated LilyPond didn't compile. The full log is written to `out/<stem>.log`. This is a bug in the exporter for that construct: reduce the score to the failing bar and add a regression case |
| `barcheck failed` / `fatal warnings` | a bar doesn't add up; treated as fatal on purpose. Usually a pickup or `length` in the chart spec |
| `exports disagree with the IR` | LilyPond MIDI, MusicXML or MIDI didn't match score.json. The report lists the first differing events. Never deliver; it's an exporter bug |
| `MusicXML 4.0 schema: INVALID` | same: exporter bug, report the element named |
| `need a grid finer than 32nds/sextuplets` | the rhythm (e.g. a quintuplet or 64ths) isn't supported. Simplify to the nearest supported rhythm and say so in the delivery, or leave the bar marked |

## Input
| Message | Fix |
|---|---|
| `no notes on MIDI channel 10 (drums); channels present: [...]` | the drums are on another channel: `midi FILE --channel N` |
| `no MIDI notes map to the drum kit` | not GM drum notes. Check the file (some e-kits use custom maps) and pass a `--kit` override |
| `unknown symbol` / `beat segments` / `unknown pattern` | chart-spec error; the message names the pattern and bar |
| `conflicting hi-hat states` | an open and closed hi-hat at the same moment; keep one |
| `both accent and ghost` | choose one |
| `roll ... past the barline` | split the roll at the barline (`r~~~` in each bar) |
| `bar range ... is outside` / `no kick at 7/8 in bar 12` (edit) | references use score.json bar numbers (second number in the report) and positions in whole notes |
| `full transcription requires --rights` | ask the user which basis applies; otherwise use `analyze` |

## Audio
| Situation | What to do |
|---|---|
| Speed | ≈ 45 s for a 3 min band mix on CPU; use `--start/--end` for quick checks of a passage |
| Memory | ≈ 560 MB peak for a 3 min song; chunked, so long files are OK |
| Very noisy/live recording | expect many flags; prefer a drum stem; tell the user the chart is a draft |
| Wrong tempo/meter/downbeat | see [transcription-guide.md](transcription-guide.md); re-run with hints rather than editing every bar |
| A real stem-separation model (Demucs etc.) | not bundled. If the user has a separated drum stem, use it with `--drums-only` |

## Engraving looks wrong but checks pass
- Collisions or cramped bars: `--bars-per-line 3` or `--staff-size 18`.
- Too much compression: `--repeats percent` (no repeat barlines) or `--repeats none`.
- A section label lands mid-line: sections shorter than half a line share a
  line by design; give them more bars or accept it.
- Anything else: reproduce it in a minimal chart spec and add it to
  `tests/cases/` before fixing.
