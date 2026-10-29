# Song lookup: `python -m drum_agent song`

"Give it a song name": `song` identifies the song, finds audio you may use,
and hands it to the existing analysis, or, with `--rights`, to the
transcription. The code is in `drum_agent/song/`.

```bash
# Identify, find audio, analyse (tempo, meter, sections; no notes)
python -m drum_agent song "Song Title" --artist "Band"

# Your own file, used where it is
python -m drum_agent song "Song Title" --artist "Band" --audio ~/Bounces/take3.wav --rights own -o out/song

# Your music folders only, no network at all: list what matches (and analyse the best),
# then transcribe the file you name by its number in that list
python -m drum_agent song "Song Title" --no-online --library ~/Bounces
python -m drum_agent song "Song Title" --no-online --library ~/Bounces --pick 2 --rights own -o out/song

# A direct link to an audio file you may use, with transcription hints
python -m drum_agent song "Song Title" --url https://example.com/audio/take.flac --rights permission -o out/song --bpm 96 --drums-only

# A file you bought, and the metadata BPM as the tempo hint
python -m drum_agent song "Song Title" --artist "Band" --audio "~/Music/Band - Song Title.m4a" --use-metadata-bpm --rights licensed -o out/song
```

It takes every transcription hint that `transcribe` takes (`--bpm`,
`--time-signature`, `--downbeat`, `--drums-only`, `--sections`, `--start`,
`--end`, `--sensitivity`, `--feel`, `--no-32nds`, `--chart-type`) and the
usual export options (`--formats`, `--paper`, `--stem`, `--voicing`, ...).

## The four steps

Each step is printed as it happens.

1. **Identify.** MusicBrainz (WS2 JSON recording search), the iTunes Search
   API (`entity=song`) and Deezer (search, then `/track/<id>` for BPM and ISRC)
   are asked at the same time. Answers that describe the same recording
   (same normalised title and primary artist, lengths within 4 s or 3 %) are
   merged; candidates are ranked by how well title and artist match, plus a
   bonus when services agree. Live, remix, karaoke and tribute versions rank
   lower unless you asked for them. A failing service is a warning; only all
   three failing means "not identified", and the command goes on without it.
   This step is metadata only: no audio is requested.
2. **Choose the audio**, in this order:
   * `--audio FILE`: your file, used in place, never copied or modified;
   * `--url URL`: a direct link to an audio file (a web page is refused, and so
     is a page on a video site: their official interfaces give links and
     players, not audio to analyse, and Drum Agent doesn't extract it);
   * your library: audio files under `~/Music` and `DRUM_AGENT_MUSIC_DIRS`
     (or the `--library` folders), matched by their tags (read with
     ffprobe) or their names (`Artist - Title.flac`, `Artist/Album/03 Title.mp3`).
     Nothing found there is an error that says what to give instead.

   The candidates are listed with where they come from; the best is used,
   `--pick N` takes another. Live takes and remixes rank after the plain
   recording unless your own words ask for them. With `--rights`, a search
   result is never chosen for you, even when it is the only match (a basis is
   a statement about one recording, and the first or only match can be
   another band's live take): name the file your basis covers with
   `--pick N`, its number in the list, or give it with `--audio`.
3. **Check the length** against the identified recording. More than 10 % off
   prints a warning: it may be another version (live, edit, remix) or another
   song.
4. **Analyse or transcribe:**
   * **without `--rights`**: the existing high-level analysis only (tempo,
     meter, sections; no notes, no chart files), then how to go on: state a
     basis with `--rights own|permission|licensed|public_domain|original`, or
     get a licensed chart. If a downloaded file's source states a Creative
     Commons or public-domain licence, that is said with the `--rights` value
     it would suggest. It is never applied: whether the publisher owned the
     recording, and whether the licence covers a transcription, is yours to
     check (a NoDerivatives licence doesn't).
   * **with `--rights`**: `drum_agent.rights.require_rights` runs first,
     before anything is downloaded or opened for transcription, then the same
     path as `transcribe`. The chart's title and artist are what you typed
     (QUERY and `--artist`, or `--title`). The score records a precise source
     (file path, or URL with its stated licence) and puts the identified
     metadata in `analysis.identified_as`. The metadata BPM goes into the
     report as a hint; it becomes the tempo hint only with
     `--use-metadata-bpm` (service BPMs are often half or double, or a little
     off).

## What is never done

* **No audio from Spotify, Apple Music, Tidal, Deezer or Amazon Music.**
  Their streams are DRM-protected, so links to them and their audio CDNs
  (and `spotify:` URIs) are refused with a message; these services are used
  for metadata only. A link is matched on the host name the resolver will
  look up (`%XX` decoded, then IDNA: a percent-escape, a soft hyphen or a
  full-width dot doesn't hide one), and every redirect is checked before it
  is followed. A direct download from a host name that isn't plain ASCII, or
  has `%XX` in it, is refused with the name to give instead (the `xn--` form
  of a non-ASCII one).
* **No audio from video sites.** YouTube, Vimeo, SoundCloud, Bandcamp and
  Dailymotion pages are refused before any request: their official
  interfaces give metadata, links and embedded players, and Drum Agent
  doesn't scrape them or extract their audio. A download gives no right to
  transcribe; that is still `--rights`.
* **No writes outside the cache.** Downloads go to `~/.cache/drum-agent/audio`
  (or `DRUM_AGENT_AUDIO_CACHE`), never into the repository, under sanitised
  names that include a hash of the URL. A download is streamed to a hidden
  temp file and renamed only when complete; an existing file is never
  overwritten (the same link again reuses the cached file). Your own files
  are only read.
* **No shell.** ffprobe runs with an argument list.

## Limits

| What | Limit |
|---|---|
| Metadata answer | 2 MB, 8 s timeout per request, 3 Deezer track lookups |
| Direct download | 200 MB (Content-Length checked first, then while streaming); given up when slower than 16 kB/s on average after the first 30 s (checked after every receive); audio content types only (or a generic type with an audio extension); web pages and playlists refused |
| Library scan | 20,000 audio files, tags read for at most 300 (name matches first), 20 s, each folder once (symlink loops are safe), hidden entries skipped |

Library extensions: mp3, m4a, flac, wav, ogg, aiff, opus.

## Environment

| Variable | Meaning |
|---|---|
| `DRUM_AGENT_MUSIC_DIRS` | more music folders to search, separated like PATH (`:` or `;` on Windows) |
| `DRUM_AGENT_AUDIO_CACHE` | download folder (default `~/.cache/drum-agent/audio`, or `$XDG_CACHE_HOME/drum-agent/audio`) |
| `http_proxy`, `https_proxy`, `no_proxy` | honoured for metadata and direct downloads |

`--no-online` uses no network at all: no metadata, and `--url` is refused.

## Tests

`tests/test_song.py` runs offline: the services answer with canned JSON
through a replaced HTTP helper, downloads come from a local `http.server`,
and the music folder is a temporary folder holding a WAV synthesized from an
original chart. The end-to-end runs with real analysis
and transcription are marked `slow`.
