# Running the studio as a website

The studio runs on a server as one Docker image (`Dockerfile`): the web app, LilyPond 2.26
(engraving), FFmpeg (decoding), CPU PyTorch with demucs and the HTDemucs weights (drum
separation), nothing fetched at run time except song metadata. On a shared server every
visitor gets a private workspace and the personal-practice rights basis is refused
(`docs/WEB_APP.md`, "Visitors of a shared server").

```bash
docker run -p 8000:8000 -v drum-agent-data:/data ghcr.io/urigrossman1-netizen/drum-agent:latest
```

## How it is tested

`.github/workflows/container.yml` builds the image on every change and runs it as a shared
server. It checks every tool, runs a real catalog search, and runs
`scripts/acceptance_run.py` as a visitor on a real annotated recording (MDB Drums, Britpop).
The acceptance run uploads the recording with a rights basis and requires the drum
separation to run. It then checks the chart, saves an edit as version 2, reopens both
versions, exports PDF, MusicXML and MIDI, and scores the chart against the human
annotations. Only an image that passes is pushed to `ghcr.io/<owner>/<repo>:latest`.

## What a host must give it

- **One process.** The job runner is a thread of the server process. The database is
  SQLite in `/data`. Run one replica, and give it more CPU rather than more copies.
- **Background jobs, not long requests.** An upload returns at once with a job. The page
  polls the job's stages, so a proxy's request timeout never cuts a transcription short.
  Jobs are stored, and a job interrupted by a restart is picked up again.
- **CPU and memory.** Separation takes about as long as the recording on two CPU threads
  (`DRUM_AGENT_TORCH_THREADS`). Transcription peaked at 1.1 GB for an 8.5-minute band mix
  without separation (`docs/LIMITATIONS.md`). HTDemucs needs more, and that hasn't been
  measured on a small host yet, so allow 4 GB or more.
- **Persistent `/data`.** It holds the database, the uploaded audio (normalized) and every
  chart version. Without a volume, a restart loses them.
- **Limits.** Uploads up to `DRUM_AGENT_MAX_UPLOAD_MB` (200) and recordings up to
  `DRUM_AGENT_MAX_AUDIO_MINUTES` (20).

## Environment

Set these on the host or as its secrets. Never put them in a file in the repository:
`.env` is ignored by git and Docker.

| Variable | Default | What it does |
|---|---|---|
| `DRUM_AGENT_DATA_DIR` | `/data` in the image | database, audio, charts |
| `PORT` | `8000` in the image | the port the server listens on |
| `DRUM_AGENT_MAX_UPLOAD_MB`, `DRUM_AGENT_MAX_AUDIO_MINUTES` | 200, 20 | upload limits |
| `DRUM_AGENT_PUBLIC_METADATA` | `1` | MusicBrainz, iTunes and Deezer search (no keys) |
| `DRUM_AGENT_PROVIDER_TIMEOUT` | 8 | seconds per catalog request |
| `YOUTUBE_API_KEY` | none | YouTube Data API v3 search (metadata, links, the embedded player) |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | none | Spotify Web API search (metadata only) |
| `ANTHROPIC_API_KEY`, `DRUM_AGENT_ANTHROPIC_MODEL` | none | Claude: section names, beat descriptions (never notes) |
| `DRUM_AGENT_ASSET_DIR` | none | recordings the operator is authorized to transcribe, with a manifest |
| `DRUM_AGENT_TORCH_THREADS` | PyTorch's choice | CPU threads for the separation |
| `DRUM_AGENT_LILYPOND`, `DRUM_AGENT_LOG_LEVEL` | set in the image, `INFO` | |

`DRUM_AGENT_MODE=personal` and `DRUM_AGENT_MUSIC_DIRS` are for the personal app on one
person's own computer only. Never set them on a shared server.

The keys come from Google Cloud (a project with the YouTube Data API v3 enabled, then an API
key) and from the Spotify developer dashboard (an app's client ID and secret). For CI and the
deployment below, store them as GitHub repository secrets with the same names.

## A permanent address: Hugging Face Space

After the image passes, the workflow's `deploy` job calls `scripts/deploy_space.py`. The
script creates or updates the public Docker Space `<your account>/drum-agent`, which
Hugging Face builds from the same Dockerfile. It copies the optional keys above into the
Space's secrets, waits until the new build runs, and then runs the same acceptance test
against the live address, `https://<account>-drum-agent.hf.space`. The job needs one
repository secret, `HF_TOKEN`: a Hugging Face access token with write permission. Without
it the job deploys nothing and says so. To deploy after adding the token, re-run the
latest "Server image" workflow run.

On Hugging Face's free CPU hardware a Space sleeps after a period without visits and wakes
on the next one (a cold start of a minute or so). Its disk isn't kept across restarts
unless persistent storage is mounted at `/data` (the Space's settings). Check Hugging
Face's current terms for both.

Until then, `.github/workflows/live-studio.yml` puts the studio online for up to 5.5 hours
on a temporary `trycloudflare.com` address. It posts the address to the issue "Drum Agent
Studio: live link".
