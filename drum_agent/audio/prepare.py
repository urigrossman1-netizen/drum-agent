"""Inspect, validate and normalize an audio file before transcription.

Every recording the app analyses is first decoded to one internal format: 44.1 kHz,
two channels, 16-bit PCM WAV, with the timeline of the original preserved (no
trimming, no time stretching). Each model then takes what it needs from that file:
the onset classifier and beat tracker read it as 44.1 kHz mono (`transcribe.load_audio`).

`prepare()` refuses, with an `AudioError` the user can act on: an extension or file
signature that is not a supported audio format, a file over the size limit, no audio
stream, a duration outside the limits, a decode that fails or comes out shorter than
the container says (a truncated file), and silence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

INTERNAL_SR = 44100
INTERNAL_CHANNELS = 2
EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg")
MAX_BYTES = int(os.environ.get("DRUM_AGENT_MAX_UPLOAD_MB", "200")) * 1024 * 1024
MIN_SECONDS = 5.0
MAX_SECONDS = float(os.environ.get("DRUM_AGENT_MAX_AUDIO_MINUTES", "20")) * 60
SILENCE_DBFS = -60.0  # RMS of the whole file below this: nothing to transcribe
DECODE_TIMEOUT = 300


class AudioError(ValueError):
    """The file can't be used; `code` is stable for the API, the message is for people."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class PreparedAudio:
    path: Path  # the normalized WAV
    sha256: str  # of the original file: the same recording uploaded twice is one source
    size_bytes: int
    duration_s: float
    original_codec: str
    original_sample_rate: int
    original_channels: int
    original_format: str
    rms_dbfs: float
    peak_dbfs: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        return d


