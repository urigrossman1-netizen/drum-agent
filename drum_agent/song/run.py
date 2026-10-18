"""`python -m drum_agent song QUERY`: from a song's name to an analysis, or a chart.

The steps, each printed as it happens:

1. Identify the song from public metadata (MusicBrainz, iTunes, Deezer),
   unless --no-online.
2. Choose the audio: --audio FILE, --url URL, else the user's own library,
   else (online, with the user's yt-dlp) a video search. Where it comes from
   and its stated licence are printed.
3. Compare its length with the identified recording's: more than 10 % off
   is probably another version.
4. Without --rights: the existing high-level analysis only (tempo, meter,
   sections; no notes) and how to proceed. With --rights: the rights gate
   first, before anything is downloaded or opened for transcription, then
   the same path as `transcribe`.

The chart's title and artist are what the user typed; what the services
identified goes into the score's analysis, and their BPM is a hint that is
used only with --use-metadata-bpm.
"""

from __future__ import annotations

import json
import shlex
import textwrap
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .. import rights as rights_gate
from ..kit import DEFAULT_VOICING
from . import fetch, local, lookup
from .fetch import AudioSource, FetchError, VideoCandidate
from .local import LocalMatch
from .lookup import MetadataError, SongCandidate, format_duration

MAX_CANDIDATES = 25
IDENTIFY_MIN_SCORE = 0.55  # below this the best metadata match is shown but not relied on


@dataclass
class AudioChoice:
    """The audio chosen in step 2, before anything is downloaded or opened."""

    kind: str  # "file" (--audio), "library", "url" (a direct link) or "video"
    source: str  # a path or a URL
    local: LocalMatch | None = None
    video: VideoCandidate | None = None

    def describe(self) -> str:
        if self.kind == "file":
            return f"audio file {self.source} (given with --audio; used in place, not modified)"
        if self.kind == "library" and self.local:
            return f"{self.local.describe()} (used in place, not modified)"
        if self.kind == "video" and self.video:
            return f"{self.video.describe()} (video page, through your yt-dlp)"
        return f"link {self.source} (downloaded to the audio cache)"

    def rights_source(self) -> str:
        """What the rights gate is told the recording is."""
        if self.video:
            return f"{self.video.url} ({self.video.title}, uploaded by {self.video.uploader or 'unknown'})"
        return self.source


def _fail(message: str) -> SystemExit:
    return SystemExit(f"error: {message}")


def _check_args(args, query: str) -> None:
    """Every mistake that needs no network is reported before any lookup."""
    if not query:
        raise _fail("give the song's name, e.g. python -m drum_agent song \"Song Title\" --artist \"Band\"")
    if not 1 <= args.candidates <= MAX_CANDIDATES:
        raise _fail(f"--candidates is 1 to {MAX_CANDIDATES}, got {args.candidates}")
    if args.pick is not None and args.pick < 1:
        raise _fail(f"--pick counts from 1, got {args.pick}")
    if args.pick is not None and (args.audio or args.url):
        raise _fail("--pick chooses among the audio found; with --audio or --url there is nothing to choose")
    if args.no_online and args.url:
        raise _fail("--url needs the network; drop --no-online, or give a file with --audio")
    if args.rights and not args.out:
        raise _fail("--rights writes a chart: give an output folder with -o")
    if args.audio and not Path(args.audio).expanduser().is_file():
        raise _fail(f"--audio {args.audio}: no such file")
    if args.url:
        try:
            fetch.refuse_streaming(args.url)
        except FetchError as exc:
            raise _fail(str(exc)) from None
        if urllib.parse.urlsplit(args.url).scheme.lower() not in ("http", "https"):
            raise _fail(f"--url takes an http(s) link, not {args.url!r}; for a file of yours use --audio")


# ---- step 1 ---------------------------------------------------------------------------

