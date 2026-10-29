"""`song`: from a song's name to audio the user may use, then analysis or transcription.

Everything here runs offline. The three metadata services answer with canned
JSON through a replaced HTTP helper; downloads come from a local http.server
on 127.0.0.1; yt-dlp is a fake Python script put first on PATH that answers
searches and "downloads" a WAV synthesized from an original chart. The song
("Test Groove" by "The Placeholders") and every fixture are made up.

The rights gate is checked as an order of events: with --rights, it runs
before anything is downloaded or opened for transcription; without, only the
high-level analysis runs and no chart is written.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import soundfile

from conftest import needs_fluidsynth, needs_lilypond
from drum_agent import rights as rights_module
from drum_agent.charts import compile_spec
from drum_agent.cli import build_parser, main
from drum_agent.model import Score
from drum_agent.song import fetch, local, lookup
from drum_agent.song.fetch import AudioSource, FetchError, VideoCandidate
from drum_agent.song.lookup import MetadataError

ROOT = Path(__file__).resolve().parents[1]
FAST = "musicxml,midi,json"  # every format that doesn't need LilyPond
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")

# An original groove: the "recording" every fake download delivers.
GROOVE = {
    "title": "Song Lookup Groove",
    "tempo": 120,
    "chart_type": "pattern_study",
    "rights": "original",
    "patterns": {"rock": {"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---", "bd": "x-------x-x-----"}},
    "sections": [{"label": "A", "bars": ["rock*6"]}],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Downloads into a temp cache, no music folders from the environment, local servers unproxied."""
    monkeypatch.setenv(fetch.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.delenv(local.MUSIC_DIRS_ENV, raising=False)
    monkeypatch.delenv("DRUM_AGENT_DEBUG", raising=False)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")


# ---- canned metadata --------------------------------------------------------------------

def canned_services(duration_s: float = 192.0, fail: tuple[str, ...] = (), calls: list | None = None):
    """A stand-in for lookup.http_get_json: MusicBrainz, iTunes and Deezer answers for "Test Groove".

    `fail` names hosts that answer with an error instead."""
    ms = int(duration_s * 1000)
    placeholders = [{"name": "The Placeholders", "artist": {"id": "a-1", "name": "The Placeholders"}}]
    answers = {
        "musicbrainz.org": {"count": 3, "recordings": [
            {"id": "mb-1", "score": 100, "title": "Test Groove", "length": ms, "artist-credit": placeholders,
             "first-release-date": "2021-03-05", "isrcs": ["QZTST2100001"],
             "releases": [{"id": "r-1", "title": "Practice Room Sessions", "date": "2021-03-05"}]},
            {"id": "mb-2", "score": 96, "title": "Test Groove (Live)", "length": int(ms * 1.35),
             "artist-credit": placeholders, "releases": [{"title": "Live at the Rehearsal Hall", "date": "2022"}]},
            {"id": "mb-3", "score": 80, "title": "Test Groove", "length": ms + 9000,
             "artist-credit": [{"name": "Karaoke Band Deluxe"}], "releases": [{"title": "Karaoke Hits Vol. 9"}]},
        ]},
        "itunes.apple.com": {"resultCount": 2, "results": [
            {"kind": "song", "trackName": "Test Groove (2023 Remaster)", "artistName": "The Placeholders",
             "collectionName": "Practice Room Sessions (Deluxe)", "releaseDate": "2023-01-01T08:00:00Z",
             "trackTimeMillis": ms + 500, "trackViewUrl": "https://music.apple.com/us/album/prs?i=1"},
            {"kind": "song", "trackName": "Groove Test", "artistName": "Somebody Else", "trackTimeMillis": 150000},
        ]},
        "deezer-search": {"total": 2, "data": [
            {"id": 3001, "title": "Test Groove", "duration": round(duration_s),
             "link": "https://www.deezer.com/track/3001", "artist": {"name": "The Placeholders"},
             "album": {"title": "Practice Room Sessions"}},
            {"id": 3002, "title": "Test Groove (Live)", "duration": round(duration_s * 1.35),
             "link": "https://www.deezer.com/track/3002", "artist": {"name": "The Placeholders"},
             "album": {"title": "Live at the Rehearsal Hall"}},
        ]},
        "deezer-3001": {"id": 3001, "title": "Test Groove", "isrc": "QZTST2100001", "bpm": 118.5,
                        "release_date": "2021-03-05", "duration": round(duration_s)},
        "deezer-3002": {"id": 3002, "title": "Test Groove (Live)", "bpm": 0, "release_date": "2022-06-01"},
    }

    def fake(url, timeout=8, max_bytes=None):
        if calls is not None:
            calls.append(url)
        host = re.match(r"https://([^/]+)", url).group(1)
        if host in fail:
            raise MetadataError(f"{host} answered HTTP 503")
        if host == "api.deezer.com":
            m = re.search(r"/track/(\d+)", url)
            return answers[f"deezer-{m.group(1)}" if m else "deezer-search"]
        return answers[host]

    return fake


@pytest.fixture
def services(monkeypatch):
    def install(**kw):
        calls = []
        monkeypatch.setattr(lookup, "http_get_json", canned_services(calls=calls, **kw))
        return calls
    return install


def test_metadata_is_merged_ranked_and_deduplicated(services):
    calls = services()
    found = lookup.search_metadata("Test Groove", "The Placeholders")
    best = found[0]
    assert (best.title, best.artist) == ("Test Groove", "The Placeholders")
    assert set(best.sources) == {"musicbrainz", "itunes", "deezer"}  # the remaster on iTunes is the same take
    assert (best.bpm, best.isrc, best.year, best.duration_s) == (118.5, "QZTST2100001", 2021, 192.0)
    assert best.album == "Practice Room Sessions"
    assert set(best.urls) == {"musicbrainz", "itunes", "deezer"}
    live = [c for c in found if "Live" in c.title]
    assert len(live) == 1 and set(live[0].sources) == {"musicbrainz", "deezer"}  # merged across services
    assert live[0].bpm is None  # Deezer's bpm 0 means unknown
    assert [(c.title, c.artist) for c in found] == [  # one entry per recording, best first
        ("Test Groove", "The Placeholders"), ("Test Groove (Live)", "The Placeholders"),
        ("Groove Test", "Somebody Else"), ("Test Groove", "Karaoke Band Deluxe")]
    assert found[0].score > found[1].score + 0.3
    assert found.warnings == []
    mb = next(u for u in calls if "musicbrainz" in u)
    assert "fmt=json" in mb and "recording%3A%22Test+Groove%22" in mb and "artist%3A%22The+Placeholders%22" in mb
    assert any("itunes.apple.com/search" in u and "entity=song" in u for u in calls)
    assert any(u.startswith("https://api.deezer.com/track/3001") for u in calls)


def test_without_artist_the_original_still_wins(services):
    services()
    for query in ("Test Groove", "the placeholders test groove"):  # the query may hold the artist too
        found = lookup.search_metadata(query)
        assert (found[0].title, found[0].artist) == ("Test Groove", "The Placeholders")
        karaoke = next(c for c in found if c.artist == "Karaoke Band Deluxe")
        assert karaoke.score < found[0].score - 0.3


def test_one_failing_source_is_a_warning(services):
    services(fail=("musicbrainz.org",))
    found = lookup.search_metadata("Test Groove", "The Placeholders")
    assert found[0].title == "Test Groove" and set(found[0].sources) == {"itunes", "deezer"}
    assert len(found.warnings) == 1 and found.warnings[0].startswith("MusicBrainz:")


def test_all_sources_failing_is_an_error(services):
    services(fail=("musicbrainz.org", "itunes.apple.com", "api.deezer.com"))
    with pytest.raises(MetadataError, match="MusicBrainz.*iTunes.*Deezer"):
        lookup.search_metadata("Test Groove")


def test_an_answer_of_another_shape_is_a_warning(monkeypatch):
    def fake(url, timeout=8, max_bytes=None):
        if "deezer" in url:
            return {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}
        if "itunes" in url:
            return ["not", "a", "dict"]
        return {"recordings": [{"title": "Test Groove", "artist-credit": [{"name": "The Placeholders"}]}]}

    monkeypatch.setattr(lookup, "http_get_json", fake)
    found = lookup.search_metadata("Test Groove")
    assert [c.title for c in found] == ["Test Groove"]
    assert any("Quota limit exceeded" in w for w in found.warnings)
    assert any(w.startswith("iTunes: unexpected answer") for w in found.warnings)


def test_text_helpers():
    assert lookup.title_key("Test Groove (Remastered 2011)") == lookup.title_key("Test Groove - 2011 Remaster")
    assert lookup.title_key("Test Groove (Live)") != lookup.title_key("Test Groove")
    assert lookup.artist_key("The Placeholders feat. Guest") == lookup.artist_key("Placeholders & Guest")
    assert lookup.text_key("Café-Noir!") == "cafe noir"
    assert lookup.similarity("test groove", "Test Groove") == 1.0
    assert lookup.similarity("test groove", "groove test") > lookup.similarity("test groove", "other song")
    assert lookup.version_penalty("Test Groove (Live)", "test groove") > 0
    assert lookup.version_penalty("Test Groove (Live)", "test groove live") == 0
    assert lookup.format_duration(192.4) == "3:12" and lookup.format_duration(3725) == "1:02:05"


# ---- a local web server ---------------------------------------------------------------

class _Handler(SimpleHTTPRequestHandler):
    """Static files, plus /echo (headers as JSON), /stream.wav (no Content-Length) and
    /disguised.mp3 (a web page served as audio)."""

    hits: list = []

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):  # noqa: N802 (http.server API)
        type(self).hits.append(self.path)
        if self.path == "/echo":
            return self._send(json.dumps({"user_agent": self.headers.get("User-Agent")}).encode(), "application/json")
        if self.path == "/big.json":
            return self._send(b"[" + b"1," * 1_200_000 + b"1]", "application/json")
        if self.path == "/notjson":
            return self._send(b"<html>hello</html>", "text/html")
        if self.path == "/disguised.mp3":
            return self._send(b"<!DOCTYPE html><html><body>Sign in</body></html>", "audio/mpeg")
        if self.path == "/stream.wav":
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            for _ in range(40):
                self.wfile.write(b"RIFF" + b"\0" * 8188)
            return None
        if self.path == "/error":
            self.send_error(503)
            return None
        return super().do_GET()

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def web(tmp_path):
    """A web server on 127.0.0.1 serving tmp_path/www; yields (base URL, folder, hits)."""
    www = tmp_path / "www"
    www.mkdir()
    _Handler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, directory=str(www)))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", www, _Handler.hits
    finally:
        server.shutdown()
        server.server_close()


