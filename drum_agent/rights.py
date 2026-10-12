"""Permission gate for note-for-note transcription of recordings.

Full transcription reproduces a performance in detail, so it is limited to
material the user owns, has permission to transcribe, has licensed, or that
is in the public domain. Without one of those, only high-level analysis
(`python -m drum_agent analyze`: tempo, meter, sections) is offered. The agent never
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
        f"Full transcription of {source!r} needs a rights basis. Re-run with --rights and one of: "
        f"own (you made or own the recording), permission (the rights holder allowed it), "
        f"licensed (a licence covers transcription), public_domain, original (your own composition). "
        f"Otherwise use `python -m drum_agent analyze` for tempo/meter/structure only, or get a "
        f"licensed chart from the publisher."
    )
