"""What every request passes before its route: the checks that don't belong to any one route.

An ASGI middleware, so it can refuse a request without reading its body:

- **Host** (personal mode). The app answers only to this computer's own names. Otherwise a web
  page could point a domain of its own at 127.0.0.1 (DNS rebinding) and read the user's charts
  and the list of their music files.
- **Size.** A body over the limit is refused by its Content-Length, or, when it declares none
  or lies, the moment it passes the limit on the way in. Nothing past the limit reaches a disk.
- **Cross-site writes.** A write must carry the X-Drum-Agent header. A page on another site can't
  add it without the browser asking the server first, and this server never agrees, so a
  site the user visits can't use the app behind their back.
- **Rate limits** (shared servers). Token buckets on what costs money or minutes of CPU, for each
  visitor and for each address: dropping the cookie makes a new visitor, not a new address. One
  address can hold many visitors (a household, or everyone behind a proxy), so it gets more
  room. Behind a proxy every visitor shares the proxy's address unless uvicorn is told to
  trust it (FORWARDED_ALLOW_IPS): the limit then works as one for the whole server, which
  slows a busy site and never lets the bill run away. On their own computer one person has
  nobody to share with, so nothing is limited there.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..audio.prepare import MAX_BYTES
from . import owners, sources

WRITE_HEADER = b"x-drum-agent"  # any value: that it can be sent at all is the proof
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOCAL_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})
MAX_BODY = 16 * 2**20  # a 20-minute chart is about 2 MB
MULTIPART_SLACK = 2**20  # the form's other fields and boundaries, around the file
UPLOAD = re.compile(r"/api/songs/[^/]+/upload")
ADDRESS_FACTOR = 5  # how much more an address may do than one visitor
MAX_TRACKED = 50_000  # buckets kept before the idle ones are forgotten
IDLE_S = 3600  # every bucket below is full again by then
PRUNE_EVERY_S = 60


@dataclass(frozen=True)
class Limit:
    burst: int  # requests that can come at once
    per_hour: float  # the rate that can be kept up


LIMITS = {
    "claude": Limit(5, 20),  # each one is paid for
    "words": Limit(20, 120),  # a typed edit: rules first, Claude only for what they can't read
    "search": Limit(10, 120),  # other services' quotas
    "jobs": Limit(10, 30),  # minutes of CPU each
    "save": Limit(20, 120),  # a full engraving each
    "preview": Limit(30, 3600),  # an engraving each, up to about one a second while editing
    "listen": Limit(30, 240),  # FFmpeg, the first time at a speed
}
ROUTES = tuple((method, re.compile(path), name) for method, path, name in (
    ("POST", r"/api/charts/[^/]+/(suggest-sections|explain)", "claude"),
    ("POST", r"/api/beats/command", "words"),
    ("GET", r"/api/search", "search"),
    ("POST", r"/api/songs/[^/]+/(upload|jobs|use-asset|library)", "jobs"),
    ("POST", r"/api/jobs/[^/]+/retry", "jobs"),
    ("POST", r"/api/beats", "jobs"),
    ("POST", r"/api/projects/[^/]+/(versions|duplicate)", "save"),
    ("POST", r"/api/charts/[^/]+/(sections|rechart|simplify|review|restore)", "save"),
    ("POST", r"/api/preview", "preview"),
    ("GET", r"/api/charts/[^/]+/listen", "listen"),
))


def bucket_for(method: str, path: str) -> str | None:
    return next((name for m, pattern, name in ROUTES if m == method and pattern.fullmatch(path)), None)


class Buckets:
    """Token buckets: a request takes a token from each of its buckets, and tokens come back at the
    limit's rate. If any bucket is empty, nothing is taken."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state: dict[tuple, tuple[float, float]] = {}  # key -> (tokens, when they were counted)
        self.pruned = clock()

    def take(self, limit: Limit, keys: list[tuple[tuple, int]]) -> float:
        """0 if the request may go, else the seconds to wait. `keys`: (bucket, how many times the limit)."""
        now = self.clock()
        levels = []
        for key, scale in keys:
            room, rate = limit.burst * scale, limit.per_hour * scale / 3600
            tokens, then = self.state.get(key, (room, now))
            levels.append((key, min(room, tokens + (now - then) * rate), rate))
        wait = max((1 - tokens) / rate if tokens < 1 else 0.0 for _, tokens, rate in levels)
        if wait > 0:
            return wait
        for key, tokens, _ in levels:
            self.state[key] = (tokens - 1, now)
        if len(self.state) > MAX_TRACKED and now - self.pruned > PRUNE_EVERY_S:
            self.pruned = now
            self.state = {k: v for k, v in self.state.items() if now - v[1] < IDLE_S}
        return 0.0


def hostname(header: bytes | None) -> str:
    """The name in a Host header, without its port: "[::1]:8000" -> "[::1]"."""
    text = (header or b"").decode("latin-1").strip().lower()
    if text.startswith("[") and "]" in text:
        return text[:text.index("]") + 1]
    return text.split(":")[0]


def _too_large(limit: int) -> str:
    return f"That's too much to send: the limit is {limit / 2**20:.0f} MB."


def _refuse(status: int, code: str, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status, headers=headers)


class Guard:
    def __init__(self, app):
        self.app = app
        self.buckets = Buckets()

    def refusal(self, scope: dict, limit: int) -> JSONResponse | None:
        method, path, personal = scope["method"], scope["path"], sources.personal_mode()
        headers = dict(scope["headers"])
        if personal and hostname(headers.get(b"host")) not in LOCAL_NAMES:
            return _refuse(403, "bad_host", "This app answers only on this computer's own address.")
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            return _refuse(413, "too_large", _too_large(limit))
        if method in WRITES and WRITE_HEADER not in headers:
            return _refuse(403, "cross_site", "This request didn't come from the studio's own page, so it was refused.")
        name = None if personal else bucket_for(method, path)
        if name is None:
            return None
        client = scope.get("client") or ("unknown",)
        wait = self.buckets.take(LIMITS[name], [(("visitor", name, owners.current()), 1),
                                                (("address", name, client[0]), ADDRESS_FACTOR)])
        if not wait:
            return None
        seconds = int(wait) + 1
        when = f"{seconds} seconds" if seconds < 120 else f"{seconds // 60 + 1} minutes"
        return _refuse(429, "rate_limited", f"That's a lot in a short time. Try again in about {when}.",
                       {"Retry-After": str(seconds)})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = MAX_BYTES + MULTIPART_SLACK if UPLOAD.fullmatch(scope["path"]) else MAX_BODY
        refused = self.refusal(scope, limit)
        if refused is not None:
            await refused(scope, receive, send)
            return
        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(413, _too_large(limit))  # the route answers it, as it reads the body
            return message

        await self.app(scope, counted, send)
