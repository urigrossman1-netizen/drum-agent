# Project recovery report

Written 2026-11-03 at the start of the "transcription platform" round, before any code changed.
It records where the Drum Agent's history lives, what was recovered from each place, the
decisions that must not be reversed, and what could not be recovered. Every statement marked
**confirmed** was read in the named source; **assumption** marks inferences.

## 1. Summary

- The Drum Agent is this repository, `urigrossman1-netizen/drum-agent`. The live line of work
  is branch `claude/peaceful-noether-qz2xmc`: 111 commits, 2026-10-11 to 2026-10-30, head
  `a9b52095`. **Confirmed** through the GitHub API.
- The repository's default branch, `claude/eager-keller-91y28i`, stops at `18d11f1a`
  (2026-10-13). It is an ancestor of the live branch and holds no work of its own.
  **Confirmed** by comparing the two trees: every file on it also exists on the live branch.
- The work was done in Claude Code cloud sessions on claude.ai (section 3). On 2026-11-03
  nothing of it was on the owner's Windows PC: no clone, no installed app, no audio.
- The project is far beyond a prototype:
  - CLI, web studio and Windows desktop app;
  - Docker image and three CI workflows;
  - 936 passing tests (2026-10-29 run);
  - a 113-chart library;
  - a neural onset classifier measured on real recordings.

  The gaps that remain are listed in section 10 and in `docs/DEVELOPMENT_PROGRESS.md`.

## 2. Sources searched

| Source | Reached? | What it held |
|---|---|---|
| GitHub: the owner's repositories (6) | yes (public API) | `drum-agent` is the only drum project; the others are unrelated (`learnforge`, `VANGUARD`, ...) |
| GitHub: `drum-agent` branches, commits, release, issue, Actions runs | yes | 2 branches, 111 commits, release `app-windows-15`, issue #1 (live links), CI green on 10-30 |
| Repository documentation | yes | `README.md`, `CLAUDE.md`, `docs/AUDIT.md`, `ARCHITECTURE.md`, `LIMITATIONS.md`, `MODELS.md`, `REPORT.md`, `WEB_APP.md`, `DEPLOY.md`, `DESKTOP.md`, `SONG_LOOKUP.md`, `GAMECHARTS.md`, `NOTATION_SPEC.md`, `implementation-audit.md` |
| Claude Code cloud sessions (claude.ai/code) | yes, after the owner signed in on 11-03 | 14 drum sessions, read through the session events feed (section 3) |
| claude.ai chats | yes | 18 chats in the account; one drum chat (2026-05-11). No drum chats from September or October exist in the account (section 9) |
| claude.ai artifacts | yes | "Drum Agent" library page (10-21), "Funk Ghost-Note Groove" (10-19), "Lithium", "Smells Like Teen Spirit", "Burnout" drum charts (10-07) |
| Claude Code sessions on this PC (desktop app) | yes | 3 sessions, none about drums |
| Local disk (home folders, PyCharm projects, Downloads, Music, program folders) | yes | nothing drum-related; the Music folder is empty; no Git, FFmpeg or LilyPond installed |
| Desktop-app agent-mode sessions folder | yes | skills only, no drum work |
| Google Drive, Vercel | not searched this time | a 09-27 session searched Google Drive and found nothing about drums; `implementation-audit.md` records Vercel refusing project creation (403) |

## 3. The sessions, in order (confirmed from their transcripts)

