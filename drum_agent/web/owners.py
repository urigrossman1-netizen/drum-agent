"""Whose project is it: a private workspace for every visitor of a shared server.

A shared server (the default `serve`) has no accounts. Each browser gets a random owner
token in a cookie on its first request (HttpOnly, SameSite=Lax, a year), and everything it
creates belongs to it: its songs and beats, their uploads, jobs and chart versions. Lists,
the search's catalog and every lookup show a visitor only their own projects and the
examples the operator seeded, which have no owner: anyone can open, play and print those;
nobody can change them (a copy, "Duplicate", is the visitor's own). Clearing the browser's
cookies loses the workspace; nothing else identifies a visitor.

Song ids are scoped too: a catalog id (from an ISRC, a provider's track id, or the title and
artist) becomes the owner's own id, so two visitors charting the same song never share a
project, its upload or its chart.

In personal mode (one person, their own computer) there is no owner: nothing is scoped.
"""

from __future__ import annotations

import contextvars
import hashlib
import re
import secrets

from fastapi import HTTPException

COOKIE = "drum_agent_owner"
MAX_AGE_S = 365 * 24 * 3600
_TOKEN = re.compile(r"[0-9a-f]{32}")
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("drum_agent_owner", default=None)


def current() -> str | None:
    """This request's owner; None in personal mode (and outside requests: the job runner)."""
    return _current.get()


def enter(owner: str | None) -> contextvars.Token:
    return _current.set(owner)


def leave(token: contextvars.Token) -> None:
    _current.reset(token)


def new_token() -> str:
    return secrets.token_hex(16)


def valid(token: str | None) -> bool:
    return bool(token and _TOKEN.fullmatch(token))


def scoped_id(song_id: str, owner: str | None = None) -> str:
    """The owner's own id for a catalog song id (the id itself when nobody is scoped)."""
    owner = current() if owner is None else owner
    if owner is None:
        return song_id
    return "s_" + hashlib.sha1(f"{owner}|{song_id}".encode()).hexdigest()[:16]


def visible(song: dict | None) -> bool:
    """May this request see the song (and its sources, jobs and charts)?"""
    owner = current()
    return song is not None and (owner is None or song.get("owner") in (None, owner))


def require_writable(song: dict) -> None:
    """May this request change the song? Examples (no owner) are read-only on a shared server."""
    owner = current()
    if owner is not None and song.get("owner") != owner:
        raise HTTPException(403, "this is an example, read-only here: duplicate it to make your own copy")
