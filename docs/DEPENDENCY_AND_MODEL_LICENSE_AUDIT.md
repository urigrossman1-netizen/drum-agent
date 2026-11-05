# Dependency, model and data licence audit

Every external component the Drum Agent uses, ships, or was evaluated against: its licence,
what it is used for, and whether it suits a commercial product. Package licences below were
read from the installed packages' own metadata on 2026-11-04 (Windows, Python 3.12.10).
Model and dataset licences come from their primary pages (cited in `docs/MODELS.md` and in
the 2026-11-03 model survey). **Unverified** marks what no primary source confirmed.

This is an engineering record, not legal advice. Items marked *legal review* need a
lawyer before a commercial launch.

## 1. Verdict summary

| Area | Status |
|---|---|
| Python runtime dependencies | permissive (BSD, MIT, ISC, Apache) plus three LGPL libraries (`soxr`, `lameenc`, and `soundfile`'s libsndfile), used as separate dynamic libraries: fine for a commercial product if LGPL terms are honoured (§7) |
| Shipped programs (LilyPond GPL, FFmpeg LGPL, FluidSynth LGPL) | run as separate, unmodified programs with source offers in `NOTICES.txt`: fine |
| Onset classifier weights (ours) | **legal review**: trained on audio rendered from samples, some under GPL-2 or CC BY-SA. A permissive-only retraining path exists (§4) |
| HTDemucs weights (Meta) | **legal review**: code MIT; the weights carry no separate licence, and the training data is unverified (§4) |
| MDB Drums | non-commercial (CC BY-NC-SA 4.0): **evaluation only**, cached locally, never committed, never used for training |
| Provider APIs (YouTube, Spotify, MusicBrainz, iTunes, Deezer, Anthropic) | used within their terms for metadata, links, embeds and text only; never audio (§6) |
| Candidates excluded for licence reasons | ADTOF, LarsNet weights, madmom models, YourMT3+, All-In-One (§5) |

## 2. Python packages (installed versions, licence from package metadata)

### Core (`pip install -e .`)

| Package | Version | Licence | Role |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | arrays |
| scipy | 1.18.1 | BSD | signal processing |
| librosa | 1.0.0 | ISC | spectrograms, onsets, beat tracking |
| soundfile | 0.14.0 | BSD-3-Clause (bundles libsndfile, LGPL-2.1) | WAV/FLAC/OGG I/O |
| soxr | 1.1.0 (via librosa) | **LGPL-2.1-or-later** | resampling |
| numba / llvmlite | 0.68.1 / 0.50.0 | BSD / BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | librosa's JIT |
| scikit-learn, joblib, pooch, lazy-loader, decorator, msgpack | 1.9.1, 1.6.0, 1.9.0, 0.6, 5.3.1, 1.2.4 | BSD-3 / BSD-3 / BSD-3 / BSD-3 / BSD-2 / Apache-2.0 | librosa's dependencies |
| mido | 1.3.3 | MIT | MIDI |
| PyYAML | 6.0.3 | MIT | chart specs |
| xmlschema | 4.3.2 | MIT | MusicXML validation |
| pillow | 13.0.0 | MIT-CMU | page images |
| mir_eval | 0.8.2 | MIT | evaluation metrics |

### Web and desktop (`[web]`, `[desktop]`)

| Package | Version | Licence | Role |
|---|---|---|---|
| fastapi | 0.162.0 | MIT | web API |
| starlette | 1.10.0 | BSD-3-Clause | web API |
| pydantic | 2.14.2 | MIT | web API |
| uvicorn | 0.54.0 | BSD-3-Clause | server |
| python-multipart | 0.0.33 | Apache-2.0 | uploads |
| httpx | 0.28.1 | BSD-3-Clause | provider calls |
| anthropic | 2.4.0 | Apache-2.0 | Claude API client |
| pywebview | 6.2.1 | BSD-3-Clause | desktop window |

### Drum separation (installed separately: CPU wheels)

| Package | Version | Licence | Role |
|---|---|---|---|
| torch | 2.15.0+cpu | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib (the metadata's own expression) | HTDemucs inference |
| torchaudio | 2.11.1+cpu | BSD | demucs dependency |
| demucs | 4.1.0 | MIT | separation model code |
| julius, einops | 0.2.8, 0.8.2 | MIT, MIT | demucs dependencies |
| lameenc | 1.9.0 | **LGPL-3.0-or-later** | demucs dependency (MP3 encoding, unused by us) |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | progress bars |

### Test only (`[test]`, never shipped)

| Package | Version | Licence |
|---|---|---|
| pytest | 9.2.0 | MIT |
| verovio | 6.4.1 | LGPL-3.0-only |
| pdfplumber | 0.11.10 | MIT |
| pdfminer.six | 20260107 | MIT |

## 3. Programs the product runs or ships

| Program | Version | Licence | How it is used | Notes |
|---|---|---|---|---|
| LilyPond | 2.26.0 | GPL-3.0-or-later | separate program: engraves every chart | the Windows app ships it unmodified with a source link (`NOTICES.txt`): aggregation, not linking |
| FFmpeg (BtbN LGPL shared build) | "latest" (N-128352, 2026-11-03) | LGPL-2.1-or-later (no GPL parts) | separate program: decoding | **unpinned**: `fetch_tools.py` takes the rolling "latest" build. Pinning is planned (phase 5) |
| FluidSynth | 2.6.2 (pinned SHA-256) | LGPL-2.1-or-later | separate program: sampled drums, `synth` | added 2026-11-04 (`fetch_tools.py --sounds`) |
| FluidR3_GM.sf2 (Frank Wen) | Debian 3.1-5.3 (pinned SHA-256) | MIT | the General MIDI soundfont | the same file the Linux image installs |
| cloudflared | latest | Apache-2.0 | CI only (`live-studio.yml` tunnel) | unpinned, no checksum (phase 5) |
| PyInstaller | build tool | GPL-2.0 with bootloader exception | packages the Windows app | the exception permits distributing the built app |
| Inno Setup | build tool | Inno Setup licence (free, commercial use allowed) | Windows installer | |

## 4. Models

| Model | Code licence | Weights licence | Training data | Verdict |
|---|---|---|---|---|
| Onset classifier (`drum_agent/data/onset_classifier.npz`, ours) | this repository | ours | synthetic audio rendered from 44 kits (`docs/MODELS.md`): FluidR3 (MIT), csound GM (public domain), Audiophob (CC0), rumpf (CC BY 3.0), AVL kits and BJA Pacific (CC BY-SA 3.0), several Hydrogen kits (GPL-2/GPL-2+), MuseScore General (MIT), TimGM6mb (GPL-2) | **legal review**: whether weights are a derivative work of their training audio is unsettled law. Commercial fallback: retrain with `oneshots.py --permissive-only` and `DRUM_AGENT_PERMISSIVE=1` (FluidR3, csound, Audiophob, rumpf only; lower accuracy expected) |
| NMF drum templates (`drum_agent/data/templates.npz`) | this repository | ours | FluidR3 GM (MIT) | OK |
| HTDemucs `955717e8` (Rouard, Massa, Défossez 2023) | MIT (archived 2025-01; fork `adefossez/demucs` takes only important fixes) | **no separate licence stated**; downloaded from Meta's CDN | per the paper, MUSDB18-HQ plus extra songs: **unverified**; MUSDB18 itself is research-only | **legal review** before a commercial launch; it works today and stays the default |
| Onsets & Frames drums ONNX (`thebluescreen/oaf-drums-onnx`, from Magenta E-GMD) | Apache-2.0 + NOTICE.md | Apache-2.0 | E-GMD, CC BY 4.0 | OK with attribution. **Measured in phase 2, not adopted**: this conversion's closed hi-hat output is always 0, and alone it scores 0.557 against the classifier's 0.856. Benchmark only (`scripts/eval_backends.py`, downloaded on request, SHA-256 pinned); not shipped |
| ADT_STR (`pier-maker92/ADT_STR`, `Pierfrancesco/adt-str`) | CC BY-SA 4.0 (README "this work"); the Hugging Face card has **no licence field** | as code | Lakh MIDI + 8,495 one-shots from soundpacks.com packs (sample licences unknown) | **legal review**; benchmark and opt-in only. ShareAlike applies to modified weights. 289 MB per checkpoint. **Measured in phase 2, not adopted**: alone it scores 0.745 against the classifier's 0.856. Benchmark only (`scripts/eval_backends.py`, which also runs its code from the pinned revision: read before use, safetensors weights, no pickle); not shipped |
| Beat This! (CPJKU) | MIT | MIT ("the code and the published model weights") | 16 datasets, some copyrighted or limited CC (the authors' note) | OK (MIT notice). Phase 3 candidate |
| DrumScript | Apache-2.0 | none (rule-based) | none | benchmark baseline only, never shipped |

## 5. Excluded for licence reasons (2026-11-03 survey)

| Component | Why |
|---|---|
| ADTOF models and ADTOF-pytorch | CC BY-NC-SA 4.0 (non-commercial); the port has no licence file |
| LarsNet weights | CC BY-NC 4.0 |
| madmom pretrained models | CC BY-NC-SA 4.0 (the code is BSD, but its models are what make it useful) |
| YourMT3+ | GPL-3.0 code inside a distributed desktop app |
| All-In-One (`allin1`) | weights' licence not stated; NATTEN does not build for Windows/CPU |
| Community drum-separation checkpoints (DrumSep, RoFormer, SCNet via audio-separator) | licence and training data unknown |

## 6. Data and services

### Datasets

| Dataset | Licence | Use here |
|---|---|---|
| MDB Drums (Southall et al.) | CC BY-NC-SA 4.0 | evaluation only (`scripts/eval_real.py`); cached in `~/.cache/drum-agent/mdb-drums`; never committed, shipped or trained on. *Legal review:* whether internal benchmarking for a commercial product counts as non-commercial use |
| E-GMD (Magenta) | CC BY 4.0 | not used yet; a commercially usable real-kit training source |
| StemGMD (LarsNet authors) | CC BY 4.0 | not used yet; same |
| IDMT-SMT-Drums | CC BY-NC-ND 4.0 | not used |
| ENST-Drums | research use (unverified exact terms) | not used |

### Provider APIs

All provider APIs are used for metadata, links, embedded players and text only. The project
rule (owner, 2026-10-29) is no audio from video or streaming services.

| Service | Terms that matter | How the code complies |
|---|---|---|
| YouTube Data API v3 + embedded player | YouTube API Services Terms and Developer Policies: no downloading or separating audio; quota 10,000 units/day (a search costs 100); stored API data has refresh limits (**verify** the exact rule for stored video ids) | `search.list` + `videos.list` only; `youtube-nocookie.com` embed; no extraction code (yt-dlp removed in `643b357`) |
| Spotify Web API | Developer Terms: no downloading, no using Spotify content to train models, attribution | client-credentials `/v1/search` only, metadata shown with a link |
| MusicBrainz | core data CC0; at most about 1 request/second; meaningful User-Agent | User-Agent set; no throttling yet (phase 5) |
| iTunes Search API | Apple's terms for promoting Apple Media content | metadata search only |
| Deezer API | Deezer's API terms: **verify** commercial-use conditions before launch | search + track BPM only |
| Anthropic API | Commercial Terms; pay-as-you-go | text only: section names, beat descriptions, typed edit commands, chart explanations. Never note data invented by the model |

## 7. Obligations checklist

1. **NOTICES.** `packaging/fetch_tools.py` writes `tools/NOTICES.txt`: LilyPond, FFmpeg, HTDemucs, FluidSynth, FluidR3, with licences and source links. The installer ships it.
2. **LGPL (FFmpeg, FluidSynth, libsndfile, soxr, lameenc).** These stay as separate DLLs or `.pyd` files, unmodified and replaceable. The one-folder PyInstaller layout keeps them as files. Source links are in NOTICES.
3. **GPL (LilyPond).** Shipped unmodified as a separate program with a source link. Never linked into our code.
4. **Apache-2.0 (OaF ONNX, when adopted).** Ship its LICENSE and NOTICE.md with the model.
5. **CC BY-SA (ADT_STR, if ever shipped).** Attribution, and the same licence for any modified weights. Shipping waits for a legal review.
6. **MIT notices.** Demucs/HTDemucs, Beat This! and FluidR3 notices go in NOTICES when shipped.
7. **Charts of copyrighted songs.** Personal-practice charts carry "Transcribed for personal practice. Not for distribution." and are never shared (`rights.py`).

## 8. Commercial-launch risks, highest first

1. **HTDemucs weights' terms and training data.** Mitigation: legal review, or a separation model with clear commercial terms.
2. **Our classifier's GPL/CC BY-SA training samples.** Mitigation: legal review, or retrain permissive-only, and add E-GMD/StemGMD (CC BY 4.0) real-kit audio.
3. **Benchmarking on MDB Drums (CC BY-NC-SA).** Mitigation: legal review; a commercially licensed or self-recorded benchmark set.
4. **Deezer and YouTube stored-data terms.** Verify before launch.
5. **Unpinned FFmpeg, cloudflared, torch and demucs.** Pinning is planned in phase 5. Supply-chain risk, not a licence risk.