| Date | Session (title) | What happened |
|---|---|---|
| 05-11 | claude.ai chat "Drum arrangement for 'There is nothing holding me back'" | The idea's origin. The owner asked for a hard drum part, then "GIVE ME ALL OF THAT IN REAL DRUM LYRICS". The answers were invented patterns, not notation from audio |
| 09-27 | "Senior architect role setup" (two sessions) | 61K-character architect prompt. Then: "go through the drum chats ... You literally spent 1 million tokens on something that I don't know how it works". The session had no access to claude.ai chats and asked for share links |
| 09-30 | "Audio-faithful drum transcription system" | Never ran: a 43K-character prompt had been pasted into the environment's setup script ("You: command not found") |
| 10-03 | "Drum chart readability and zoom" (first) | Same setup-script failure |
| 10-03 | "Chat session credit usage" | The account has two cloud environments, "Default" and "Drum agent" (created 09-27) |
| 10-05 | "Drum chart readability and zoom" | "Make them look like real good drum charts ... zoom into the charts". Produced the interactive chart pages that became the 10-07 artifacts |
| 10-06 | "Drum agent repository usage" | An HTML/JS drum agent with sampled Hydrogen drums was built in that session's sandbox and **never pushed: lost**. The owner insisted on real drum sounds ("not some different instruments") and charts "like the picture" |
| 10-06 to 10-07 | "Drum Agent transcription pipeline" | 15K-character prompt for a testable transcription pipeline. Started the MDB Drums evaluation and audio validation; its work continued in the repository from 10-11 |
| 10-07 | "YouTube/Spotify MCP integration for drum-agent" | Asked for YouTube + Spotify search and a "local, legal audio-acquisition pipeline ... yt-dlp/ffmpeg". Later reversed (10-29 rule, section 4) |
| 10-11 | "Drum Agent sheet music engraving" | 23K-character engraving prompt. Created the repository and branch `eager-keller` (notation core, LilyPond/MusicXML/MIDI) |
| 10-13 to 10-30 | "Drum agent implementation" (pinned; 21,087 events) | The main session: everything on `peaceful-noether`. The owner's 46 messages are summarized below |
| 10-19, 10-21 | "Drum Agent (old ...)" ×2, "Drum Agent" | Sessions started from the library artifact: `doctor` and a smoke render, no changes |
| 10-19 | "Drum chart: A funk groove ..." | Made the "Funk Ghost-Note Groove" artifact from library chart G13 |

**The owner's messages in the main session** (abridged, in order):

1. **10-13:** go through all the drum chats; build the final Drum agent; "When it asks for a song ... it searches that song, listens to it perfectly, note by note ... writes the drum charts correctly"; take your time; test a lot.
2. **10-13:** a reference chart image, "This is an example of how the drum charts should look like" (section 5).
3. **10-19:** "give me a link that can take me and only me to use the agent ... not the code".
4. **10-19:** "Review your work, find all the errors ... make the thing ready to be used".
5. **10-25:** "You have spent more than 1m tokens in this chat. Tell me what you did ..."
6. **10-25 and 10-29:** three more long architect prompts. The 10-29 one produced `docs/implementation-audit.md`.
7. **10-25 and 10-26:** "I don't really get what you did, I just want YOU to use github, vercel ... so that I could use what you made"; "I am giving you the permission".
8. **10-28:** "the user TYPES a name of a song or beat and then YOU go and search up that song, then write its drum charts. Why in the app that you made the user needs to upload a file!"
9. **10-30:** "make it that ... other people could also use it ... a link like a localhost___".
10. **10-30, last message:** "YOU SEARCH THE SONGS, AND YOU FIND THE AUDIO! Not them! You spent more than 3million tokens ...". The answer explained that no website can legally fetch a famous song's audio from YouTube/Spotify/Apple. It offered three options:
    - find the song in the visitor's own music files;
    - a paid licensed music provider;
    - leave it as it is.

    The owner first answered "I have spotify plus, and it does let me download their songs". Told that those downloads are locked inside the Spotify app, they chose **"Leave it as it is"**.

## 4. Decisions that must not be reversed (confirmed)

| Decision | Where it is recorded |
|---|---|
| `drum_agent/model.py` is the single source of truth. Positions are exact `Fraction`s; renderers never invent rhythm | `CLAUDE.md`, `docs/ARCHITECTURE.md` |
| LilyPond is the only engraver; no fallback chart without it | `CLAUDE.md` |
| Kit positions, noteheads and MIDI notes live only in `kit.py` and match `docs/NOTATION_SPEC.md` | `CLAUDE.md`, `tests/test_kit.py` |
| House style: the owner's reference chart. Cymbals stems up; snare, toms and kick stems down; sticking under the staff; "Swing" mark; four bars a line | `NOTATION_SPEC.md`, skill `drum-chart` |
| Every note-for-note transcription needs a stated rights basis (`rights.py`). `personal` (approved by the owner 2026-10-29) only where one person uses the tool on their own computer; personal charts are never shared | `CLAUDE.md`, `rights.py` |
| No audio from video sites or streaming services. Official APIs only, for metadata, links and embedded players; no scraping, no yt-dlp (owner's rule 2026-10-29) | `CLAUDE.md`, commit `643b357` |
| The website charts recordings people upload; the personal/Windows app finds a typed song among the user's own music files (owner's choice 2026-10-30, "Leave it as it is") | main session, events 21018-21085 |
| Claude never adds, moves or changes a note. It names sections, reads beat descriptions and turns typed edits into editor commands, all validated | `web/claude.py`, `implementation-audit.md` §2 |
| Detection changes are measured with both synthetic evals and the real-recording dev split; no change that regresses held-out kits or band mixes; MDB Drums test split run once per model version | `CLAUDE.md`, `docs/MODELS.md` |
| Charts of non-commercial-licensed material and audio are never committed | `docs/LIMITATIONS.md`, skill rule 6 |

