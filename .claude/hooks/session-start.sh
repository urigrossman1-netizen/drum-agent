#!/bin/bash
# SessionStart hook for Claude Code on the web: installs what the drum agent needs, so a
# fresh cloud session can engrave, transcribe and run the tests straight away.
# Idempotent: each step checks first and returns quickly when its part is installed.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# FluidSynth and the GM soundfont (synthesized audio for tests and evals) and ffmpeg
# (MP3/M4A input) are optional, so a failed install only warns.
missing=()
command -v fluidsynth >/dev/null || missing+=(fluidsynth)
command -v ffmpeg >/dev/null || missing+=(ffmpeg)
[ -f /usr/share/sounds/sf2/FluidR3_GM.sf2 ] || missing+=(fluid-soundfont-gm)
if [ ${#missing[@]} -gt 0 ]; then
  sudo=""
  [ "$(id -u)" -ne 0 ] && sudo="sudo -n"  # never wait for a password
  if ! { $sudo apt-get update -qq && $sudo env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y -qq --no-install-recommends "${missing[@]}"; } >/dev/null 2>&1; then
    echo "warning: could not install ${missing[*]} (optional: synthesized audio, MP3/M4A input)" >&2
  fi
fi

# LilyPond 2.26: the engraver. No chart is made without it.
scripts/install_lilypond.sh >/dev/null

# The package, with its test tools.
python -m pip install -q --root-user-action=ignore -e ".[test]"

python -m drum_agent doctor