def sniff(head: bytes) -> str | None:
    """The audio container a file's first bytes announce, or None."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "aac"  # ADTS frame header (layer bits 00)
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        return "mp3"  # MPEG audio frame sync
    return None


def _tool(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise AudioError("tool_missing", f"{name} is not installed; it is needed to read audio files")
    return exe


def probe(path: Path) -> dict:
    """Container and first audio stream properties from ffprobe."""
    try:
        r = subprocess.run([_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
                            "-show_streams", str(path)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, check=False)
    except subprocess.TimeoutExpired:
        raise AudioError("unreadable", "reading the file's properties timed out") from None
    if r.returncode != 0:
        raise AudioError("unreadable", "the file is not a readable audio file: " + r.stderr.strip()[-300:])
    info = json.loads(r.stdout or "{}")
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise AudioError("no_audio", "the file has no audio stream")
    st, fmt = audio[0], info.get("format", {})
    duration = st.get("duration") or fmt.get("duration")
    return {
        "codec": st.get("codec_name", "?"),
        "sample_rate": int(st.get("sample_rate") or 0),
        "channels": int(st.get("channels") or 0),
        "duration_s": float(duration) if duration not in (None, "N/A") else None,
        "format": fmt.get("format_name", "?"),
    }


def _levels(wav: Path) -> tuple[float, float, float]:
    """(duration in seconds, RMS dBFS, peak dBFS) of a 16-bit WAV, read in blocks."""
    import soundfile as sf
    total, sq, peak = 0, 0.0, 0.0
    with sf.SoundFile(str(wav)) as f:
        for block in f.blocks(blocksize=INTERNAL_SR * 10, dtype="float32", always_2d=True):
            total += block.shape[0]
            sq += float(np.square(block, dtype=np.float64).sum())
            peak = max(peak, float(np.abs(block).max(initial=0.0)))
        sr, ch = f.samplerate, f.channels
    if not total:
        return 0.0, -np.inf, -np.inf
    rms = (sq / (total * ch)) ** 0.5
    db = lambda v: 20 * np.log10(v) if v > 0 else -np.inf
    return total / sr, db(rms), db(peak)


def wav_declared_seconds(path: Path) -> float | None:
    """The duration a WAV header announces (data chunk size / byte rate). ffprobe reports
    the duration of the bytes present, so a cut-off WAV is only visible here."""
    import struct
    try:
        with open(path, "rb") as f:
            if f.read(12)[8:12] != b"WAVE":
                return None
            byte_rate = None
            while True:
                head = f.read(8)
                if len(head) < 8:
                    return None
                cid, size = head[:4], struct.unpack("<I", head[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(size + (size & 1))
                    byte_rate = struct.unpack("<I", fmt[8:12])[0] if len(fmt) >= 12 else None
                elif cid == b"data":
                    if not byte_rate or size in (0, 0xFFFFFFFF):
                        return None
                    return size / byte_rate
                else:
                    f.seek(size + (size & 1), 1)
    except (OSError, struct.error):
        return None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(src: str | Path, out_wav: str | Path, *, original_name: str | None = None) -> PreparedAudio:
    """Validate `src` and decode it to the internal WAV at `out_wav`."""
    src, out_wav = Path(src), Path(out_wav)
    name = original_name or src.name
    ext = Path(name).suffix.lower()
    if ext not in EXTENSIONS:
        raise AudioError("unsupported_type", f"{ext or 'no extension'}: supported audio files are "
                         + ", ".join(e.lstrip(".").upper() for e in EXTENSIONS))
    size = src.stat().st_size
    if size == 0:
        raise AudioError("empty", "the file is empty")
    if size > MAX_BYTES:
        raise AudioError("too_large", f"the file is {size / 2**20:.0f} MB; the limit is {MAX_BYTES / 2**20:.0f} MB")
    with open(src, "rb") as f:
        kind = sniff(f.read(16))
    if kind is None:
        raise AudioError("bad_signature", f"{name} does not start like an audio file (renamed or corrupt?)")
    props = probe(src)
    expected = props["duration_s"]
    if kind == "wav":
        declared = wav_declared_seconds(src)
        if declared and (expected is None or declared > expected):
            expected = declared
    if expected is not None and expected < MIN_SECONDS:
        raise AudioError("too_short", f"the recording is {expected:.1f} s; at least {MIN_SECONDS:g} s is needed")
    if expected is not None and expected > MAX_SECONDS:
        raise AudioError("too_long", f"the recording is {expected / 60:.1f} min; the limit is {MAX_SECONDS / 60:g} min")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_name(out_wav.name + ".part")
    try:
        r = subprocess.run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0",
                            "-vn", "-ac", str(INTERNAL_CHANNELS), "-ar", str(INTERNAL_SR), "-c:a", "pcm_s16le",
                            "-f", "wav", str(tmp)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=DECODE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        raise AudioError("decode_failed", "decoding the file timed out") from None
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise AudioError("decode_failed", "the file could not be decoded: " + r.stderr.strip()[-300:])
    duration, rms, peak = _levels(tmp)
    if expected and duration < expected - max(0.5, 0.01 * expected):
        tmp.unlink(missing_ok=True)
        raise AudioError("truncated", f"only {duration:.1f} s of the {expected:.1f} s the file announces could be "
                         "decoded; the file is truncated or damaged")
    if duration < MIN_SECONDS:
        tmp.unlink(missing_ok=True)
        raise AudioError("too_short", f"the recording is {duration:.1f} s; at least {MIN_SECONDS:g} s is needed")
    if duration > MAX_SECONDS:
        tmp.unlink(missing_ok=True)
        raise AudioError("too_long", f"the recording is {duration / 60:.1f} min; the limit is {MAX_SECONDS / 60:g} min")
    if rms < SILENCE_DBFS:
        tmp.unlink(missing_ok=True)
        raise AudioError("silent", f"the recording is silent (level {rms:.0f} dBFS)")
    tmp.replace(out_wav)
    return PreparedAudio(out_wav, file_sha256(src), size, round(duration, 3), props["codec"],
                         props["sample_rate"], props["channels"], props["format"], round(rms, 1), round(peak, 1))