## 5. The reference chart

The image the owner sent on 10-13 (main session, event 552, PNG 360×520) is a Songsterr-style
drum part:
- hi-hat 8ths with x noteheads, stems up, beamed in fours;
- snare and kick stems down;
- four bars a line;
- a lyric cue ("hey") above the staff;
- quarter rests;
- a "Swing" marking;
- sticking "L R L R L R" under a fill.

The engraving in this repository follows it (`NOTATION_SPEC.md`). The image itself stays in that
session.

## 6. Architecture and technical choices (confirmed in code)

One Python package used three ways:
- the CLI (`python -m drum_agent`);
- the FastAPI studio (`serve`; `drum_agent/web/`);
- the Windows desktop app (`app`; pywebview + PyInstaller + Inno Setup).

Pipeline:
`audio/prepare.py` (ffmpeg to 44.1 kHz) → `audio/separate.py` (HTDemucs) → `audio/detect.py` (superflux candidates) +
`audio/classifier.py` (numpy MLP ensemble, 11 classes) → `audio/beats.py` → `quantize.py` →
`audio/structure.py` → `model.Score` → `layout.py` → `export/` (LilyPond, MusicXML 4.0, MIDI) →
`verify.py` (three-way read-back).

Details: `docs/ARCHITECTURE.md` and `docs/AUDIO_TRANSCRIPTION_PIPELINE.md`.

## 7. Integrations and their real status (confirmed in code, 2026-11-03)

| Integration | Status |
|---|---|
| MusicBrainz, iTunes, Deezer search | working, no keys; measured from GitHub runners (10-29) |
| YouTube Data API (`search.list`, `videos.list`) + `youtube-nocookie` embedded player | implemented; **never run against the real API**: no key was ever configured |
| Spotify Web API (client credentials, `/v1/search`) | implemented; **no key ever configured** |
| Anthropic (Claude) | implemented for section names, beat descriptions and typed edits; needs `ANTHROPIC_API_KEY` **and** `DRUM_AGENT_ANTHROPIC_MODEL` (no default); never exercised in CI |
| HTDemucs drum separation | working; weights shipped in the Docker image and Windows app; CPU only |
| Onset classifier | working; trained only on synthetic audio (`docs/MODELS.md`) |
| Hugging Face Space deploy | prepared (`scripts/deploy_space.py`, `container.yml`); blocked on `HF_TOKEN` |
| "Live studio" (GitHub Actions + Cloudflare quick tunnel) | working; each link lives about 5 hours |
| yt-dlp | removed (commit `643b357`); only a PyInstaller exclude remains |

## 8. Configuration and audio settings (confirmed)

**Environment variables** (`.env.example`; values are never committed):
- data: `DRUM_AGENT_DATA_DIR`;
- upload limits: `DRUM_AGENT_MAX_UPLOAD_MB` (200), `DRUM_AGENT_MAX_AUDIO_MINUTES` (20);
- assets: `DRUM_AGENT_ASSET_DIR`;
- providers: `DRUM_AGENT_PUBLIC_METADATA`, `DRUM_AGENT_PROVIDER_TIMEOUT`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `YOUTUBE_API_KEY`;
- Claude: `ANTHROPIC_API_KEY`, `DRUM_AGENT_ANTHROPIC_MODEL`, `DRUM_AGENT_ANTHROPIC_BASE_URL`;
- runtime: `DRUM_AGENT_TORCH_THREADS`, `DRUM_AGENT_MUSIC_DIRS`, `DRUM_AGENT_LILYPOND`, `DRUM_AGENT_LOG_LEVEL`.

**Audio**
- Decode to 44.1 kHz. The web path decodes to stereo 16-bit WAV; transcription loads it mono.
- HTDemucs gets the mono signal duplicated to two channels; the stem is averaged back to mono.
- Features: STFT 2048 / hop 256 (5.8 ms), 96 mel bands 30 Hz to 17 kHz.
- Onset matching window 50 ms in evaluations.

