"""Permission gate for note-for-note transcription of recordings.

Full transcription reproduces a performance in detail, so it is limited to
material the user owns, has permission to transcribe, has licensed, or that
is in the public domain. Without one of those, only high-level analysis
(`drum-agent analyze`: tempo, meter, sections) is offered. The agent never
downloads audio from streaming services or circumvents DRM; it works only on
files the user supplies.
"""

from __future__ import annotations

from .model import RIGHTS


class RightsError(PermissionError):
    pass


def require_rights(rights: str | None, source: str) -> None:
    if rights in RIGHTS:
        return
    raise RightsError(
        f"Full transcription of {source!r} needs a rights basis. Re-run with "
        f"--rights {{{', '.join(sorted(RIGHTS))}}} if you own the recording, have the rights "
        f"holder's permission, have licensed it, or it is in the public domain. Otherwise use "
        f"`drum-agent analyze` for tempo/meter/structure only, or get a licensed chart from the publisher."
    )
