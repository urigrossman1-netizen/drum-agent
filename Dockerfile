# The Drum Agent studio as a server: a shared website, every visitor with a private
# workspace (drum_agent/web/owners.py). Everything a chart needs is inside the image:
# LilyPond 2.26 (engraving), FFmpeg (decoding), CPU PyTorch with demucs and the HTDemucs
# weights (separating the drums from the band), so nothing is downloaded at run time except
# song metadata (MusicBrainz, iTunes, Deezer; Spotify and YouTube with keys).
#
#   docker build -t drum-agent .
#   docker run -p 8000:8000 -v drum-agent-data:/data drum-agent
#
# Charts, uploads and the database live in /data (mount a volume to keep them). Optional
# environment: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET, YOUTUBE_API_KEY, ANTHROPIC_API_KEY
# with DRUM_AGENT_ANTHROPIC_MODEL, DRUM_AGENT_MAX_UPLOAD_MB, DRUM_AGENT_MAX_AUDIO_MINUTES.
# Tested by .github/workflows/container.yml (a real recording through the whole workflow).
FROM python:3.12-slim-bookworm

ARG LILYPOND_VERSION=2.26.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DRUM_AGENT_DATA_DIR=/data DRUM_AGENT_LILYPOND=/opt/lilypond-${LILYPOND_VERSION}/bin/lilypond \
    TORCH_HOME=/opt/torch NUMBA_CACHE_DIR=/tmp/numba PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates fontconfig \
 && rm -rf /var/lib/apt/lists/*

COPY scripts/install_lilypond.sh /tmp/install_lilypond.sh
RUN LILYPOND_VERSION=${LILYPOND_VERSION} PREFIX=/opt bash /tmp/install_lilypond.sh && rm /tmp/install_lilypond.sh

# The drum separation: CPU PyTorch (not the CUDA build), demucs and its model, fetched now.
# numpy first: demucs imports it without declaring it, and the PyTorch index doesn't bring it.
RUN pip install numpy \
 && pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install demucs \
 && python -c "from demucs.pretrained import get_model; get_model('htdemucs')"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY drum_agent ./drum_agent
COPY examples/specs/03_full_song_northbound.yaml ./examples/specs/
RUN pip install -e ".[web]" \
 && useradd --create-home --uid 1000 drumagent \
 && mkdir -p /data /tmp/numba && chown drumagent /data /tmp/numba

USER drumagent
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" > /dev/null || exit 1
CMD ["sh", "-c", "exec python -m drum_agent serve --host 0.0.0.0 --port \"${PORT}\" --seed-examples"]
