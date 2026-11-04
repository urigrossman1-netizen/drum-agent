# Available tools, skills and integrations

An inventory of the capabilities available to the Claude sessions that work on this
project (taken on 2026-11-03, Claude Code in the Claude desktop app on the owner's Windows
PC). It says what each one is, whether it matters here, and how it is used. Capabilities
the product itself uses at runtime, such as provider APIs, are in
`docs/DEPENDENCY_AND_MODEL_LICENSE_AUDIT.md`.

## 1. Working environment

| Item | State on 2026-11-03 | Use |
|---|---|---|
| Windows 11 Pro, i5-1145G7 (4 cores / 8 threads), 15.7 GB RAM, Intel Iris Xe (no CUDA), 164 GB free | present | CPU-only development, tests and benchmarks; separation and inference run on the CPU |
| Python 3.14 | present (only pip) | left alone; the project uses a Python 3.12 virtual environment (PyTorch, demucs and numba wheels target 3.12; CI and the Windows build use 3.12) |
| winget 1.29 | present | installs Git, Python 3.12, GitHub CLI |
| Git, GitHub CLI | installed in phase 0 | clone, branch, commit, push, pull request |
| LilyPond 2.26.0, FFmpeg (LGPL build), HTDemucs weights | fetched in phase 0 by `packaging/fetch_tools.py` into `tools/` (git-ignored) | engraving, decoding, drum separation; the same files the Windows app ships |
| PyCharm 2026.2.3 | present | the owner's editor; the clone lives in `C:\Users\USER\PycharmProjects\drum-agent` |

## 2. Tools built into Claude Code

| Tool | Relevant | Use |
|---|---|---|
| PowerShell, Read/Write/Edit, Glob/Grep | yes | all code work |
| WebSearch / WebFetch | yes | model, licence and API research (sources cited in the docs) |
| Built-in browser pane (`Claude_Browser`) | yes | recovered the cloud-session transcripts (signed in by the owner); drives the studio on localhost for end-to-end checks; opens the API-key pages for the owner |
| Claude in Chrome | available, not used | the built-in browser covers every need |
| Artifacts | available | the existing "Drum Agent" library page is an artifact; not changed this round |
| Subagents: Explore, Plan, general-purpose, claude-code-guide | yes | Explore agents audited the audio pipeline, the web app and the model landscape in parallel (11-03); reviews and research later. One writer at a time on the code |
| Session tools (start/hand-off sessions, PR status, directory) | yes | moving the session into the clone; PR tracking |

## 3. Skills

### Used or planned this round

| Skill | Why |
|---|---|
| `drum-chart` (this repository, `.claude/skills/drum-chart/`) | the project's own workflow: chart types, rights check, transcription hints, QC checklist, honest delivery |
| `claude-api` | read before any change to `drum_agent/web/claude.py` (model ids, structured outputs, thinking and token limits) |
| `built-in-browser` | rules for the browser pane (sign-ins, tabs, localhost) |
| `run` | launching and driving the studio to see changes working |
| `pdf` | inspecting exported PDFs during verification |
| `code-review`, `security-review`, `simplify` | review of the branch before the pull request |
| `design:accessibility-review`, `design:design-critique`, `design:ux-copy` | audit of the studio pages touched in phase 4 |
| `dataviz` | if benchmark results are charted |
| `fewer-permission-prompts`, `update-config` | allow-listing routine read-only commands such as `pytest` so the owner gets fewer prompts (only with the owner's consent) |
| `deep-research` | available for multi-source research; the 11-03 model survey used one Explore agent instead, which was enough |
| `skill-creator` | if the `drum-chart` skill needs updating for new commands |

### Available, not relevant to this project

- `anthropic-skills`: animatemymap, computer-use, consolidate-memory, docs, docx, explain-usage, google-workspace, import-memory, morning, pptx, setup-claude, xlsx, chrome-browser.
- `small-business` (40+ skills: accounting, payroll, sales, marketing).
- `enterprise-search`.
- `design`: design-system, design-handoff, research-synthesis, user-research.
- Cowork plugin management.
- Built-in: loop, schedule, artifact-*, keybindings-help, plugin-authoring, init (`CLAUDE.md` already exists).

## 4. MCP servers and connectors

| Server | State | Relevant | Use / reason |
|---|---|---|---|
| Built-in browser, session, directory, PR, view, terminal tools (Claude desktop app) | connected | yes | see section 2 |
| Vercel | connected | no | refused project creation before (403); a serverless host is a poor fit for minutes-long PyTorch jobs |
| Google Drive (two connectors) | connected | no | nothing drum-related was found there on 09-27 |
| Spotify connector (search, playlists, library) | connected | marginal | acts for Claude in the owner's Spotify account; the product uses its own Spotify Web API credentials, metadata only |
| HasData YouTube (search, video, transcript) | connected (needs a HasData key to call) | **no** | a third-party data service, not YouTube's official API; the project's rule is official APIs only |
| Higgsfield (media generation, websites) | connected | no | |
| Claude Docs | connected | no | the owner asked for Markdown docs in the repository |
| Google Calendar, Shopify, scheduled tasks | connected | no | |
| MCP registry | connected | no | git and the GitHub CLI cover GitHub; Hugging Face model cards are read with WebFetch |
| Figma, Linear, Notion, Slack, Gmail, Canva, Stripe and about 30 more | need sign-in | no | |

## 5. Hooks

- Repository: `.claude/settings.json` runs `.claude/hooks/session-start.sh` at session start.
  - It exits at once unless `CLAUDE_CODE_REMOTE=true`.
  - In cloud sessions it installs FluidSynth, FFmpeg and LilyPond, then the package.
  - On Windows it needs Git Bash, which comes with Git.
- The cloud environment also ran a stop hook (`~/.claude/stop-hook-git-check.sh`) that asked for every change to be committed and pushed. This is a property of that environment, not of the repository.

## 6. External services the development work touches

| Service | For | Account needed |
|---|---|---|
| GitHub (repo, Actions, Releases, ghcr.io) | code, CI, Windows installer, server image | the owner's, signed in once through Git's browser window and `gh auth login` |
| Hugging Face Hub | downloading candidate model weights (public) and, optionally, a permanent Space | a token only for the Space |
| Google Cloud console | the YouTube Data API v3 key | the owner's Google account |
| Anthropic Console | the API key for Claude features (billed separately from a Claude subscription) | the owner's |
| Spotify for Developers | client ID and secret (metadata search) | the owner's |
| dl.fbaipublicfiles.com, gitlab.com (LilyPond), github.com/BtbN (FFmpeg) | tool and model downloads | none |
| github.com/CarlSouthall/MDBDrums | the real-recording benchmark (CC BY-NC-SA, evaluation only, cached locally) | none |