def test_http_helper_sends_our_user_agent_and_caps_the_size(web):
    base, _, _ = web
    assert lookup.http_get_json(base + "/echo")["user_agent"] == lookup.USER_AGENT
    with pytest.raises(MetadataError, match="more than"):
        lookup.http_get_json(base + "/big.json", max_bytes=100_000)
    with pytest.raises(MetadataError, match="not answer with JSON"):
        lookup.http_get_json(base + "/notjson")
    with pytest.raises(MetadataError, match="HTTP 503"):
        lookup.http_get_json(base + "/error")
    with pytest.raises(MetadataError, match="only http"):
        lookup.http_get_json("file:///etc/passwd")


def write_wav(path: Path, seconds: float = 1.0) -> Path:
    import numpy as np
    sr = 22050
    t = np.arange(int(sr * seconds)) / sr
    soundfile.write(path, 0.2 * np.sin(2 * np.pi * 220 * t), sr)
    return path


def cache_files(tmp_path) -> list[str]:
    d = tmp_path / "cache"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def test_direct_url_download(web, tmp_path):
    base, www, hits = web
    src = write_wav(www / "My Song (final)!.wav")
    url = base + "/My%20Song%20(final)!.wav"
    audio = fetch.fetch_audio(url)
    assert audio.origin == "direct" and audio.url == url
    assert audio.path.parent == (tmp_path / "cache").resolve()
    assert re.fullmatch(r"My_Song_final-[0-9a-f]{10}\.wav", audio.path.name)
    assert audio.path.read_bytes() == src.read_bytes()
    assert cache_files(tmp_path) == [audio.path.name]  # no temp file left behind
    again = fetch.fetch_audio(url)  # the same link again: the cached file, not a second download
    assert again.path == audio.path and again.note == "already in the cache"
    assert hits == ["/My%20Song%20(final)!.wav"] * 2  # the second time only the headers are read


def test_download_size_cap(web, tmp_path):
    base, www, _ = web
    write_wav(www / "long.wav", seconds=4)
    with pytest.raises(FetchError, match="download limit"):
        fetch.fetch_audio(base + "/long.wav", max_bytes=50_000)  # refused from Content-Length
    with pytest.raises(FetchError, match="download limit"):
        fetch.fetch_audio(base + "/stream.wav", max_bytes=100_000)  # no length given: stopped while streaming
    assert cache_files(tmp_path) == []


@pytest.mark.parametrize("name,body,match", [
    ("notes.txt", b"just text", "text/plain, not audio"),
    ("data.json", b"{}", "application/json, not audio"),
])
def test_wrong_content_type_is_refused(web, tmp_path, name, body, match):
    base, www, _ = web
    (www / name).write_bytes(body)
    with pytest.raises(FetchError, match=match):
        fetch.fetch_audio(f"{base}/{name}")
    assert cache_files(tmp_path) == []


def test_a_web_page_needs_yt_dlp(web, tmp_path, monkeypatch):
    base, www, _ = web
    (www / "page.html").write_text("<html><body>a page</body></html>")
    monkeypatch.setattr(fetch, "find_ytdlp", lambda: None)
    with pytest.raises(FetchError, match=r"pip install yt-dlp"):
        fetch.fetch_audio(base + "/page.html")
    with pytest.raises(FetchError, match="sent a web page"):
        fetch.fetch_audio(base + "/disguised.mp3")  # labelled audio, but it isn't
    assert cache_files(tmp_path) == []