def identify(query: str, args) -> SongCandidate | None:
    if args.no_online:
        print("1. Identify: skipped (--no-online)")
        return None
    try:
        found = lookup.search_metadata(query, args.artist)
    except MetadataError as exc:
        print(f"1. Identify: no metadata service answered; going on without ({exc})")
        return None
    who = f" by {args.artist}" if args.artist else ""
    if not found:
        print(f"1. Identify: no match for {query!r}{who}")
    else:
        print(f"1. Identified {query!r}{who}: {len(found)} candidate(s), best first")
        for i, c in enumerate(found[:args.candidates], 1):
            print(f"   {i}) {c.describe()}")
    for w in found.warnings:
        print(f"   warning: {w}")
    if not found:
        return None
    best = found[0]
    if best.score < IDENTIFY_MIN_SCORE:
        print("   no confident match: not used for the length check or the BPM hint (add --artist, or check "
              "the spelling)")
        return None
    return best


# ---- step 2 ---------------------------------------------------------------------------

def _search_text(query: str, artist: str | None, ident: SongCandidate | None) -> str:
    if ident:
        return f"{ident.artist} {ident.title}"
    return f"{artist} {query}" if artist else query


def choose_audio(query: str, args, ident: SongCandidate | None) -> AudioChoice:
    try:
        return _choose_audio(query, args, ident)
    except FetchError as exc:
        raise _fail(str(exc)) from None


def _choose_audio(query: str, args, ident: SongCandidate | None) -> AudioChoice:
    if args.audio:
        choice = AudioChoice("file", str(Path(args.audio).expanduser().resolve()))
        print(f"2. Audio: {choice.describe()}")
        return choice
    if args.url:
        if fetch.is_video_page(args.url):
            choice = AudioChoice("video", args.url, video=fetch.video_info(args.url, ytdlp=fetch.require_ytdlp()))
        else:
            choice = AudioChoice("url", args.url)
        print(f"2. Audio: {choice.describe()}")
        return choice

    found = local.find_local(query, args.artist, args.library or None)
    roots = [str(p) for p in (args.library or local.default_roots())]
    where = ", ".join(roots) or "no music folder found (~/Music, DRUM_AGENT_MUSIC_DIRS)"
    if found:
        print(f"2. Audio: found in your library ({where})")
        choices = [AudioChoice("library", str(m.path), local=m) for m in found[:args.candidates]]
    elif args.no_online:
        _print_warnings(found.warnings)
        raise _fail(f"no audio for {query!r} in your library ({where}), and --no-online: give a file with "
                    f"--audio FILE or a folder with --library DIR")
    else:
        exe = fetch.find_ytdlp()
        if exe is None:
            _print_warnings(found.warnings)
            raise _fail(f"no audio for {query!r} in your library ({where}). Give a file you own (--audio FILE), "
                        f"a folder (--library DIR) or a direct link (--url URL); to search video sites, install "
                        f"yt-dlp yourself: pip install yt-dlp")
        search = _search_text(query, args.artist, ident)
        print(f"2. Audio: nothing in your library ({where}); searching video sites with yt-dlp for {search!r}")
        videos = fetch.search_videos(search, args.candidates, ident.duration_s if ident else None,
                                     asked=f"{query} {args.artist or ''}", ytdlp=exe)
        if not videos:
            raise _fail(f"the video search found nothing for {search!r}; give a file with --audio")
        choices = [AudioChoice("video", v.url, video=v) for v in videos]
    _print_warnings(found.warnings)
    for i, c in enumerate(choices, 1):
        print(f"   {i}) {c.describe()}")
    # A rights basis is a statement about one recording. A search result (a reupload, a cover,
    # another band's live take can rank first, or be the only match) must be named by the user.
    if args.rights and choices[0].kind == "video":
        # The search runs again on the next run and can rank differently: name the video by its link.
        links = "\n".join(f"     {i}) --url {shlex.quote(c.source)}" for i, c in enumerate(choices, 1))
        raise _fail("--rights is a statement about one recording, and these were found by a video search, "
                    "which can rank differently on the next run: check the list, then re-run with --url for "
                    "the one your basis covers (instead of the search):\n" + links)
    if args.rights and args.pick is None:
        raise _fail("--rights is a statement about one recording, and this was found by a search of your "
                    "library: check the list, then re-run with --pick N for the one your basis covers "
                    "(or give the file with --audio)")
    pick = args.pick or 1
    if pick > len(choices):
        raise _fail(f"--pick {pick}: only {len(choices)} candidate(s) were found")
    more = "; another one: --pick N" if len(choices) > 1 else ""
    print(f"   using {pick}){more}")
    return choices[pick - 1]


