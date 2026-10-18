"""Identify a song from what the user typed, using public metadata services.

`search_metadata` asks MusicBrainz (WS2 JSON), the iTunes Search API and
Deezer what a typed song name could be, merges the answers that describe the
same recording and ranks them. It is metadata only: title, artist, album,
year, duration, ISRC, BPM and the services' pages. No audio is ever requested
here; finding audio the user may use is `local.py` and `fetch.py`.

Services fail in ordinary ways (offline, rate limits, a changed API), so a
failing source becomes a warning on the result, and only all of them failing
is an error. The text helpers here (`text_key`, `similarity`,
`version_penalty`) are shared with the library and video search so that one
notion of "the same song" applies everywhere.
"""

from __future__ import annotations

import difflib
import http.client
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

USER_AGENT = "drum-agent/1.0 (https://github.com/urigrossman1-netizen/drum-agent)"
MAX_JSON_BYTES = 2 * 1024 * 1024  # a search answer is a few kB; anything this big is not one
RESULTS_PER_SOURCE = 10
DEEZER_TRACK_LOOKUPS = 3  # /track/<id> calls for BPM and ISRC, best search hits only

MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/recording/"
ITUNES_URL = "https://itunes.apple.com/search"
DEEZER_SEARCH_URL = "https://api.deezer.com/search"
DEEZER_TRACK_URL = "https://api.deezer.com/track/"

SOURCE_NAMES = {"musicbrainz": "MusicBrainz", "itunes": "iTunes", "deezer": "Deezer"}

# Words that mark another version of a song. A candidate titled with one ranks
# lower unless the user asked for it ("... live").
OTHER_VERSION_WORDS = ("live", "remix", "karaoke", "cover", "tribute", "instrumental", "acoustic", "demo",
                       "made famous by", "originally performed", "in the style of")
# The same in an artist name ("Karaoke Band", "Tribute Players"): a re-recording by someone else.
OTHER_ARTIST_WORDS = ("karaoke", "tribute", "cover", "made famous by", "originally performed", "in the style of")


class MetadataError(RuntimeError):
    """A metadata source (or all of them) could not answer."""


class Results(list):
    """A list that also carries the warnings collected while filling it.

    One failing source or a truncated scan is worth telling the user about,
    but not worth an exception that would throw the other answers away.
    """

    def __init__(self, items=(), warnings: list[str] | None = None):
        super().__init__(items)
        self.warnings: list[str] = list(warnings or [])


@dataclass
class SongCandidate:
    title: str
    artist: str
    album: str | None = None
    year: int | None = None
    duration_s: float | None = None
    isrc: str | None = None
    bpm: float | None = None  # Deezer's value when it has one; a hint, never applied unasked
    sources: list[str] = field(default_factory=list)  # "musicbrainz", "itunes", "deezer"
    urls: dict[str, str] = field(default_factory=dict)  # source -> the service's page for it
    score: float = 0.0  # match quality plus agreement between sources (set by rank)

    @property
    def key(self) -> tuple[str, str]:
        return title_key(self.title), artist_key(self.artist)

    def absorb(self, other: "SongCandidate") -> None:
        """Merge another service's answer for the same recording into this one."""
        for s in other.sources:
            if s not in self.sources:
                self.sources.append(s)
        for s, u in other.urls.items():
            self.urls.setdefault(s, u)
        if len(other.title) < len(self.title):
            self.title = other.title  # "Song" rather than "Song (2023 Remaster)": the name, not a release
        if other.year and (not self.year or other.year < self.year):
            self.year = other.year  # the earliest release is the original, and so is its album
            self.album = other.album or self.album
        self.album = self.album or other.album
        self.duration_s = self.duration_s or other.duration_s
        self.isrc = self.isrc or other.isrc
        self.bpm = self.bpm or other.bpm

    def describe(self) -> str:
        parts = [f"{self.title} - {self.artist}"]
        extra = ", ".join(str(x) for x in (self.album, self.year) if x)
        if extra:
            parts[0] += f" ({extra})"
        if self.duration_s:
            parts.append(format_duration(self.duration_s))
        if self.bpm:
            parts.append(f"{self.bpm:g} BPM")
        if self.isrc:
            parts.append(f"ISRC {self.isrc}")
        parts.append("sources: " + ", ".join(SOURCE_NAMES.get(s, s) for s in self.sources))
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = {"title": self.title, "artist": self.artist, "album": self.album, "year": self.year,
             "duration_s": self.duration_s, "isrc": self.isrc, "bpm": self.bpm,
             "sources": list(self.sources), "urls": dict(self.urls)}
        return {k: v for k, v in d.items() if v not in (None, [], {})}


