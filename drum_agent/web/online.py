"""Find a song's recording on YouTube and chart it, in the personal app.

In the Drum Agent app on the user's own computer, typing a song is enough: the app
searches YouTube for the identified recording (the search results' metadata only),
takes the upload that matches it best (`fetch.rank_videos`: title and artist, a
length within 10 % of the identified recording's, no live/cover/remix unless the
user asked for one, never a drumless backing track), downloads that video's audio
with yt-dlp into the app's cache, decodes it and charts it for the user's own
practice (rights basis `personal`: the chart says so and is not shared). The user
sees which video was used and can pick another.

This runs only in personal mode (`sources.personal_mode()`: one person, their own
computer) with yt-dlp installed (the desktop app ships it). A shared server never
fetches recordings from video sites: there a song needs an uploaded recording.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from ..song import fetch
from ..song.fetch import FetchError, VideoCandidate
from .sources import add_video, personal_mode
from .store import Store

SEARCH_RESULTS = 8
SEARCH_TIMEOUT_S = 60


def status() -> dict:
    """Can songs be found online here? {"available", "reason", "detail"}."""
    if not personal_mode():
        return {"available": False, "reason": "shared_server",
                "detail": "This is a shared server: it never fetches recordings from video sites. Get the Drum "
                          "Agent app to chart a song from its name, or upload a recording you have the right to "
                          "transcribe."}
    if fetch.find_ytdlp() is None:
        return {"available": False, "reason": "no_ytdlp", "detail": fetch.YTDLP_MISSING}
    return {"available": True, "reason": None, "detail": "YouTube, through yt-dlp on this computer"}


def search_query(song: dict) -> str:
    return f"{song['artist']} {song['title']}".strip()


def _asked(song: dict) -> str:
    """The user's own words about the version: a "live" or "remix" in them lets such uploads rank."""
    return " ".join(x for x in (song["title"], song["artist"], song.get("version") or "") if x)


def candidates(song: dict, n: int = SEARCH_RESULTS) -> list[VideoCandidate]:
    """Ranked uploads of this song, best first (metadata only; nothing is downloaded)."""
    return fetch.search_videos(search_query(song), n, song.get("duration_s"), asked=_asked(song), flat=True,
                               artist=song["artist"], timeout=SEARCH_TIMEOUT_S)


def public(v: VideoCandidate, expected_s: float | None) -> dict:
    off = round(abs(v.duration_s - expected_s) / expected_s, 3) if expected_s and v.duration_s else None
    return {"url": v.url, "id": v.id, "title": v.title, "channel": v.channel or v.uploader,
            "duration_s": v.duration_s, "score": v.score, "length_off": off,
            "length_ok": off is None or off <= fetch.DURATION_TOLERANCE}


def chosen(video: dict) -> VideoCandidate:
    """A video the user picked (a search result, or a link they pasted): a page on a known video site."""
    url = str(video.get("url") or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not fetch.is_video_page(url):
        raise FetchError("that is not a link to a video page (YouTube, Vimeo, SoundCloud, Bandcamp...)")
    fetch.refuse_streaming(url)
    duration = video.get("duration_s")
    return VideoCandidate(url=url, title=str(video.get("title") or url)[:300], id=video.get("id"),
                          channel=video.get("channel"), uploader=video.get("channel"),
                          duration_s=float(duration) if isinstance(duration, (int, float)) else None)


def fetch_source(store: Store, song: dict, video: VideoCandidate) -> dict:
    """Download the video's audio, decode it into the song's source (personal basis), drop the download."""
    for s in store.sources_for(song["id"]):  # this video was fetched before: no second download
        if s["kind"] == "video" and video.id and (s["info"].get("video") or {}).get("id") == video.id \
                and Path(s["path"]).is_file():
            return s
    audio = fetch.download_with_ytdlp(video.url, store.root / "downloads", info=video)
    try:
        return add_video(store, song, audio.path, {"url": video.url, "id": video.id, "title": video.title,
                                                   "channel": video.channel or video.uploader,
                                                   "duration_s": video.duration_s})
    finally:
        audio.path.unlink(missing_ok=True)  # the decoded copy is the source; the download isn't kept