def _print_warnings(warnings: list[str]) -> None:
    for w in warnings:
        print(f"   warning: {w}")


def obtain(choice: AudioChoice) -> AudioSource:
    """The local file for the choice: the user's file as is, or a download into the cache."""
    try:
        if choice.kind in ("file", "library"):
            return fetch.local_file(choice.source)
        if choice.kind == "video":
            audio = fetch.download_with_ytdlp(choice.source, info=choice.video)
        else:
            audio = fetch.fetch_audio(choice.source)
    except FetchError as exc:
        raise _fail(str(exc)) from None
    print(f"   saved as {audio.path}" + (f" ({audio.note})" if audio.note else ""))
    return audio


# ---- step 3 ---------------------------------------------------------------------------

def check_duration(audio: AudioSource, ident: SongCandidate | None) -> float | None:
    actual = local.audio_duration(audio.path) or audio.duration_s
    expected = ident.duration_s if ident else None
    if actual is None:
        print("3. Length: unknown (the file's length can't be read)")
    elif expected is None:
        print(f"3. Length: {format_duration(actual)} (no identified length to compare with)")
    else:
        off = abs(actual - expected) / expected
        if off > fetch.DURATION_TOLERANCE:
            print(f"3. Length: {format_duration(actual)}, but the identified recording is "
                  f"{format_duration(expected)} ({off:.0%} off)")
            print("   warning: this may be another version (live, edit, remix) or another song; check it "
                  "before relying on the result")
        else:
            print(f"3. Length: {format_duration(actual)}, matches the identified recording "
                  f"({format_duration(expected)})")
    return actual


# ---- step 4 ---------------------------------------------------------------------------

def _bpm_hint(args, ident: SongCandidate | None) -> float | None:
    """--bpm if given; the metadata BPM only when asked for with --use-metadata-bpm."""
    if args.bpm:
        return args.bpm
    meta = ident.bpm if ident else None
    if args.use_metadata_bpm:
        if meta:
            print(f"   tempo hint: the metadata BPM {meta:g} (--use-metadata-bpm)")
            return meta
        print("   --use-metadata-bpm: the metadata has no BPM; the tempo is detected")
    elif meta:
        print(f"   metadata BPM {meta:g}: a hint only, not used (pass --use-metadata-bpm to use it as --bpm)")
    return None


# Options carried over to the suggested --rights command (flag, attribute, default; False for a
# switch). The source replaces --library, --candidates and --pick (tests/test_song.py checks
# that every other option of `song` is here).
_CARRIED = (
    ("--artist", "artist", None), ("--no-online", "no_online", False),
    ("--use-metadata-bpm", "use_metadata_bpm", False), ("--title", "title", None),
    ("--transcriber", "transcriber", None), ("--bpm", "bpm", None), ("--time-signature", "time_signature", None),
    ("--downbeat", "downbeat", None), ("--feel", "feel", "auto"), ("--drums-only", "drums_only", False),
    ("--sensitivity", "sensitivity", 1.0), ("--no-32nds", "no_32nds", False), ("--start", "start", None),
    ("--end", "end", None), ("--sections", "sections", None), ("--chart-type", "chart_type", None),
    ("--detector", "detector", "auto"),
    # export options
    ("--stem", "stem", None), ("--formats", "formats", "pdf,musicxml,midi,json"), ("--paper", "paper", "letter"),
    ("--staff-size", "staff_size", 20), ("--repeats", "repeats", "auto"), ("--bars-per-line", "bars_per_line", 4.0),
    ("--no-legend", "no_legend", False), ("--midi-timing", "midi_timing", "quantized"), ("--kit", "kit", None),
    ("--voicing", "voicing", DEFAULT_VOICING),
)


def _rerun_command(args, audio: AudioSource) -> str:
    """The same request with --rights: from the original source (a link is fetched again,
    which re-records its uploader and licence; the cache makes it quick), with every
    option the user gave. Values are joined to their flag and the song's name comes after
    "--", so that a value starting with "-" is still read as one."""
    cmd = ["python", "-m", "drum_agent", "song"]
    cmd += ["--url", audio.url] if audio.url and audio.origin in ("video", "direct") else ["--audio", str(audio.path)]
    for flag, attr, default in _CARRIED:
        value = getattr(args, attr, default)
        if value is None or value == default:
            continue
        cmd.append(flag if value is True else f"{flag}={value:g}" if isinstance(value, float) else f"{flag}={value}")
    cmd += ["--rights", "BASIS", f"--out={args.out or 'OUT'}", "--", args.query]
    return " ".join(shlex.quote(c) for c in cmd)


