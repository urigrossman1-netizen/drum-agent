# Benchmark results

`results/` keeps every accuracy run worth remembering, one `.json` (all the numbers,
per recording and pooled) and one `.md` (the printed tables) per run, named
`<date>_<label>`. Each records the commit it ran on, whether `drum_agent/` or the
benchmark script had uncommitted changes, the classifier version, the separation model and
the machine. A record that could not read its commit says why (`commit_unknown`).

Written by `scripts/eval_real.py` (real recordings: MDB Drums). The suites and how to
read them are in `docs/TESTING_AND_BENCHMARKS.md`.

Only numbers live here. The recordings and their annotations (MDB Drums, CC BY-NC-SA
4.0) stay in the local cache (`~/.cache/drum-agent/mdb-drums`) and are never committed.

Rules of use (see `CLAUDE.md`):
- choose between models and settings on the development split (`--split train`);
- run the held-out split (`--split test`) once per model version, and keep that run here.
