#!/usr/bin/env bash
# Runs once when the codespace (or dev container) is created: everything the studio needs.
set -euo pipefail
cd "$(dirname "$0")/.."

sudo=""
[ "$(id -u)" -ne 0 ] && sudo="sudo"
$sudo apt-get update -qq
# ffmpeg: MP3/M4A uploads; fluidsynth + the GM soundfont: the sampled drum kit; poppler: PDF checks in tests
$sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  ffmpeg fluidsynth fluid-soundfont-gm poppler-utils curl ca-certificates
# LilyPond 2.26, the engraver (into /opt, where the app finds it)
$sudo scripts/install_lilypond.sh
python -m pip install -q -e ".[web,test]"
# The example song chart, so the catalog isn't empty
python -m drum_agent catalog seed-examples
python -m drum_agent doctor