def test_a_local_file_is_used_in_place(tmp_path):
    src = write_wav(tmp_path / "mine.wav")
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    audio = fetch.fetch_audio(str(src))
    assert audio.path == src.resolve() and audio.origin == "file"
    assert fetch.fetch_audio(src.as_uri()).path == src.resolve()
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before
    assert cache_files(tmp_path) == []
    with pytest.raises(FetchError, match="no such audio file"):
        fetch.fetch_audio(str(tmp_path / "missing.wav"))


def test_the_cache_never_lives_in_the_repository(tmp_path, monkeypatch):
    with pytest.raises(FetchError, match="inside the drum-agent repository"):
        fetch.cache_root(ROOT / "tests" / "_downloads")
    assert not (ROOT / "tests" / "_downloads").exists()
    monkeypatch.setenv(fetch.CACHE_ENV, str(tmp_path / "elsewhere"))
    assert fetch.cache_root() == (tmp_path / "elsewhere").resolve()


def test_safe_names():
    assert fetch.safe_name("../../etc/passwd") == "etc_passwd"
    assert fetch.safe_name("Ünïcödé  Sóng: Part 1/2") == "Unicode_Song_Part_1_2"
    assert fetch.safe_name("...") == "audio" and fetch.safe_name("") == "audio"
    # titles in another script get distinct names, not "audio" for every song
    assert fetch.safe_name("שיר לשלום").startswith("audio-") and fetch.safe_name("上を向いて歩こう") != fetch.safe_name("שיר לשלום")
    assert len(fetch.safe_name("x" * 500)) <= 60


@pytest.mark.parametrize("url,service", [
    ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "Spotify"),
    ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", "Spotify"),
    ("https://music.apple.com/us/album/some-album/123?i=456", "Apple Music"),
    ("https://tidal.com/browse/track/123", "Tidal"),
    ("https://listen.tidal.com/track/123", "Tidal"),
    ("https://www.deezer.com/track/3001", "Deezer"),
    ("https://music.amazon.com/albums/B000000000", "Amazon Music"),
    ("https://www.amazon.de/music/player/albums/B000000000", "Amazon Music"),
    ("https://open.spotify.com./track/4uLU6hMCjMI75M1A2tKUQC", "Spotify"),  # trailing-dot hostnames
    ("https://www.deezer.com./track/3001", "Deezer"),
    ("https://p.scdn.co/mp3-preview/abc", "Spotify"),  # the services' audio CDNs
    ("https://cdns-preview-d.dzcdn.net/stream/c-123.mp3", "Deezer"),
    # the host the resolver looks up: urllib decodes %XX, IDNA drops a soft hyphen (U+00AD), maps
    # "\u00ba" to "o" and reads U+3002 and U+FF0E as dots
    ("http://p.s%63dn.co/mp3-preview/abc.mp3", "Spotify"),
    ("https://open.spotify%2Ecom/track/abc", "Spotify"),
    ("http://p.s%C2%ADcdn.co/mp3-preview/abc.mp3", "Spotify"),
    ("http://p.s\u00adcdn.co/mp3-preview/abc.mp3", "Spotify"),
    ("https://open.spo\u00adtify.com/track/abc", "Spotify"),
    ("https://open.sp\u00batify.com/track/abc", "Spotify"),
    ("https://open.spotify\u3002com/track/abc", "Spotify"),
    ("https://p\uff0escdn\uff0eco/mp3-preview/abc", "Spotify"),
    ("https://www.amazon.com/-/es/music/player/albums/B000000000", "Amazon Music"),
    ("https://smile.amazon.com/music/player", "Amazon Music"),
])
def test_drm_streaming_links_are_refused(url, service, monkeypatch):
    monkeypatch.setattr(fetch, "open_url", lambda *a, **k: pytest.fail("a streaming link was opened"))
    assert fetch.streaming_service(url) == service
    with pytest.raises(FetchError, match=rf"{service} streams are DRM-protected.*metadata only"):
        fetch.fetch_audio(url)


def test_other_links_are_not_streaming_services():
    for url in ("https://example.com/take.mp3", "https://www.youtube.com/watch?v=x", "/home/me/Music/a.flac",
                "https://www.amazon.com/some-book", "https://www.amazon.com/musical-instruments/b"):
        assert fetch.streaming_service(url) is None


def test_a_host_name_that_is_not_plain_ascii_is_refused_with_a_message(monkeypatch):
    # The request would go to the decoded or IDNA form of the name: say so, rather than crash or ask
    # another host.
    monkeypatch.setattr(fetch, "open_url", lambda *a, **k: pytest.fail("the link was opened"))
    for url, match in (("http://example\u3002com/take.mp3", "example.com"),
                       ("http://exam\u00adple.com/take.mp3", "example.com"),
                       ("http://ex%61mple.com/take.mp3", "example.com"),  # urllib asks for the decoded name
                       ("http://b\u00fccher.example/take.mp3", "xn--bcher-kva.example"),
                       ("http://a\u3002\u3002b/take.mp3", "ASCII")):
        with pytest.raises(FetchError, match=match):
            fetch.fetch_audio(url)


def test_licence_hints_are_suggestions_only():
    assert fetch.license_hint(None) is None
    assert fetch.license_hint("Creative Commons Attribution license (reuse allowed)")[0] == "licensed"
    assert fetch.license_hint("CC0 1.0 Universal (public domain)")[0] == "public_domain"
    nd = fetch.license_hint("Creative Commons Attribution-NoDerivatives 4.0")
    assert nd[0] is None and "NoDerivatives" in nd[1] and "permission" in nd[1]
    assert fetch.license_hint("Standard YouTube License")[0] is None


def test_video_ranking_prefers_the_right_length_and_the_original():
    v = [VideoCandidate("https://v.example/1", "Test Groove - Drum Cover", duration_s=192),
         VideoCandidate("https://v.example/2", "The Placeholders - Test Groove (Live)", duration_s=250),
         VideoCandidate("https://v.example/3", "The Placeholders - Test Groove", duration_s=400),
         VideoCandidate("https://v.example/4", "The Placeholders - Test Groove (Official Audio)", duration_s=193),
         VideoCandidate("https://v.example/5", "Test Groove slowed + reverb 8D", duration_s=192)]
    ranked = fetch.rank_videos(v, "The Placeholders Test Groove", expected_duration=192)
    assert ranked[0].url == "https://v.example/4"
    assert {ranked[-1].url, ranked[-2].url} == {"https://v.example/1", "https://v.example/5"}
    asked_live = fetch.rank_videos(v, "The Placeholders Test Groove", 250, asked="test groove live")
    assert asked_live[0].url == "https://v.example/2"  # the user asked for the live version


# ---- the user's library ---------------------------------------------------------------

def ffmpeg_tone(path: Path, **tags) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1"]
    for k, v in tags.items():
        cmd += ["-metadata", f"{k}={v}"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True, timeout=60)
    return path


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "Music"
    (lib / "rips").mkdir(parents=True)
    (lib / "The Placeholders" / "Practice Room Sessions").mkdir(parents=True)
    (lib / "rips" / "cover.jpg").write_bytes(b"not audio")
    return lib


