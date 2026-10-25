"""Song search providers. All of them return metadata only: no provider here supplies
audio, so a search result is never "analyzable" by itself (see `sources.py`).

- metadata: MusicBrainz, iTunes and Deezer through `drum_agent.song.lookup` (no keys)
- spotify:  the Spotify Web API search, client-credentials flow, when SPOTIFY_CLIENT_ID and
            SPOTIFY_CLIENT_SECRET are set. Metadata only: Spotify audio and previews are
            never fetched or transcribed.
- youtube:  the YouTube Data API v3 (search.list and videos.list), when YOUTUBE_API_KEY is
            set. Metadata only: the server never downloads YouTube audio.

Every provider reports its own state (ok, not configured, or the error), so the page can
say which searches ran instead of showing a silent empty list.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..song import lookup
from .store import song_id_for

TIMEOUT = float(os.environ.get("DRUM_AGENT_PROVIDER_TIMEOUT", "8"))
VERSION_WORDS = [  # (label, pattern) checked against the title and the album
    ("live", r"\blive\b|\bunplugged\b|\bin concert\b"),
    ("demo", r"\bdemo\b"),
    ("remaster", r"\bremaster(ed)?\b"),
    ("acoustic", r"\bacoustic\b"),
    ("remix", r"\bremix\b|\bmix\)|\bedit\b"),
    ("instrumental", r"\binstrumental\b|\bkaraoke\b"),
    ("cover", r"\bcover\b|\btribute\b"),
]


def version_of(*texts: str | None) -> str:
    """"studio" unless the title or album names another version."""
    joined = " ".join(t for t in texts if t).lower()
    for label, pattern in VERSION_WORDS:
        if re.search(pattern, joined):
            return label
    return "studio"


def split_query(text: str) -> tuple[str, str | None]:
    """"American Idiot - Green Day" -> ("American Idiot", "Green Day")."""
    text = " ".join(text.split())
    for sep in (" - ", " – ", " — ", " by "):
        if sep in text:
            title, artist = text.split(sep, 1)
            if title.strip() and artist.strip():
                return title.strip(), artist.strip()
    return text, None


def _result(*, title, artist, album=None, year=None, duration_s=None, isrc=None, provider, provider_id=None,
            url=None, providers=None) -> dict:
    version = version_of(title, album)
    if isrc:
        sid = song_id_for(title, artist, "isrc", isrc)
    elif provider_id:
        sid = song_id_for(title, artist, provider, provider_id)
    else:
        sid = song_id_for(f"{title} [{version}]", artist)
    return {"id": sid, "title": title, "artist": artist, "album": album, "year": year,
            "duration_s": round(duration_s, 1) if duration_s else None, "isrc": isrc, "version": version,
            "provider": provider, "provider_id": provider_id, "url": url, "providers": providers or [provider],
            "analyzable": False}


# ---- MusicBrainz / iTunes / Deezer ---------------------------------------------------

def search_public_metadata(title: str, artist: str | None, limit: int = 10) -> tuple[list[dict], list[dict]]:
    states = []
    try:
        found = lookup.search_metadata(title, artist, timeout=TIMEOUT)
    except lookup.MetadataError as exc:  # every source failed: "no metadata source answered: A: ...; B: ..."
        message = str(exc)
        parts = message.split(": ", 1)[-1].split("; ")
        return [], [{"provider": n, "state": "error",
                     "detail": _short(next((p for p in parts if p.startswith(lookup.SOURCE_NAMES.get(n, n))), message))}
                    for n in lookup.SOURCES]
    failed = {name for name in lookup.SOURCES for w in found.warnings
              if w.startswith(lookup.SOURCE_NAMES.get(name, name))}
    for name in lookup.SOURCES:
        detail = next((w for w in found.warnings if w.startswith(lookup.SOURCE_NAMES.get(name, name))), None)
        states.append({"provider": name, "state": "error" if name in failed else "ok",
                       "detail": _short(detail) if detail else None})
    out = []
    for c in found[:limit]:
        url = next(iter(c.urls.values()), None)
        out.append(_result(title=c.title, artist=c.artist, album=c.album, year=c.year, duration_s=c.duration_s,
                           isrc=c.isrc, provider=c.sources[0] if c.sources else "metadata", url=url,
                           providers=list(c.sources)))
    return out, states


# ---- Spotify (metadata only) ---------------------------------------------------------

class Spotify:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    SEARCH_URL = "https://api.spotify.com/v1/search"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET")
        self._http = httpx.Client(timeout=TIMEOUT, transport=transport)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _access_token(self) -> str:
        with self._lock:
            if self._token and self._token[1] > time.time() + 30:
                return self._token[0]
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            r = self._http.post(self.TOKEN_URL, data={"grant_type": "client_credentials"},
                                headers={"Authorization": f"Basic {basic}"})
            if r.status_code != 200:
                raise ProviderError(f"Spotify refused the credentials (HTTP {r.status_code})")
            body = r.json()
            self._token = (body["access_token"], time.time() + float(body.get("expires_in", 3600)))
            return self._token[0]

    def search(self, title: str, artist: str | None, limit: int = 10) -> list[dict]:
        q = f'track:"{title}"' + (f' artist:"{artist}"' if artist else "")
        r = self._http.get(self.SEARCH_URL, params={"q": q, "type": "track", "limit": limit},
                           headers={"Authorization": f"Bearer {self._access_token()}"})
        if r.status_code == 429:
            raise ProviderError("Spotify rate limit reached; try again shortly")
        if r.status_code != 200:
            raise ProviderError(f"Spotify search failed (HTTP {r.status_code})")
        out = []
        for t in r.json().get("tracks", {}).get("items", []):
            album = t.get("album") or {}
            year = (album.get("release_date") or "")[:4]
            out.append(_result(title=t["name"], artist=", ".join(a["name"] for a in t.get("artists", [])),
                               album=album.get("name"), year=int(year) if year.isdigit() else None,
                               duration_s=(t.get("duration_ms") or 0) / 1000 or None,
                               isrc=(t.get("external_ids") or {}).get("isrc"), provider="spotify",
                               provider_id=t["id"], url=(t.get("external_urls") or {}).get("spotify")))
        return out


# ---- YouTube (metadata only) ---------------------------------------------------------

_ISO_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration(text: str | None) -> float | None:
    m = _ISO_DURATION.fullmatch(text or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return float(((d * 24 + h) * 60 + mi) * 60 + s)


class YouTube:
    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
        self._http = httpx.Client(timeout=TIMEOUT, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, title: str, artist: str | None, limit: int = 6) -> list[dict]:
        q = f"{artist} {title}" if artist else title
        r = self._http.get(self.SEARCH_URL, params={"part": "snippet", "type": "video", "q": q,
                                                    "maxResults": limit, "key": self.api_key})
        if r.status_code in (400, 403):
            reason = (r.json().get("error", {}).get("errors") or [{}])[0].get("reason", "") if r.content else ""
            raise ProviderError(f"YouTube refused the request ({reason or r.status_code})")
        if r.status_code != 200:
            raise ProviderError(f"YouTube search failed (HTTP {r.status_code})")
        items = [i for i in r.json().get("items", []) if i.get("id", {}).get("videoId")]
        ids = [i["id"]["videoId"] for i in items]
        durations: dict[str, float | None] = {}
        if ids:
            v = self._http.get(self.VIDEOS_URL, params={"part": "contentDetails", "id": ",".join(ids),
                                                        "key": self.api_key})
            if v.status_code == 200:
                durations = {x["id"]: iso_duration(x.get("contentDetails", {}).get("duration"))
                             for x in v.json().get("items", [])}
        out = []
        for i in items:
            sn, vid = i.get("snippet", {}), i["id"]["videoId"]
            year = (sn.get("publishedAt") or "")[:4]
            res = _result(title=_unescape(sn.get("title", "")), artist=artist or sn.get("channelTitle", ""),
                          album=None, year=int(year) if year.isdigit() else None, duration_s=durations.get(vid),
                          provider="youtube", provider_id=vid, url=f"https://www.youtube.com/watch?v={vid}")
            res["channel"] = sn.get("channelTitle")
            out.append(res)
        return out


class ProviderError(RuntimeError):
    pass


def _unescape(text: str) -> str:
    import html
    return html.unescape(text)


def _short(text: str | None) -> str | None:
    return text[:200] if text else text


class Providers:
    """All configured providers, searched in parallel."""

    def __init__(self, spotify: Spotify | None = None, youtube: YouTube | None = None, public: bool = True):
        self.spotify = spotify or Spotify()
        self.youtube = youtube or YouTube()
        self.public = public and os.environ.get("DRUM_AGENT_PUBLIC_METADATA", "1") != "0"

    def status(self) -> list[dict]:
        return ([{"provider": n, "state": "enabled"} for n in lookup.SOURCES] if self.public else []) + [
            {"provider": "spotify", "state": "enabled" if self.spotify.configured else "not_configured"},
            {"provider": "youtube", "state": "enabled" if self.youtube.configured else "not_configured"},
        ]

    def search(self, text: str) -> tuple[list[dict], list[dict]]:
        title, artist = split_query(text)
        jobs = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            if self.public:
                jobs["public"] = pool.submit(search_public_metadata, title, artist)
            if self.spotify.configured:
                jobs["spotify"] = pool.submit(self.spotify.search, title, artist)
            if self.youtube.configured:
                jobs["youtube"] = pool.submit(self.youtube.search, title, artist)
            results, states = [], []
            for name, fut in jobs.items():
                try:
                    if name == "public":
                        found, st = fut.result()
                        results += found
                        states += st
                    else:
                        results += fut.result()
                        states.append({"provider": name, "state": "ok", "detail": None})
                except (ProviderError, httpx.HTTPError, ValueError, KeyError) as exc:
                    states.append({"provider": name, "state": "error", "detail": _short(str(exc) or type(exc).__name__)})
        for name, p in (("spotify", self.spotify), ("youtube", self.youtube)):
            if not p.configured:
                states.append({"provider": name, "state": "not_configured", "detail": None})
        return _dedupe(results), states


def _dedupe(results: list[dict]) -> list[dict]:
    seen, out = {}, []
    for r in results:
        if r["id"] in seen:
            prev = seen[r["id"]]
            prev["providers"] = sorted(set(prev["providers"]) | set(r["providers"]))
            continue
        seen[r["id"]] = r
        out.append(r)
    return out