# ---- text helpers (shared with local.py and fetch.py) ---------------------------------

def text_key(text: str | None) -> str:
    """Lower case, accents and punctuation removed, spaces collapsed: "Café-Noir!" -> "cafe noir"."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", t).replace("_", " ").split())


# Parts of a title that name the same performance (a remaster is the same take);
# "live", "remix", "edit" stay: those are other versions.
_SAME_TAKE = re.compile(r"\s*[(\[]\s*(?:[^)\]]*\b(?:remaster(?:ed)?|feat\.?|ft\.?|featuring|mono|stereo|explicit|"
                        r"clean|album version|single version|original version)\b[^)\]]*)[)\]]"
                        r"|\s+-\s+(?:\d{4}\s+)?(?:remaster(?:ed)?|mono|stereo|single version|album version)\b.*$",
                        re.IGNORECASE)


def title_key(title: str | None) -> str:
    return text_key(_SAME_TAKE.sub("", title or ""))


def artist_key(artist: str | None) -> str:
    """The primary artist only, so "A feat. B" (MusicBrainz) and "A & B" (iTunes) agree."""
    full = text_key(artist)
    t = re.split(r"\b(?:feat|ft|featuring|with|and|x)\b", full)[0].strip() or full
    return t[4:] if t.startswith("the ") else t


def similarity(a: str | None, b: str | None) -> float:
    """0..1: half character similarity, half word overlap (so word order and extra words cost less)."""
    ka, kb = text_key(a), text_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    seq = difflib.SequenceMatcher(None, ka, kb).ratio()
    wa, wb = set(ka.split()), set(kb.split())
    f1 = 2 * len(wa & wb) / (len(wa) + len(wb))
    return 0.5 * seq + 0.5 * f1


def version_penalty(text: str | None, asked: str, words=OTHER_VERSION_WORDS, per_word: float = 0.25) -> float:
    """Penalty for words in `text` that mark another version, unless the user's own words contain them."""
    t, q = f" {text_key(text)} ", f" {text_key(asked)} "
    hits = [w for w in words if f" {text_key(w)} " in t and f" {text_key(w)} " not in q]
    return per_word * len(hits)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?:??"
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ---- HTTP -----------------------------------------------------------------------------

