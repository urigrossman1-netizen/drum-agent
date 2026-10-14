"""From a song's name to audio the user may use (`python -m drum_agent song`).

* `lookup`: identify the song from public metadata (MusicBrainz, iTunes,
  Deezer). Metadata only; no audio is requested.
* `local`: find it among the user's own audio files (tags or file names).
* `fetch`: get the audio file: a local file in place, a direct link to an
  audio file, or a video page through the user's own yt-dlp. DRM streaming
  services are refused.
* `run`: the `song` command: identify, choose the audio, check its length,
  then the analysis, or with --rights (checked before any download for
  transcription) the transcription.

Finding audio is not permission to transcribe it: `drum_agent.rights` decides that.
"""

from .fetch import AudioSource, FetchError, fetch_audio
from .local import LocalMatch, find_local
from .lookup import MetadataError, SongCandidate, search_metadata

__all__ = ["AudioSource", "FetchError", "LocalMatch", "MetadataError", "SongCandidate", "fetch_audio",
           "find_local", "search_metadata"]