@needs_ffmpeg
def test_library_match_by_tags(library):
    tagged = ffmpeg_tone(library / "rips" / "track01.flac", title="Test Groove", artist="The Placeholders")
    ffmpeg_tone(library / "rips" / "track02.mp3", title="Another Tune", artist="The Placeholders")
    opus = ffmpeg_tone(library / "rips" / "track03.opus", title="Test Groove", artist="Karaoke Band Deluxe")
    found = local.find_local("Test Groove", "The Placeholders", [library])
    assert found[0].path == tagged.resolve() and found[0].matched_by == "tags"
    assert (found[0].title, found[0].artist) == ("Test Groove", "The Placeholders")
    assert found[0].duration_s == pytest.approx(1.0, abs=0.1)
    assert opus.resolve() not in [m.path for m in found[:1]]  # same title, other artist: ranked lower
    assert all("track02" not in m.path.name for m in found)
    no_artist = local.find_local("test groove", None, [library])  # Opus keeps its tags on the stream
    assert {m.path for m in no_artist} >= {tagged.resolve(), opus.resolve()}


def test_library_match_by_file_name(library, monkeypatch):
    live = write_wav(library / "rips" / "The Placeholders - Test Groove (Live).wav")
    by_name = write_wav(library / "The Placeholders" / "Practice Room Sessions" / "03 Test Groove.wav")
    flat = write_wav(library / "rips" / "The Placeholders - Test Groove.wav")
    write_wav(library / "rips" / "Somebody Else - Other Song.wav")
    monkeypatch.setattr(local.shutil, "which", lambda name: None)  # no ffprobe: names only
    found = local.find_local("Test Groove", "The Placeholders", [library])
    assert {m.path for m in found[:2]} == {by_name.resolve(), flat.resolve()}
    assert [m.path for m in found[2:]] == [live.resolve()]  # offered, but after the studio take
    assert local.find_local("Test Groove live", "The Placeholders", [library])[0].path == live.resolve()
    assert all(m.matched_by == "file name" for m in found)
    assert any("ffprobe not found" in w for w in found.warnings)
    assert local.find_local("Unknown Song", None, [library]) == []


def test_library_scan_is_bounded_and_survives_symlink_loops(library):
    for i in range(5):
        write_wav(library / "rips" / f"Test Groove take {i}.wav")
    os.symlink(library, library / "rips" / "loop")  # a link back up the tree
    os.symlink(library / "rips", library / "again")  # the same folder twice
    found = local.find_local("Test Groove take 1", None, [library], time_limit=10)
    paths = [m.path for m in found]
    assert len(paths) == len(set(paths))
    assert paths[0].name == "Test Groove take 1.wav"
    capped = local.find_local("Test Groove", None, [library], max_files=2)
    assert any("stopped at 2" in w for w in capped.warnings) and len(capped) <= 2
    assert local.find_local("Test Groove", None, [library / "nope"]).warnings[0].startswith("not a folder")


def test_default_roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Music").mkdir(parents=True)
    extra = tmp_path / "Bounces"
    extra.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(local.MUSIC_DIRS_ENV, os.pathsep.join([str(extra), str(tmp_path / "missing"), str(extra)]))
    assert local.default_roots() == [(home / "Music").resolve(), extra.resolve()]


# ---- a fake yt-dlp ---------------------------------------------------------------------

FAKE_YTDLP = r'''#!{python}
"""A stand-in for yt-dlp: answers searches from FAKE_YTDLP_VIDEOS and "downloads" FAKE_YTDLP_WAV."""
import json, os, re, shutil, sys
args = sys.argv[1:]
with open(os.environ["FAKE_YTDLP_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
videos = json.loads(os.environ["FAKE_YTDLP_VIDEOS"])
target = args[-1]
if "--dump-json" in args:
    m = re.match(r"ytsearch(\d*):(.*)", target)
    if m:
        for v in videos[:int(m.group(1) or 1)]:
            print(json.dumps(v))
        sys.exit(0)
    for v in videos:
        if v["webpage_url"] == target:
            print(json.dumps(v))
            sys.exit(0)
    print("ERROR: Unsupported URL: " + target, file=sys.stderr)
    sys.exit(1)
v = next((v for v in videos if v["webpage_url"] == target), None)
if v is None or "-o" not in args:
    print("ERROR: Unsupported URL: " + target, file=sys.stderr)
    sys.exit(1)
title = re.sub(r"[^A-Za-z0-9_.-]+", "_", v["title"]).strip("_")[:80]
out = args[args.index("-o") + 1].replace("%(title).80B", title).replace("%(id)s", v["id"]).replace("%(ext)s", "wav")
if "-P" in args:  # the download folder, as in yt-dlp: the template is relative to it
    out = os.path.join(args[args.index("-P") + 1], out)
if not os.path.isabs(out):
    print("ERROR: fake yt-dlp would write into the working directory: " + out, file=sys.stderr)
    sys.exit(1)
shutil.copyfile(os.environ["FAKE_YTDLP_WAV"], out)
print(out)
'''

CC_BY = "Creative Commons Attribution license (reuse allowed)"


def video_infos(seconds: float) -> list[dict]:
    def info(vid, title, duration, uploader, licence=None):
        return {"id": vid, "title": title, "duration": duration, "uploader": uploader, "channel": uploader,
                "license": licence, "webpage_url": f"https://www.youtube.com/watch?v={vid}"}
    return [info("tg-cover", "Test Groove - Drum Cover", seconds, "Somebody Drums"),
            info("tg-live", "The Placeholders - Test Groove (Live)", seconds * 1.4, "Fan Uploads"),
            info("tg-official", "The Placeholders - Test Groove (Official Audio)", seconds, "The Placeholders",
                 CC_BY)]


@pytest.fixture(scope="module")
def groove_wav(tmp_path_factory) -> Path:
    from drum_agent.synth import synthesize
    return synthesize(compile_spec(GROOVE), tmp_path_factory.mktemp("wav") / "groove.wav", method="numpy")


def wav_seconds(path: Path) -> float:
    return soundfile.info(str(path)).duration