def open_url(url: str, timeout: float, headers: dict[str, str] | None = None,
             refuse: Callable[[str], None] | None = None):
    """GET `url` with our User-Agent. Only http(s); proxies come from the environment
    (http_proxy, https_proxy, no_proxy) through urllib's default ProxyHandler. `refuse(url)`
    is called on every redirect target before it is requested, and may raise to stop there."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise MetadataError(f"only http(s) URLs are fetched, not {scheme or 'a bare path'!r}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.build_opener(_HttpOnlyRedirects(refuse)).open(req, timeout=timeout)


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects to http(s) only: urllib's default also follows ftp:// (and would
    log in to an FTP server named by whoever answers the first request)."""

    def __init__(self, refuse: Callable[[str], None] | None = None):
        super().__init__()
        self.refuse = refuse

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlsplit(newurl).scheme.lower()
        if scheme not in ("http", "https"):
            raise urllib.error.HTTPError(newurl, code, f"redirect to a {scheme or 'bare'} URL refused", headers, fp)
        if self.refuse is not None:
            self.refuse(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get_json(url: str, timeout: float = 8, max_bytes: int = MAX_JSON_BYTES) -> Any:
    """The one HTTP helper of the metadata search: JSON from `url`, size-capped, with every
    network failure turned into a MetadataError that names the host."""
    host = urllib.parse.urlsplit(url).hostname or url
    try:
        with open_url(url, timeout, {"Accept": "application/json"}) as resp:
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise MetadataError(f"{host} answered HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise MetadataError(f"can't reach {host}: {exc.reason}") from None
    except (OSError, http.client.HTTPException) as exc:  # timeouts, resets, truncated answers
        raise MetadataError(f"can't read from {host}: {exc or type(exc).__name__}") from None
    if len(data) > max_bytes:
        raise MetadataError(f"{host} sent more than {max_bytes} bytes; not a search answer")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MetadataError(f"{host} did not answer with JSON") from None


def _get(url: str, params: dict[str, Any], timeout: float) -> Any:
    # Looked up at call time, so tests can replace http_get_json with canned answers.
    return http_get_json(url + "?" + urllib.parse.urlencode(params), timeout)


# ---- the three services ---------------------------------------------------------------

def _lucene(text: str) -> str:
    """Escape a phrase for a Lucene query (MusicBrainz search syntax)."""
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", text)


def _year(date: Any) -> int | None:
    m = re.match(r"(\d{4})", str(date or ""))
    return int(m.group(1)) if m else None


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None  # 0 means "unknown" in these APIs (Deezer's bpm, missing lengths)


def search_musicbrainz(query: str, artist: str | None, timeout: float) -> list[SongCandidate]:
    if artist:
        q = f'recording:"{_lucene(query)}" AND artist:"{_lucene(artist)}"'
    else:
        q = _lucene(query)
    data = _get(MUSICBRAINZ_URL, {"query": q, "fmt": "json", "limit": RESULTS_PER_SOURCE}, timeout)
    out = []
    for rec in (data or {}).get("recordings") or []:
        if not isinstance(rec, dict) or not rec.get("title"):
            continue
        credit = rec.get("artist-credit") or []
        name = "".join(str(c.get("name", "")) + str(c.get("joinphrase", "")) for c in credit
                       if isinstance(c, dict)).strip()
        releases = [r for r in rec.get("releases") or [] if isinstance(r, dict)]
        years = [y for y in (_year(r.get("date")) for r in releases) if y]
        year = _year(rec.get("first-release-date")) or (min(years) if years else None)
        isrcs = rec.get("isrcs") or []
        length = _num(rec.get("length"))
        out.append(SongCandidate(
            title=rec["title"], artist=name or "?", album=releases[0].get("title") if releases else None,
            year=year, duration_s=round(length / 1000, 1) if length else None,
            isrc=str(isrcs[0]) if isrcs else None, sources=["musicbrainz"],
            urls={"musicbrainz": f"https://musicbrainz.org/recording/{rec.get('id')}"} if rec.get("id") else {}))
    return out


def search_itunes(query: str, artist: str | None, timeout: float) -> list[SongCandidate]:
    term = f"{artist} {query}" if artist else query
    data = _get(ITUNES_URL, {"term": term, "entity": "song", "media": "music", "limit": RESULTS_PER_SOURCE},
                timeout)
    out = []
    for r in (data or {}).get("results") or []:
        if not isinstance(r, dict) or not r.get("trackName") or r.get("kind", "song") != "song":
            continue
        ms = _num(r.get("trackTimeMillis"))
        out.append(SongCandidate(
            title=r["trackName"], artist=r.get("artistName") or "?", album=r.get("collectionName"),
            year=_year(r.get("releaseDate")), duration_s=round(ms / 1000, 1) if ms else None,
            sources=["itunes"], urls={"itunes": r["trackViewUrl"]} if r.get("trackViewUrl") else {}))
    return out


def _deezer_json(url: str, params: dict[str, Any], timeout: float) -> dict:
    data = _get(url, params, timeout) if params else http_get_json(url, timeout)
    if isinstance(data, dict) and data.get("error"):  # Deezer reports errors (quota...) with HTTP 200
        err = data["error"]
        raise MetadataError(f"Deezer: {err.get('message') or err}" if isinstance(err, dict) else f"Deezer: {err}")
    return data if isinstance(data, dict) else {}


def search_deezer(query: str, artist: str | None, timeout: float,
                  warnings: list[str] | None = None) -> list[SongCandidate]:
    q = f'artist:"{artist}" track:"{query}"' if artist else query
    data = _deezer_json(DEEZER_SEARCH_URL, {"q": q, "limit": RESULTS_PER_SOURCE}, timeout)
    found: list[tuple[SongCandidate, str]] = []
    for r in data.get("data") or []:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        c = SongCandidate(
            title=r["title"], artist=(r.get("artist") or {}).get("name") or "?",
            album=(r.get("album") or {}).get("title"), duration_s=_num(r.get("duration")),
            sources=["deezer"], urls={"deezer": r["link"]} if r.get("link") else {})
        found.append((c, str(r.get("id", ""))))
    # BPM, ISRC and the release date are only on the track resource: ask for the best few.
    best = sorted(found, key=lambda ct: -_match_quality(query, artist, ct[0]))[:DEEZER_TRACK_LOOKUPS]
    for c, tid in best:
        if not tid.isdigit():
            continue
        try:
            t = _deezer_json(DEEZER_TRACK_URL + tid, {}, timeout)
        except MetadataError as exc:
            if warnings is not None:
                warnings.append(f"Deezer track {tid}: {exc}")
            continue
        c.bpm = _num(t.get("bpm"))
        c.isrc = t.get("isrc") or None
        c.year = _year(t.get("release_date"))
        c.duration_s = _num(t.get("duration")) or c.duration_s
    return [c for c, _ in found]


SOURCES: dict[str, Callable[..., list[SongCandidate]]] = {
    "musicbrainz": search_musicbrainz,
    "itunes": search_itunes,
    "deezer": search_deezer,
}


# ---- merge and rank -------------------------------------------------------------------

def _same_length(a: float | None, b: float | None) -> bool:
    """Services round lengths differently; a remaster may differ by a second or two."""
    if a is None or b is None:
        return True
    return abs(a - b) <= max(4.0, 0.03 * max(a, b))


def merge_candidates(cands: list[SongCandidate]) -> list[SongCandidate]:
    """One candidate per recording: same normalised title and primary artist, and a length that agrees."""
    merged: list[SongCandidate] = []
    for c in cands:
        for m in merged:
            if m.key == c.key and _same_length(m.duration_s, c.duration_s):
                m.absorb(c)
                break
        else:
            merged.append(SongCandidate(c.title, c.artist, c.album, c.year, c.duration_s, c.isrc, c.bpm,
                                        list(c.sources), dict(c.urls)))
    return merged


def _match_quality(query: str, artist: str | None, c: SongCandidate) -> float:
    title = max(similarity(query, c.title), similarity(query, title_key(c.title)))
    if artist:
        who = max(similarity(artist, c.artist), similarity(artist_key(artist), artist_key(c.artist)))
        return 0.6 * title + 0.4 * who
    # Without --artist the query often holds the artist too: "title artist" or "artist - title".
    return max(title, similarity(query, f"{c.title} {c.artist}"), similarity(query, f"{c.artist} {c.title}"))


def rank(cands: list[SongCandidate], query: str, artist: str | None = None) -> list[SongCandidate]:
    """Best first: how well title (and artist) match, plus a bonus when services agree."""
    asked = f"{query} {artist or ''}"
    for c in cands:
        agree = 0.08 * (len(set(c.sources)) - 1)
        penalty = (version_penalty(c.title, asked) + version_penalty(c.album, asked, per_word=0.1)
                   + version_penalty(c.artist, asked, OTHER_ARTIST_WORDS))
        c.score = round(_match_quality(query, artist, c) + agree + (0.02 if c.isrc else 0.0) - penalty, 3)
    return sorted(cands, key=lambda c: (-c.score, -(c.year is not None), c.year or 0))


def search_metadata(query: str, artist: str | None = None, timeout: float = 8,
                    sources: tuple[str, ...] = tuple(SOURCES)) -> Results:
    """Ranked SongCandidates for `query` from MusicBrainz, iTunes and Deezer (metadata only).

    The result is a list with a `.warnings` attribute naming every source that
    failed. Raises MetadataError only when no source answered at all.
    """
    query = " ".join(query.split())
    if not query:
        raise MetadataError("empty song name")
    warnings: list[str] = []

    def ask(name: str) -> list[SongCandidate]:
        fn = SOURCES[name]
        return fn(query, artist, timeout, warnings) if name == "deezer" else fn(query, artist, timeout)

    found: list[SongCandidate] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        futures = {name: pool.submit(ask, name) for name in sources}
        for name, fut in futures.items():
            try:
                found += fut.result()
            except MetadataError as exc:
                failed += 1
                warnings.append(f"{SOURCE_NAMES.get(name, name)}: {exc}")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:  # an answer of another shape
                failed += 1
                warnings.append(f"{SOURCE_NAMES.get(name, name)}: unexpected answer ({exc})")
    if sources and failed == len(sources):
        raise MetadataError("no metadata source answered: " + "; ".join(warnings))
    return Results(rank(merge_candidates(found), query, artist), warnings)
