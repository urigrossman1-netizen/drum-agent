# Drum Agent Studio in a codespace

The studio starts by itself and opens in a new browser tab. If the tab didn't open,
open the **Ports** panel (bottom of the editor) and click the globe next to
**Drum Agent Studio (8000)**.

- The address is private: only your GitHub account can open it.
- Your charts are stored in this codespace (`~/.drum_agent/web`). They stay there while
  the codespace exists; a codespace you don't use is deleted after 30 days by default.
- If the studio isn't running (after a restart, say), run `bash .devcontainer/start.sh`
  in the terminal. Its log is `/tmp/drum-agent.log`.
- Optional extras are set in the codespace's environment: `ANTHROPIC_API_KEY` and
  `DRUM_AGENT_ANTHROPIC_MODEL` (Claude), and `SPOTIFY_CLIENT_ID` /
  `SPOTIFY_CLIENT_SECRET` or `YOUTUBE_API_KEY` (search). Add them as Codespaces secrets
  under GitHub → Settings → Codespaces. See `.env.example`.