@pytest.fixture
def ytdlp(tmp_path, monkeypatch, groove_wav):
    """The fake yt-dlp first on PATH. Returns a function giving the argument lists it was called with."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "yt-dlp"
    exe.write_text(FAKE_YTDLP.replace("{python}", sys.executable))
    exe.chmod(0o755)
    log = tmp_path / "ytdlp.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    monkeypatch.setenv("FAKE_YTDLP_WAV", str(groove_wav))
    monkeypatch.setenv("FAKE_YTDLP_VIDEOS", json.dumps(video_infos(wav_seconds(groove_wav))))

    def calls() -> list[list[str]]:
        return [json.loads(line) for line in log.read_text().splitlines()]
    return calls


def downloads(calls) -> list[list[str]]:
    return [c for c in calls if "-o" in c]


def test_yt_dlp_search_and_download(ytdlp, groove_wav, tmp_path):
    assert fetch.find_ytdlp() == [str(tmp_path / "bin" / "yt-dlp")]
    videos = fetch.search_videos("The Placeholders Test Groove", 3, expected_duration=wav_seconds(groove_wav))
    assert [v.id for v in videos][0] == "tg-official"
    assert videos[0].license == CC_BY and videos[0].uploader == "The Placeholders"
    assert downloads(ytdlp()) == []  # searching downloads nothing
    audio = fetch.fetch_audio(videos[0].url, info=videos[0])
    assert audio.origin == "video" and audio.license == CC_BY
    assert audio.path.parent == (tmp_path / "cache").resolve() and audio.path.suffix == ".wav"
    assert audio.path.read_bytes() == groove_wav.read_bytes()
    call = downloads(ytdlp())[0]
    assert call[-2:] == ["--", videos[0].url] and "--restrict-filenames" in call and "--no-overwrites" in call
    assert "uploader The Placeholders" in audio.describe() and CC_BY in audio.describe()
    again = fetch.fetch_audio(videos[0].url, info=videos[0])  # the same video: the cached file, no new download
    assert again.path == audio.path and again.note == "already in the cache" and len(downloads(ytdlp())) == 1


def test_without_yt_dlp_the_message_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(fetch.shutil, "which", lambda name: None)
    monkeypatch.setattr(fetch.importlib.util, "find_spec", lambda name: None)
    assert fetch.find_ytdlp() is None
    with pytest.raises(FetchError, match="pip install yt-dlp"):
        fetch.fetch_audio("https://www.youtube.com/watch?v=tg-official")


# ---- the song command -------------------------------------------------------------------

@pytest.fixture
def cli(capsys):
    def run(*argv):
        capsys.readouterr()
        try:
            rc = main([str(a) for a in argv])
        except SystemExit as exc:
            if isinstance(exc.code, str):
                print(exc.code, file=sys.stderr)
                rc = 1
            else:
                rc = exc.code or 0
        out, err = capsys.readouterr()
        return rc, out, err
    return run


@pytest.fixture
def events(monkeypatch):
    """Records the rights gate, every audio read and every transcription, in order."""
    import drum_agent.audio.transcribe as T
    seen: list[tuple[str, object]] = []
    real_gate = rights_module.require_rights

    def gate(rights, source):
        seen.append(("rights", source))
        return real_gate(rights, source)

    def fake_transcribe(path, opts):
        seen.append(("transcribe", (Path(path), opts)))
        score = compile_spec(dict(GROOVE, title="whatever the file says", rights=None, chart_type="full_transcription"))
        score.status = "unverified_auto"
        score.analysis = {"tempo_estimate": "120 BPM (quarter note)", "notes": ["from the detector"]}
        return score

    def fake_analyze(path, bpm=None, time_signature=None, detector="auto"):
        seen.append(("analyze", (Path(path), bpm, time_signature)))
        return {"file": str(path), "tempo": "120 BPM (quarter note)", "meter": "4/4 (confidence 0.9)",
                "sections": ["A: bar 1, 6 bars, hihat"]}

    monkeypatch.setattr(rights_module, "require_rights", gate)
    monkeypatch.setattr(T, "transcribe_file", fake_transcribe)
    monkeypatch.setattr(T, "analyze_file", fake_analyze)
    monkeypatch.setattr(T, "load_audio", lambda *a, **k: pytest.fail("audio decoded outside the stubs"))
    return seen


def kinds(seen) -> list[str]:
    return [k for k, _ in seen]


def test_song_with_rights_transcribes_the_chosen_video(cli, services, ytdlp, events, groove_wav, tmp_path, monkeypatch):
    services(duration_s=wav_seconds(groove_wav))
    gate = rights_module.require_rights

    def gate_before_download(rights, source):
        assert downloads(ytdlp()) == [], "audio was downloaded before the rights check"
        return gate(rights, source)

    monkeypatch.setattr(rights_module, "require_rights", gate_before_download)
    out = tmp_path / "out"
    song = ["song", "Test Groove", "--artist", "The Placeholders", "--rights", "own", "-o", out, "--formats", FAST]
    rc, text, err = cli(*song, "--library", tmp_path / "empty-library", "--candidates", 3)
    assert rc == 1 and "2. Audio: nothing in your library" in text  # the search names the links, nothing more
    official = re.search(r"--url '(\S+tg-official)'", err).group(1)
    rc, text, err = cli(*song, "--url", official)
    assert rc == 0, text + err
    assert kinds(events) == ["rights", "transcribe"]
    assert "watch?v=tg-official" in events[0][1]
    path, opts = events[1][1]
    assert path.parent == (tmp_path / "cache").resolve() and opts.bpm is None  # the metadata BPM is only a hint
    for line in ("1. Identified 'Test Groove' by The Placeholders",
                 "2. Audio: video: The Placeholders - Test Groove (Official Audio)", "3. Length: 0:",
                 "matches the identified recording", "4. Transcription (--rights own)",
                 "metadata BPM 118.5: a hint only", "check: MusicXML: OK", "check: MIDI: OK"):
        assert line in text, line
    assert len(downloads(ytdlp())) == 1
    s = Score.load(out / "test_groove.json")
    assert (s.title, s.artist, s.rights, s.status) == ("Test Groove", "The Placeholders", "own", "unverified_auto")
    assert s.transcriber == "Drum Agent (automatic)"
    assert "https://www.youtube.com/watch?v=tg-official" in s.source and "uploader The Placeholders" in s.source
    assert CC_BY in s.source
    ident = s.analysis["identified_as"]
    assert (ident["title"], ident["artist"], ident["bpm"]) == ("Test Groove", "The Placeholders", 118.5)
    assert set(ident["sources"]) == {"musicbrainz", "itunes", "deezer"}
    assert s.analysis["metadata_bpm"] == 118.5
    report = (out / "test_groove.report.md").read_text()
    assert "Rights basis: own" in report and "Metadata BPM 118.5 (Deezer): a hint only" in report
    assert "Identified as Test Groove - The Placeholders" in report


def test_song_without_rights_is_analysis_only(cli, services, ytdlp, events, groove_wav, tmp_path):
    services(duration_s=wav_seconds(groove_wav))
    out = tmp_path / "out"
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "-o", out,
                        "--library", tmp_path / "empty-library")
    assert rc == 0, text + err
    assert kinds(events) == ["analyze"]  # no rights gate needed, and no transcription
    assert "4. Analysis only (no --rights)" in text and '"tempo": "120 BPM' in text
    assert "--rights BASIS" in text and "licensed chart from the publisher" in text
    assert "Creative Commons" in text and "--rights licensed fits" in text and "Not applied" in text
    assert not out.exists()  # no chart files
    assert len(downloads(ytdlp())) == 1


def test_song_uses_the_metadata_bpm_only_when_asked(cli, services, ytdlp, events, groove_wav, tmp_path):
    services(duration_s=wav_seconds(groove_wav))
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--rights", "original", "-o",
                        tmp_path / "out", "--formats", "json", "--use-metadata-bpm",
                        "--url", "https://www.youtube.com/watch?v=tg-official")
    assert rc == 0, text + err
    assert events[-1][1][1].bpm == 118.5
    assert "tempo hint: the metadata BPM 118.5" in text
    s = Score.load(tmp_path / "out" / "test_groove.json")
    assert any("used as the tempo hint" in n for n in s.analysis["notes"])


def test_song_warns_when_the_length_is_off(cli, services, ytdlp, events, tmp_path):
    services(duration_s=192)  # the identified recording; the video is ~12 s
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--library", tmp_path / "none")
    assert rc == 0, text + err
    assert "but the identified recording is 3:12" in text and "another version" in text


def test_song_pick_chooses_another_candidate(cli, services, ytdlp, events, tmp_path):
    services()
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--pick", 3,
                        "--library", tmp_path / "none")
    assert rc == 0, text + err
    assert "using 3)" in text
    third = re.search(r"^   3\) video: .* <(\S+)>", text, re.MULTILINE).group(1)
    first = re.search(r"^   1\) video: .* <(\S+)>", text, re.MULTILINE).group(1)
    assert [c[-1] for c in downloads(ytdlp())] == [third] and third != first


def test_song_from_the_library_offline(cli, events, library, tmp_path, monkeypatch):
    monkeypatch.setattr(lookup, "http_get_json", lambda *a, **k: pytest.fail("network used with --no-online"))
    take = write_wav(library / "rips" / "The Placeholders - Test Groove.wav")
    before = take.read_bytes()
    out = tmp_path / "out"
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--no-online", "--library", library,
                        "--rights", "own", "-o", out, "--formats", "json", "--pick", 1)
    assert rc == 0, text + err
    assert "1. Identify: skipped (--no-online)" in text and "found in your library" in text
    assert kinds(events) == ["rights", "transcribe"] and events[1][1][0] == take.resolve()
    assert take.read_bytes() == before and cache_files(tmp_path) == []
    s = Score.load(out / "test_groove.json")
    assert s.source == f"audio file {take.resolve()}" and "identified_as" not in s.analysis


def test_song_with_a_direct_link_checks_rights_before_downloading(cli, events, web, tmp_path, monkeypatch):
    base, www, hits = web
    write_wav(www / "take.wav", seconds=2)
    monkeypatch.setattr(lookup, "http_get_json", canned_services(fail=("musicbrainz.org", "itunes.apple.com",
                                                                       "api.deezer.com")))
    gate = rights_module.require_rights

    def gate_before_download(rights, source):
        assert hits == [], "the link was fetched before the rights check"
        return gate(rights, source)

    monkeypatch.setattr(rights_module, "require_rights", gate_before_download)
    rc, text, err = cli("song", "Test Groove", "--url", base + "/take.wav", "--rights", "permission",
                        "-o", tmp_path / "out", "--formats", "json")
    assert rc == 0, text + err
    assert "no metadata service answered" in text  # identification failing is not fatal
    assert kinds(events) == ["rights", "transcribe"] and hits == ["/take.wav"]
    s = Score.load(tmp_path / "out" / "test_groove.json")
    assert s.source.startswith(f"direct download {base}/take.wav") and s.rights == "permission"


def test_song_refuses_a_streaming_link_before_any_lookup(cli, events, monkeypatch, tmp_path):
    monkeypatch.setattr(lookup, "http_get_json", lambda *a, **k: pytest.fail("looked up a refused source"))
    rc, _, err = cli("song", "Test Groove", "--url", "https://open.spotify.com/track/abc", "--rights", "own",
                     "-o", tmp_path / "out")
    assert rc == 1 and "DRM-protected" in err and "metadata only" in err and "Traceback" not in err
    assert events == [] and not (tmp_path / "out").exists()


def test_song_without_audio_says_how_to_get_some(cli, services, events, monkeypatch, tmp_path):
    services()
    monkeypatch.setattr(fetch, "find_ytdlp", lambda: None)
    rc, text, err = cli("song", "Test Groove", "--library", tmp_path / "none")
    assert rc == 1 and "1. Identified" in text
    assert "--audio FILE" in err and "pip install yt-dlp" in err
    assert events == []


@pytest.mark.parametrize("argv,message", [
    (["--rights", "own"], "give an output folder with -o"),
    (["--no-online", "--url", "https://example.com/a.wav"], "--url needs the network"),
    (["--url", "ftp://example.com/a.wav"], "--url takes an http(s) link"),
    (["--audio", "/no/such/file.wav"], "no such file"),
    (["--audio", __file__, "--pick", "2"], "nothing to choose"),
    (["--candidates", "0"], "--candidates is 1 to"),
])
def test_song_argument_errors(cli, events, monkeypatch, argv, message):
    monkeypatch.setattr(lookup, "http_get_json", lambda *a, **k: pytest.fail("network used before the check"))
    rc, _, err = cli("song", "Test Groove", *argv)
    assert rc == 1 and message in err and "Traceback" not in err
    assert events == []


def test_song_rejects_an_unknown_rights_basis(cli, events):
    rc, _, err = cli("song", "Test Groove", "--rights", "found_it_online", "-o", "out")
    assert rc == 2 and "invalid choice" in err


def test_documented_song_commands_parse():
    doc = (ROOT / "docs" / "SONG_LOOKUP.md").read_text()
    parser = build_parser()
    commands = [line.split(" #", 1)[0].strip() for line in doc.replace("\\\n", " ").splitlines()
                if line.strip().startswith("python -m drum_agent song ")]
    assert len(commands) >= 4
    for line in commands:
        parser.parse_args(shlex.split(line)[3:])


# ---- slow: the real analysis and transcription on the fake download ---------------------

@pytest.fixture(scope="module")
def fluid_wav(tmp_path_factory) -> Path:
    from drum_agent.synth import synthesize
    return synthesize(compile_spec(GROOVE), tmp_path_factory.mktemp("fluid") / "groove.wav", method="fluidsynth")


@pytest.mark.slow
@needs_fluidsynth
@needs_lilypond
def test_song_end_to_end_chart(cli, services, ytdlp, fluid_wav, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_WAV", str(fluid_wav))
    services(duration_s=wav_seconds(fluid_wav))
    out = tmp_path / "out"
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--rights", "own", "-o", out,
                        "--url", "https://www.youtube.com/watch?v=tg-official")
    assert rc == 0, text + err
    for name in ("test_groove.pdf", "test_groove.musicxml", "test_groove.mid", "test_groove.json",
                 "test_groove.report.md"):
        assert (out / name).exists(), name
    assert "check: MusicXML: OK" in text and "check: MIDI: OK" in text
    s = Score.load(out / "test_groove.json")
    assert s.title == "Test Groove" and s.rights == "own" and len(s.measures) >= 5
    assert {"hihat", "snare", "kick"} <= set(s.instruments_used())
    report = (out / "test_groove.report.md").read_text()
    assert "Automatic transcription, unverified" in report and "watch?v=tg-official" in report


@pytest.mark.slow
@needs_fluidsynth
def test_song_end_to_end_analysis(cli, services, ytdlp, fluid_wav, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_WAV", str(fluid_wav))
    services(duration_s=wav_seconds(fluid_wav))
    out = tmp_path / "out"
    rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "-o", out,
                        "--library", tmp_path / "none")
    assert rc == 0, text + err
    info = json.loads(text[text.index("   {\n"):text.index("\n   }\n") + 5])
    assert info["meter"].startswith("4/4")
    assert abs(float(info["tempo"].split()[0]) - 120) < 6
    assert not {"measures", "hits", "events"} & set(info)
    assert not out.exists()


# ---- review regressions -------------------------------------------------------------

def test_rights_after_a_video_search_needs_the_exact_link(cli, services, ytdlp, events, tmp_path):
    # A basis is a statement about one recording; the first search result may be a reupload or
    # a cover, and the search runs again (and can rank differently) on the next run, so a video
    # is named by its link, never by its place in the list.
    services()
    for pick in ((), ("--pick", 1)):
        rc, text, err = cli("song", "Test Groove", "--artist", "The Placeholders", "--rights", "own",
                            "-o", tmp_path / "out", "--library", tmp_path / "none", *pick)
        assert rc == 1 and "--url 'https://www.youtube.com/watch?v=tg-official'" in err, err
        assert "--url 'https://www.youtube.com/watch?v=tg-cover'" in err and "using" not in text
    assert kinds(events) == [] and downloads(ytdlp()) == []


def test_rights_with_one_library_match_still_needs_a_pick(cli, events, library, tmp_path, monkeypatch):
    # One fuzzy match (here another band's live take) is still a search result, not the recording
    # the user stated a basis for.
    monkeypatch.setattr(lookup, "http_get_json", lambda *a, **k: pytest.fail("network used with --no-online"))
    write_wav(library / "rips" / "Cover Band - Test Groove (Live).wav")
    rc, text, err = cli("song", "Test Groove", "--no-online", "--library", library, "--rights", "own",
                        "-o", tmp_path / "out", "--formats", "json")
    assert rc == 1 and "--pick N" in err and "1) your library:" in text and "Cover Band" in text
    assert events == [] and not (tmp_path / "out").exists()


def test_drumless_and_backing_tracks_rank_last():
    names = ["The Placeholders - Test Groove (Drumless)", "The Placeholders - Test Groove (Drum Backing Track)",
             "The Placeholders - Test Groove (Official Audio)", "The Placeholders - Test Groove (No Drums)",
             "The Placeholders - Test Groove (Instrumental)"]
    v = [VideoCandidate(url=f"https://www.youtube.com/watch?v={i}", title=n, duration_s=192)
         for i, n in enumerate(names)]
    ranked = fetch.rank_videos(v, "The Placeholders Test Groove", expected_duration=192)
    assert ranked[0].title.endswith("(Official Audio)")
    assert all(r.score < ranked[0].score - 0.5 for r in ranked[1:] if "rums" in r.title)


def test_a_page_with_several_recordings_is_refused(monkeypatch):
    infos = [{"webpage_url": f"https://example.com/album#{i}", "title": f"Track {i}", "id": f"t{i}"} for i in range(3)]
    out = "\n".join(json.dumps(i) for i in infos)
    monkeypatch.setattr(fetch, "_run_ytdlp", lambda exe, args, timeout: subprocess.CompletedProcess(args, 0, out, ""))
    with pytest.raises(FetchError, match="holds 3 recordings"):
        fetch.video_info("https://example.com/album", ytdlp=["yt-dlp"])


def test_ytdlp_downloads_into_the_cache_by_folder_not_template(monkeypatch, tmp_path):
    cache = tmp_path / "cache_100%_sure"
    seen = {}

    def run(exe, args, timeout):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 1, "", "stop here")
    monkeypatch.setattr(fetch, "_run_ytdlp", run)
    with pytest.raises(FetchError):
        fetch.download_with_ytdlp("https://www.youtube.com/watch?v=x", cache, ytdlp=["yt-dlp"])
    a = seen["args"]
    assert a[a.index("-P") + 1] == str(cache.resolve()) and "%" not in a[a.index("-o") + 1].split("%(")[0]
    assert a[a.index("--playlist-items") + 1] == "1"


def test_redirect_to_ftp_is_not_followed(tmp_path):
    import http.server
    import threading

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "ftp://127.0.0.1:9/secret.wav")
            self.end_headers()

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(FetchError, match=r"HTTP 302 \(redirect to a ftp URL refused\)"):
            fetch.fetch_audio(f"http://127.0.0.1:{server.server_port}/take.wav", tmp_path / "cache", timeout=3)
    finally:
        server.shutdown()
        server.server_close()


def test_each_redirect_is_checked_before_it_is_followed(monkeypatch, tmp_path):
    # Every host name resolves to this local server, and no proxy is used: nothing leaves the machine.
    import http.server
    import socket
    import urllib.request
    hits = []
    hops = {"example.test/song.mp3": "http://p.scdn.co/mp3-preview/abc",  # straight to a streaming CDN
            "example.test/hop.mp3": "http://p.scdn.co/hop",  # through one, to a host that isn't listed
            "p.scdn.co/hop": "http://other.test/final.mp3",
            "example.test/enc.mp3": "http://p.s%63dn.co/mp3-preview/abc"}  # urllib asks for p.scdn.co

    class Hops(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            here = self.headers["Host"].split(":")[0] + self.path
            hits.append(here)
            if here in hops:
                self.send_response(302)
                self.send_header("Location", hops[here])
                self.end_headers()
                return
            body = b"ID3" + b"\0" * 4000
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Hops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: real("127.0.0.1", server.server_port,
                                                                                 *a, **k))
    monkeypatch.setattr(urllib.request, "getproxies", dict)  # no proxy: {}
    try:
        for start in ("example.test/song.mp3", "example.test/hop.mp3", "example.test/enc.mp3"):
            hits.clear()
            with pytest.raises(FetchError, match="Spotify streams are DRM-protected"):
                fetch.fetch_audio(f"http://{start}", tmp_path / "cache", timeout=3)
            assert hits == [start]  # the streaming host was never asked
        assert fetch.fetch_audio("http://other.test/final.mp3", tmp_path / "cache", timeout=3).path.is_file()
    finally:
        server.shutdown()
        server.server_close()


def test_a_download_that_slows_to_a_trickle_is_given_up(monkeypatch, tmp_path):
    clock = iter(range(0, 10_000, 10))  # 10 s pass per read
    monkeypatch.setattr(fetch.time, "monotonic", lambda: next(clock))

    class Trickle:
        def read(self, n):
            return b"RIFF"
    with pytest.raises(FetchError, match="too slow"):
        fetch._stream_to(Trickle(), tmp_path / "take.wav", 10 ** 9, "http://example.com/take.wav")
    assert list(tmp_path.iterdir()) == []  # no partial file left behind


def test_a_trickling_server_is_given_up(monkeypatch, tmp_path):
    # A real socket: HTTPResponse.read(n) waits for all n bytes (every byte restarts the socket
    # timeout), so the rate has to be checked after each receive, not after each 64 KiB.
    import http.server
    import time

    class Trickle(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(1 << 20))
            self.end_headers()
            try:
                for _ in range(60):  # 1 kB every 0.1 s (10 kB/s) for 6 s, then the connection drops
                    self.wfile.write(b"\0" * 1024)
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    monkeypatch.setattr(fetch, "SLOW_GRACE_S", 0.5)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        t0 = time.monotonic()
        with pytest.raises(FetchError, match="too slow"):
            fetch.fetch_audio(f"http://127.0.0.1:{server.server_port}/take.wav", tmp_path / "cache", timeout=10)
        assert time.monotonic() - t0 < 4, "the rate check waited for a whole chunk"
    finally:
        server.shutdown()
        server.server_close()
    assert cache_files(tmp_path) == []


def test_a_web_page_sent_in_small_pieces_is_still_recognised(tmp_path):
    class Pieces:  # what a socket gives when the page arrives a few bytes at a time
        def __init__(self, body):
            self.body = body

        def read1(self, n):
            piece, self.body = self.body[:3], self.body[3:]
            return piece
        read = read1
    with pytest.raises(FetchError, match="sent a web page"):
        fetch._stream_to(Pieces(b"\n  <!DOCTYPE html><html><body>Sign in</body></html>"), tmp_path / "take.mp3",
                         10 ** 6, "http://example.com/take.mp3")
    assert list(tmp_path.iterdir()) == []


def test_a_web_page_given_as_a_link_is_checked_like_a_video_page(web, tmp_path, monkeypatch):
    # A page on a host that isn't a known video site still goes to yt-dlp: it must be one
    # recording, and its title, uploader and licence go on the source line.
    base, www, _ = web
    for name in ("album.html", "single.html"):
        (www / name).write_text("<!doctype html><title>a page</title>")
    calls = []

    def run(exe, args, timeout):
        calls.append(args)
        page = args[-1]
        if "--dump-json" in args:
            n = 2 if page.endswith("album.html") else 1
            infos = [{"webpage_url": page if n == 1 else f"{page}#t{i}", "title": f"Track {i}", "id": f"t{i}",
                      "uploader": "The Placeholders", "license": CC_BY} for i in range(1, n + 1)]
            return subprocess.CompletedProcess(args, 0, "\n".join(json.dumps(i) for i in infos), "")
        saved = Path(args[args.index("-P") + 1]) / "Track_1-t1.wav"
        saved.write_bytes(b"RIFF")
        return subprocess.CompletedProcess(args, 0, f"{saved}\n", "")
    monkeypatch.setattr(fetch, "_run_ytdlp", run)
    with pytest.raises(FetchError, match="holds 2 recordings"):
        fetch.fetch_audio(base + "/album.html", ytdlp=["yt-dlp"])
    assert downloads(calls) == []
    audio = fetch.fetch_audio(base + "/single.html", ytdlp=["yt-dlp"])
    assert (audio.origin, audio.title, audio.uploader, audio.license) == ("video", "Track 1", "The Placeholders",
                                                                           CC_BY)
    assert downloads(calls)[0][-1] == base + "/single.html"


def test_the_suggested_rights_command_keeps_the_source_and_options():
    import argparse

    from drum_agent.song import run
    parser = build_parser()
    given = parser.parse_args([
        "song", "--artist", "The Placeholders", "--title=-Untitled-", "--transcriber", "Me", "--bpm", "120",
        "--time-signature", "6/8", "--downbeat", "125.0625", "--feel", "swing", "--drums-only", "--sensitivity", "1.5",
        "--no-32nds", "--start", "12.5", "--end", "60", "--sections", "Intro:1,Verse:5", "--chart-type",
        "performance_chart", "--detector", "nmf", "--use-metadata-bpm", "--stem", "tg", "--formats", "pdf,midi",
        "--paper", "a4", "--staff-size", "18", "--repeats", "none", "--bars-per-line", "3", "--no-legend",
        "--midi-timing", "performed", "--kit", "my kit.json", "--voicing", "hands-up", "--candidates", "3",
        "--library", "/music", "-o", "out dir", "--", "-ism"])
    video = AudioSource(Path("/cache/x.wav"), "video", url="https://www.youtube.com/watch?v=tg-official")
    cmd = run._rerun_command(given, video)
    assert "--url 'https://www.youtube.com/watch?v=tg-official'" in cmd and "/cache/x.wav" not in cmd
    assert "--rights BASIS" in cmd and cmd.endswith(" -- -ism")
    again = parser.parse_args(shlex.split(cmd.replace("BASIS", "own"))[3:])
    assert (again.url, again.audio, again.rights) == (video.url, None, "own")
    source = {"audio", "url", "library", "candidates", "pick", "rights"}  # replaced by the source and the basis
    for name, value in vars(given).items():
        if name not in source:
            assert getattr(again, name) == value, name
    # ... and that holds for every option `song` has, not only the ones given here
    song = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices["song"]
    options = {a.dest for a in song._actions if a.option_strings and a.dest != "help"}
    assert options - {attr for _, attr, _ in run._CARRIED} == source | {"out"}
    defaults = {a.dest: a.default for a in song._actions}
    assert [(attr, default) for _, attr, default in run._CARRIED if defaults[attr] != default] == []
    mine = AudioSource(Path("/music/x.wav"), "file")
    mine_cmd = run._rerun_command(given, mine).replace("BASIS", "own")
    assert parser.parse_args(shlex.split(mine_cmd)[3:]).audio == "/music/x.wav"


def test_ranking_prefers_the_album_track_and_the_artists_own_uploads():
    """Titles, channels and lengths as YouTube's search returned them for "Back in Black" (Oct 2026),
    plus the kinds of upload that must never win."""
    vids = [VideoCandidate(url=f"u{k}", title=t, channel=c, duration_s=d) for k, (t, c, d) in enumerate([
        ("AC/DC - Back In Black (Official 4K Video)", "AC/DC", 254),
        ("AC/DC - Back In Black (Lyrics)", "7clouds Rock", 252),
        ("AC/DC - Back In Black", "Rock And Metal Tv", 256),
        ("Back In Black", "AC/DC - Topic", 255),
        ("AC/DC - Back In Black (Live At River Plate, December 2009)", "AC/DC", 270),
        ("AC/DC - Back In Black (Drum Cover)", "Drummer Kid", 255),
        ("Back In Black - Drumless Backing Track", "Backing Tracks", 255),
    ])]
    ranked = fetch.rank_videos(vids, "AC/DC Back in Black", 255, asked="Back in Black AC/DC", artist="AC/DC")
    assert [v.channel for v in ranked[:3]] == ["AC/DC - Topic", "AC/DC", "Rock And Metal Tv"]
    assert [v.title for v in ranked[-3:]] == ["AC/DC - Back In Black (Live At River Plate, December 2009)",
                                              "AC/DC - Back In Black (Drum Cover)",
                                              "Back In Black - Drumless Backing Track"]
    # Asked for the live version: the live upload is no longer pushed down.
    live = fetch.rank_videos(vids, "AC/DC Back in Black live", None, asked="Back in Black live River Plate",
                             artist="AC/DC")
    assert live[0].title.startswith("AC/DC - Back In Black (Live At River Plate")
