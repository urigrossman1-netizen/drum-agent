"""Get the audio file a chart or an analysis will be made from.

`fetch_audio(source)` accepts two kinds of source:

* a local file: used where it is, never copied, moved or modified;
* a direct http(s) link to an audio file: checked by content type and
  extension, size-capped, streamed to a hidden temp file in the cache and
  renamed into place only when complete.

Pages on video sites (YouTube, Vimeo, SoundCloud...) are refused: their official
interfaces give metadata, links and embedded players, not audio for analysis, and Drum
Agent doesn't extract it. Spotify, Apple Music, Tidal, Deezer and Amazon Music are
refused too: their streams are DRM-protected, so they are used for metadata only.

Downloads go to a cache folder (`~/.cache/drum-agent/audio`, or
`DRUM_AGENT_AUDIO_CACHE`), never into the repository, under sanitised names
that carry a hash of the URL, and never over an existing file. Fetching audio
grants no right to transcribe it: that is `drum_agent.rights`, checked by the
caller before a download meant for transcription.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .local import AUDIO_EXTENSIONS
from .lookup import MetadataError, open_url, text_key

CACHE_ENV = "DRUM_AGENT_AUDIO_CACHE"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30.0  # seconds per network operation (connect, each read)
CHUNK = 1 << 16
MIN_RATE = 16 * 1024  # bytes/s: slower than this after the first 30 s, a download is given up
SLOW_GRACE_S = 30.0
DURATION_TOLERANCE = 0.10  # a recording within 10 % of the identified length counts as the same version

VIDEO_REFUSED = ("{url} is a page on a video site. Its official interfaces give links and a player, "
                 "not audio to analyse, and Drum Agent doesn't extract it: give a recording you have "
                 "(a file, or a direct link to an audio file you have the right to transcribe).")

# (host suffix, service): DRM-protected streams, metadata only.
_STREAMING_HOSTS = (
    ("spotify.com", "Spotify"), ("spotify.link", "Spotify"), ("spoti.fi", "Spotify"),
    ("music.apple.com", "Apple Music"), ("itunes.apple.com", "Apple Music"), ("apple.co", "Apple Music"),
    ("tidal.com", "Tidal"), ("tidal.link", "Tidal"),
    ("deezer.com", "Deezer"), ("deezer.page.link", "Deezer"), ("dzr.page.link", "Deezer"),
    # their audio CDNs (previews and streams)
    ("scdn.co", "Spotify"), ("spotifycdn.com", "Spotify"), ("dzcdn.net", "Deezer"), ("mzstatic.com", "Apple Music"),
    ("tidalhifi.com", "Tidal"), ("media-amazon.com", "Amazon Music"),
)
_STREAMING_SCHEMES = {"spotify": "Spotify", "deezer": "Deezer", "tidal": "Tidal", "itms": "Apple Music",
                      "itmss": "Apple Music", "music": "Apple Music"}
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com", "dailymotion.com",
                "soundcloud.com", "bandcamp.com")

_AUDIO_TYPES = {"application/ogg", "application/flac", "application/x-flac"}
_GENERIC_TYPES = {"application/octet-stream", "binary/octet-stream", "application/binary", "application/download",
                  "application/force-download", "video/mp4"}  # fine when the extension says audio
_PLAYLIST_TYPES = {"audio/x-mpegurl", "audio/mpegurl", "application/vnd.apple.mpegurl", "application/x-mpegurl",
                   "audio/x-scpls", "audio/scpls"}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_EXT_BY_TYPE = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
                "audio/aac": ".m4a", "audio/flac": ".flac", "audio/x-flac": ".flac", "application/flac": ".flac",
                "application/x-flac": ".flac", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
                "audio/vnd.wave": ".wav", "audio/ogg": ".ogg", "application/ogg": ".ogg", "audio/opus": ".opus",
                "audio/aiff": ".aiff", "audio/x-aiff": ".aiff", "audio/webm": ".webm"}


class FetchError(RuntimeError):
    """The audio can't (or mustn't) be fetched; the message says what to do instead."""


@dataclass
class AudioSource:
    path: Path
    origin: str  # "file" (the user's, used in place) or "direct" (a downloaded link)
    url: str | None = None
    title: str | None = None
    uploader: str | None = None
    duration_s: float | None = None
    license: str | None = None
    note: str | None = None  # e.g. "already in the cache"

    def describe(self) -> str:
        """Where the audio came from, precisely enough for a chart's source line."""
        if self.origin == "file":
            return f"audio file {self.path}"
        bits = [f"direct download {self.url}"]
        if self.title:
            bits.append(f'title "{self.title}"')
        if self.uploader:
            bits.append(f"uploader {self.uploader}")
        bits.append(f"licence: {self.license or 'not stated'}")
        return ", ".join(bits) + f"; saved as {self.path}"