def analyze_only(audio: AudioSource, ident: SongCandidate | None, args) -> int:
    from ..audio.transcribe import analyze_file
    print("4. Analysis only (no --rights): tempo, meter and sections; no notes")
    bpm = _bpm_hint(args, ident)
    info = analyze_file(audio.path, bpm=bpm, time_signature=args.time_signature,
                        detector=getattr(args, "detector", "auto"))
    info["audio_source"] = audio.describe()
    if ident:
        info["identified_as"] = ident.to_dict()
    print(textwrap.indent(json.dumps(info, indent=1), "   "))
    print("   To transcribe the notes, state your basis for it and re-run with --rights:")
    print("     own (you made or own the recording), permission (the rights holder allowed it), licensed (a")
    print("     licence covers transcription), public_domain, or original (your own composition):")
    print(f"     {_rerun_command(args, audio)}")
    print("   Otherwise, get a licensed chart from the publisher.")
    hint = fetch.license_hint(audio.license)
    if hint:
        print(f"   {hint[1]} (Not applied: the basis is yours to state.)")
    if args.out:
        print(f"   No chart was written, so {args.out} is unused.")
    return 0


def transcribe(audio: AudioSource, ident: SongCandidate | None, args, query: str) -> int:
    """The `transcribe` command's path, on the chosen audio, with the song's identity recorded."""
    from ..audio.transcribe import TranscribeOptions, transcribe_file
    from ..cli import _apply_sections, _export_opts, _guard_input, _kit, _print_report
    from ..pipeline import export_all
    title = args.title or query
    stem = args.stem or fetch.safe_name(title).lower()
    _guard_input(str(audio.path), args.out, stem)
    kit = _kit(args)
    print(f"4. Transcription (--rights {args.rights}) of {audio.path}")
    bpm = _bpm_hint(args, ident)
    topts = TranscribeOptions(
        bpm=bpm, time_signature=args.time_signature, downbeat=args.downbeat, feel=args.feel,
        drums_only=args.drums_only, sensitivity=args.sensitivity, allow_32nds=not args.no_32nds,
        start=args.start, end=args.end, detector=getattr(args, "detector", "auto"),
    )
    score = transcribe_file(audio.path, topts)
    score.title = title
    score.artist = args.artist
    score.transcriber = args.transcriber or "Drum Agent (automatic)"
    score.rights = args.rights
    score.source = audio.describe() + (f", from {args.start:g}s" if args.start else "")
    if args.chart_type:
        score.chart_type = args.chart_type
    _record_identity(score, ident, used_bpm=bpm is not None and not args.bpm)
    _apply_sections(score, args.sections)
    report = export_all(score, args.out, stem, kit, _export_opts(args))
    return _print_report(report, Path(args.out))


def _record_identity(score, ident: SongCandidate | None, used_bpm: bool) -> None:
    """What the services identified goes into the analysis (and the report's notes), not the title."""
    if ident is None:
        return
    score.analysis["identified_as"] = ident.to_dict()
    notes = score.analysis.setdefault("notes", [])
    notes.append(f"Identified as {ident.describe()}. The chart shows the title you typed.")
    if ident.bpm:
        score.analysis["metadata_bpm"] = ident.bpm
        notes.append(f"Metadata BPM {ident.bpm:g} (Deezer): " + (
            "used as the tempo hint (--use-metadata-bpm)." if used_bpm
            else "a hint only, not used; --use-metadata-bpm would use it as --bpm."))


def run_song(args) -> int:
    query = " ".join(args.query.split())
    _check_args(args, query)
    ident = identify(query, args)
    choice = choose_audio(query, args, ident)
    if args.rights:
        # The gate comes before the audio is downloaded or opened for transcription.
        rights_gate.require_rights(args.rights, choice.rights_source())
    audio = obtain(choice)
    check_duration(audio, ident)
    if not args.rights:
        return analyze_only(audio, ident, args)
    return transcribe(audio, ident, args, query)
