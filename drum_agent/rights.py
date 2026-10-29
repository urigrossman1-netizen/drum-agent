"""Permission gate for note-for-note transcription of recordings.

Full transcription reproduces a performance in detail, so it needs a stated basis:
the user owns the recording, has the rights holder's permission, has a licence, it
is in the public domain, it is their own composition, or (`personal`) the chart is
for their own practice and is not shared. Without a basis, only high-level analysis
(`python -m drum_agent analyze`: tempo, meter, sections) is offered. The basis is
the user's statement; the agent never picks one for them.

`personal` is accepted only where one person uses the tool on their own computer:
the command line, and the web app in personal mode (the desktop app). A shared
server, where every visitor sees the same library, never accepts it. A personal
chart carries "Transcribed for personal practice. Not for distribution." and is
never shared or published by the app (`shareable`).

The agent never circumvents DRM and never takes audio from streaming services
(Spotify, Apple Music, Tidal, Deezer, Amazon Music: metadata only). Audio comes
from the user's own files, a direct link, or a video page fetched with yt-dlp on
the user's own computer (`song`, and the desktop app), and this gate runs before
any audio is fetched or opened for transcription.
"""

from __future__ import annotations

from .model import RIGHTS

PERSONAL = "personal"
SHAREABLE = frozenset(k for k in RIGHTS if k != PERSONAL)


class RightsError(PermissionError):
    pass


def require_rights(rights: str | None, source: str, *, personal_ok: bool = True) -> None:
    """Raise unless `rights` is a basis this context accepts (`personal_ok`: one user, their own computer)."""
    if rights in RIGHTS and (personal_ok or rights != PERSONAL):
        return
    if rights == PERSONAL:
        raise RightsError(
            f"{source!r}: \"for my own practice\" is accepted only in the Drum Agent app on your own computer, "
            f"where the chart stays with you. On a shared server every visitor sees the library, so use one of: "
            f"own, permission, licensed, public_domain, original.")
    raise RightsError(
        f"Full transcription of {source!r} needs a rights basis. Re-run with --rights and one of: "
        f"own (you made or own the recording), permission (the rights holder allowed it), "
        f"licensed (a licence covers transcription), public_domain, original (your own composition), "
        f"personal (for your own practice; the chart is not shared). "
        f"Otherwise use `python -m drum_agent analyze` for tempo/meter/structure only, or get a "
        f"licensed chart from the publisher."
    )


def shareable(rights: str | None) -> bool:
    """May the app share or publish a chart made on this basis? Not a personal-practice chart."""
    return rights in SHAREABLE