# ---- what a source is -----------------------------------------------------------------

def _host_is(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def _host(parts: urllib.parse.SplitResult) -> str:
    """The host name the resolver will look up: urllib decodes %XX in it ("p.s%63dn.co" is
    p.scdn.co), and Python IDNA-encodes a non-ASCII name, which drops a soft hyphen, maps "º" to
    "o" and reads U+3002 as a dot. "open.spotify.com." is the same host."""
    host = urllib.parse.unquote(parts.hostname or "").lower()
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise FetchError(f"{host!r} is not a valid host name; give it in ASCII") from None
    return host.rstrip(".")


def streaming_service(source: str) -> str | None:
    """The DRM streaming service a link or URI belongs to, if any."""
    parts = urllib.parse.urlsplit(source.strip())
    scheme = parts.scheme.lower()
    if scheme in _STREAMING_SCHEMES:  # spotify:track:..., deezer://..., itms://...
        return _STREAMING_SCHEMES[scheme]
    if scheme not in ("http", "https"):
        return None
    host = _host(parts)
    for suffix, name in _STREAMING_HOSTS:
        if _host_is(host, suffix):
            return name
    if re.match(r"^(?:.+\.)?music\.amazon\.[a-z.]+$", host) or (  # also www./smile., and /-/es/music...
            re.match(r"^(?:.+\.)?amazon\.[a-z.]+$", host) and re.match(r"(?:/-/[\w-]+)?/music(?:/|$)",
                                                                         parts.path.lower())):
        return "Amazon Music"
    return None


def refuse_streaming(source: str) -> None:
    service = streaming_service(source)
    if service:
        raise FetchError(
            f"{service} streams are DRM-protected: Drum Agent uses {service} for song metadata only and never "
            f"downloads or records its audio. Use a file you own (--audio FILE), your music folder "
            f"(--library DIR), or a direct link to an audio file you may use (--url).")


def is_video_page(url: str) -> bool:
    host = _host(urllib.parse.urlsplit(url))
    return any(_host_is(host, h) for h in _VIDEO_HOSTS)


def _scheme(source: str) -> str | None:
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", source)
    if not m or len(m.group(1)) == 1:  # "C:\..." is a Windows path, not a URL
        return None
    return m.group(1).lower()


def license_hint(license_text: str | None) -> tuple[str | None, str] | None:
    """(suggested --rights value or None, explanation) for a licence the source states.

    Only ever a suggestion: whether the uploader owned the recording, and whether the
    licence covers a transcription, is for the user to check."""
    if not license_text:
        return None
    t = text_key(license_text)
    said = f'The source states the licence "{license_text}"'
    if "public domain" in t or re.search(r"\bcc ?0\b", t):
        return "public_domain", (f"{said}. If the recording really is in the public domain, "
                                 f"--rights public_domain fits.")
    if "creative commons" in t or re.search(r"\bcc by\b", t):
        if "noderiv" in t or "no deriv" in t or re.search(r"\bnd\b", t):
            return None, (f"{said}. A NoDerivatives licence does not allow adaptations, so it does not cover a "
                          f"transcription; ask the rights holder (--rights permission).")
        return "licensed", (f"{said}, a Creative Commons licence. If the uploader owns the recording and the "
                            f"licence allows adaptations, --rights licensed fits (give the attribution it asks for).")
    return None, f"{said}; read it to see whether it allows a transcription."


# ---- cache ----------------------------------------------------------------------------

def _repo_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").is_file() and (root / "drum_agent").is_dir() else None


def cache_root(cache_dir: str | Path | None = None) -> Path:
    """The download folder: `cache_dir`, $DRUM_AGENT_AUDIO_CACHE, or ~/.cache/drum-agent/audio."""
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    d = Path(cache_dir or os.environ.get(CACHE_ENV) or Path(base) / "drum-agent" / "audio").expanduser().resolve()
    repo = _repo_root()
    if repo is not None and d.is_relative_to(repo):
        raise FetchError(f"the audio cache {d} is inside the drum-agent repository; downloads never go there. "
                         f"Set {CACHE_ENV} to a folder outside it.")
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(text: str, limit: int = 60) -> str:
    """ASCII letters, digits, '.', '_' and '-' only: no separators, no leading dot, bounded length."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", t).strip("._-")
    t = t[:limit].rstrip("._-")
    if not t and any(ch.isalnum() for ch in text):  # a title in another script: a hash, not "audio" for all
        t = "audio-" + hashlib.sha256(text.strip().encode()).hexdigest()[:8]
    return t or "audio"


# ---- local files ----------------------------------------------------------------------

def local_file(path: str | Path) -> AudioSource:
    p = Path(path).expanduser()
    if not p.is_file():
        raise FetchError(f"{p}: no such audio file")
    return AudioSource(p.resolve(), "file")


# ---- direct links ---------------------------------------------------------------------

def _audio_ext(url: str, ctype: str | None) -> str:
    ext = PurePosixPath(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix.lower()
    if ext in AUDIO_EXTENSIONS:
        return ext
    return _EXT_BY_TYPE.get(ctype or "", "")


def _is_audio_type(ctype: str | None, url_ext: str) -> bool:
    if ctype is None or ctype in _GENERIC_TYPES:
        return url_ext in AUDIO_EXTENSIONS
    return (ctype.startswith("audio/") and ctype not in _PLAYLIST_TYPES) or ctype in _AUDIO_TYPES


def _looks_like_html(chunk: bytes) -> bool:
    head = chunk.lstrip()[:64].lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<?xml"))


def download_url(url: str, cache_dir: str | Path | None = None, *, max_bytes: int = MAX_DOWNLOAD_BYTES,
                 timeout: float = DOWNLOAD_TIMEOUT) -> AudioSource:
    """Download a direct link to an audio file into the cache (a web page is refused)."""
    refuse_streaming(url)
    parts = urllib.parse.urlsplit(url)
    host = _host(parts)
    if host != (parts.hostname or "").rstrip("."):  # %XX or not ASCII: the request would go to `host`, say so
        raise FetchError(f"{url}: the host name {parts.hostname!r} is not plain ASCII (or has %XX in it); give the "
                         f"link with the host written as {host}")
    cache = cache_root(cache_dir)
    try:
        resp = open_url(url, timeout, refuse=refuse_streaming)  # every redirect, before it is followed
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url}: HTTP {exc.code} ({' '.join(str(exc.msg).split())})") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException, MetadataError) as exc:
        raise FetchError(f"{url}: can't download it ({getattr(exc, 'reason', exc)})") from None
    with resp:
        final_url = resp.geturl() or url
        refuse_streaming(final_url)  # a redirect to a streaming service is still one
        if urllib.parse.urlsplit(final_url).scheme.lower() not in ("http", "https"):
            raise FetchError(f"{url} redirects to {final_url}; only http(s) downloads are made")
        raw_type = resp.headers.get("Content-Type")
        ctype = resp.headers.get_content_type() if raw_type else None
        url_ext = PurePosixPath(urllib.parse.urlsplit(final_url).path).suffix.lower()
        if ctype in _HTML_TYPES:
            raise FetchError(f"{url} is a web page, not an audio file: give a direct link to the audio file")
        if ctype in _PLAYLIST_TYPES:
            raise FetchError(f"{url} is a playlist or a live stream ({ctype}), not an audio file")
        if not _is_audio_type(ctype, url_ext):
            raise FetchError(f"{url} is {ctype or 'of no stated type'}, not audio; give a direct link to an audio "
                             f"file ({', '.join(sorted(AUDIO_EXTENSIONS))})")
        try:
            length = int(resp.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > max_bytes:
            raise FetchError(f"{url} is {length / 1e6:.0f} MB; the download limit is {max_bytes / 1e6:.0f} MB")
        stem = PurePosixPath(urllib.parse.unquote(urllib.parse.urlsplit(final_url).path)).stem or "download"
        digest = hashlib.sha256(url.encode()).hexdigest()[:10]
        final = cache / f"{safe_name(stem)}-{digest}{_audio_ext(final_url, ctype) or '.audio'}"
        if final.exists():  # the same link, downloaded before: ours, complete (renamed only when done)
            return AudioSource(final, "direct", url=url, note="already in the cache")
        _stream_to(resp, final, max_bytes, url)
    return AudioSource(final, "direct", url=url)


def _stream_to(resp, final: Path, max_bytes: int, url: str) -> None:
    """Copy the body to a hidden temp file next to `final`, then rename: no half file ever has the real name."""
    fd, tmp_name = tempfile.mkstemp(dir=final.parent, prefix=".", suffix=".part")
    tmp = Path(tmp_name)
    # read(n) waits for all n bytes, and each byte restarts the socket timeout: read what has
    # arrived instead, so that a trickle is measured after every receive.
    read = getattr(resp, "read1", resp.read)
    try:
        n = 0
        head = b""  # the first bytes, which may arrive a few at a time
        t0 = time.monotonic()
        with os.fdopen(fd, "wb") as out:
            while True:
                elapsed = time.monotonic() - t0
                if elapsed > SLOW_GRACE_S and n < MIN_RATE * elapsed:
                    raise FetchError(f"{url}: the download is too slow ({n / elapsed / 1024:.0f} kB/s); try again "
                                     f"later or give a file with --audio")
                try:
                    chunk = read(CHUNK)
                except (OSError, http.client.HTTPException) as exc:
                    raise FetchError(f"{url}: download interrupted ({exc or type(exc).__name__})") from None
                if not chunk:
                    break
                if n < 64:
                    head += chunk
                    if _looks_like_html(head):
                        raise FetchError(f"{url} sent a web page, not audio")
                n += len(chunk)
                if n > max_bytes:
                    raise FetchError(f"{url} is larger than the download limit of {max_bytes / 1e6:.0f} MB")
                out.write(chunk)
        if n == 0:
            raise FetchError(f"{url} sent no data")
        if final.exists():
            raise FetchError(f"{final} appeared while downloading; not overwriting it")
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)


# ---- one entry point ------------------------------------------------------------------

def fetch_audio(source: str | Path, cache_dir: str | Path | None = None, *, max_bytes: int = MAX_DOWNLOAD_BYTES,
                timeout: float = DOWNLOAD_TIMEOUT) -> AudioSource:
    """A local path or a direct audio link -> an AudioSource with a local file. Video pages are refused."""
    if isinstance(source, Path):
        return local_file(source)
    s = str(source).strip()
    refuse_streaming(s)
    scheme = _scheme(s)
    if scheme is None:
        return local_file(s)
    if scheme == "file":
        return local_file(urllib.request.url2pathname(urllib.parse.urlsplit(s).path))
    if scheme not in ("http", "https"):
        raise FetchError(f"can't fetch {scheme}: links; give a file, or an http(s) link to an audio file")
    if is_video_page(s):
        raise FetchError(VIDEO_REFUSED.format(url=s))
    return download_url(s, cache_dir, max_bytes=max_bytes, timeout=timeout)