## 9. Failed attempts and lessons

1. **Setup-script paste (09-30, 10-03).** Long prompts pasted into the cloud environment's setup
   script made two sessions fail before starting. Prompts belong in the chat box.
2. **Lost prototype (10-06).** Work left unpushed in a cloud sandbox disappeared with it. Now
   everything is committed and pushed at checkpoints.
3. **yt-dlp audio path (10-07 to 10-29).** Built, then removed under the owner's own rule
   (official APIs only). Not to be rebuilt.
4. **Temporary links.** Cloudflare quick tunnels expire after about 5 hours ("the link doesn't
   work for me anymore", 10-27). A permanent address needs a hosting account (`HF_TOKEN`).
5. **Vercel.** The connector could list projects but was refused project and sandbox creation
   (403). Vercel is also a poor fit for long CPU jobs with PyTorch.
6. **Cloud environment network.** The development container's proxy refused musicbrainz.org,
   itunes.apple.com and api.deezer.com (403), and pretrained-model downloads failed there
   (`docs/REPORT.md` §1). This round develops on the owner's PC instead.
7. **Token spend.** The owner reported 1M, 2M, then 3M tokens without a clear way to use the
   result. This round works in checkpointed phases, each ending with something usable and a
   plain-language summary.

## 10. Outstanding bugs and gaps (confirmed by code audit, 2026-11-03)

**Audio and analysis**
- Raw detections are not kept: class probabilities, merged, dropped and hi-hat-conflict strokes, roll interiors, flam graces.
- There is no per-hit "edited by user" flag, and CLI `edit` overwrites its input.
- Stereo is folded to mono at load, and the full mix is never consulted after separation.
- Meter from audio is 3/4 or 4/4 only; 12/8 needs `--feel triplet`; odd meters are not supported.
- `--bpm` is in the wrong units for compound meters (`beats.py`).
- Section letters are never reused for repeats.
- Fills are counted but not marked on bars.
- A separation failure aborts the whole job.
- torch and demucs are undeclared and unpinned.
- The published accuracy is detector-level, not chart-level.

**Web**
- Upload decoding runs inside the request, and the size limit applies only after the full upload arrives.
- No rate limits, no CSRF guard, no Host allowlist in personal mode.
- The live-studio workflow caches visitors' uploads.
- A duplicated project loses its audio when the original is deleted.
- Claude calls have no default model and small token caps.
- The YouTube player is a plain embed, not synced to anything.
- No timestamp seek; speed changes the recording's pitch.
- No whole-section loop.
- Fixed velocities in the grid editor.
- No simplified versions of transcriptions.
- The full WAV is streamed for listen-along.

**Docs that disagree with code**
- `store.py` says source WAVs are never served.
- `WEB_APP.md` describes version-creating actions that only edit the working copy.
- `DEPLOY.md` says uploads return at once.

## 11. Planned but never implemented

- A permanent public address (blocked on a hosting token).
- Real-API runs of YouTube and Spotify search (blocked on keys).
- A licensed audio provider (declined by the owner on 10-30).
- Retraining the classifier on permissive-only samples, or on commercially usable real-world data
  (E-GMD, StemGMD), as the commercial path (`docs/MODELS.md`).
- Code signing and auto-update for the Windows app.

## 12. Unresolved and inaccessible

- **The "drum chats" of September.** On 09-27 the owner described about 1M tokens of drum work in
  claude.ai chats. The account's chat list (18 chats) has none from September or October, so
  they were deleted, kept in another account, or were the cloud sessions above. **Not
  recoverable from here.**
- **The 10-06 HTML prototype** (sampled Hydrogen kit, "real AI agent") lived only in that
  session's sandbox. **Lost.**
- **The "drum-charts" skill** named in the 10-07 artifacts ("Transcribed by: Claude
  (drum-charts skill)") was made in a cloud session. It is not among the account's installed
  skills; the repository's `drum-chart` skill supersedes it.
- **Legal questions for a commercial launch.** Whether the classifier's weights are a derivative
  of its GPL and CC BY-SA training samples, and the HTDemucs weights' terms. Recorded in
  `docs/DEPENDENCY_AND_MODEL_LICENSE_AUDIT.md`.

## 13. Assumptions

- The September drum chats existed. Based only on the owner's 09-27 message.
- The 10-07 artifacts were produced by the 10-05 "readability and zoom" session. Their style and
  timing match, but the publish event was not traced.
