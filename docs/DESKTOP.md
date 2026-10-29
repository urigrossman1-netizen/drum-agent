# The Drum Agent app (Windows)

The app is the studio ([WEB_APP.md](WEB_APP.md)) running on a person's own computer, in
personal mode: a song typed by name is found on YouTube, downloaded and charted for the
user's own practice. Download: the release "Drum Agent for Windows"
(`releases/latest/download/DrumAgent-Setup.exe`).

## How it runs

`drum_agent/desktop.py` (`python -m drum_agent app`, and the installed `DrumAgent.exe`):

- **Personal mode** (`DRUM_AGENT_MODE=personal`) on `127.0.0.1` at a free port: nothing
  listens on the network.
- **Tools** shipped beside it, first on `PATH`: LilyPond 2.26.0 (`tools/lilypond`, used
  through `DRUM_AGENT_LILYPOND`), FFmpeg (`tools/ffmpeg/bin`), Deno (`tools/deno`, the
  JavaScript runtime yt-dlp needs for YouTube) and yt-dlp. yt-dlp is copied to the
  user's folder (`bin/`) on the first start, where it can replace itself: `yt-dlp -U`
  runs in the background at most once a day, because YouTube changes often and an old
  yt-dlp stops working. A newer installer's yt-dlp replaces an older copy, never a
  self-updated newer one.
- **Drum separation** inside the app: PyTorch (CPU) and demucs, with the HTDemucs weights
  in `tools/torch` (`TORCH_HOME`), so the first song downloads no model. A band
  recording's drums are separated before they are transcribed; it takes about as long as
  the song on a two-thread CPU, less on a bigger one. Measured in `docs/MODELS.md`.
- **Data** in `%LOCALAPPDATA%\Drum Agent` (a Mac: `~/Library/Application Support/Drum
  Agent`): `studio/` (the charts, decoded recordings and database), `logs/drum-agent.log`,
  `cache/`. Uninstalling keeps it.
- **Window**: the studio in its own window (pywebview, Edge WebView2), 1360 x 900, or
  maximized on a screen with less room than that (`window_size`). Without a web view,
  a small window with "Open Drum Agent" (the browser) and "Quit". Closing the window
  stops the app. A second start opens the running app (`app.json` holds its port).
- **Internet**: identifying songs (MusicBrainz, iTunes, Deezer), searching and
  downloading from YouTube, updating yt-dlp. Nothing else; no accounts, no telemetry.

## Building it

`.github/workflows/windows-app.yml` builds on a Windows runner (Python 3.12):

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install ".[desktop]" demucs pyinstaller pillow && pip uninstall -y yt-dlp
python packaging/make_icon.py                                   # build/drum-agent.ico
pyinstaller packaging/drum_agent.spec --noconfirm --clean       # dist/DrumAgent/
python packaging/fetch_tools.py --platform windows --dest dist/DrumAgent/tools --separation
iscc /DAppVersion=1.0.0 packaging\windows\DrumAgent.iss         # dist/DrumAgent-Setup.exe
```

The yt-dlp Python package is left out: the app ships `yt-dlp.exe`, which can update
itself. (In a packaged app `sys.executable` is the app, so `python -m yt_dlp` is never
tried there.) `tools/NOTICES.txt` lists each tool's licence and source: LilyPond GPL-3.0+,
FFmpeg LGPL-2.1+ (an LGPL build), yt-dlp Unlicense, Deno MIT, the HTDemucs model MIT (run
with PyTorch, BSD, and demucs, MIT). The installer is about 420 MB.

## How it is tested

Every build, before anything is published:

1. `packaging/smoke_test.py` drives the built app (`DrumAgent.exe --headless`) through its
   API: every tool ready (LilyPond, FFmpeg, the classifier, the database), personal mode,
   yt-dlp found, drum separation installed; a beat generated and engraved; a recording
   uploaded, its drums separated by HTDemucs, transcribed and engraved; a YouTube search
   for "Back in Black"; and that song charted from its name.
2. The installer is built, installed silently, and the installed app is opened normally
   (its window): it must start its studio. A screenshot of the screen is printed in the
   job's log (base64 JPEG after `SCREENSHOT:`).
3. Only then is `DrumAgent-Setup.exe` published, as a new release under the run's own tag
   (`app-windows-<run>`); the older releases are deleted only after it is up, so the
   download link always has a file.

What the build machine cannot check: **the YouTube download**. YouTube refuses downloads
from cloud servers ("Sign in to confirm you're not a bot"; checked from GitHub's Linux and
Windows runners), so there step 1 requires that refusal to come back as a clear
`download_failed`, not a crash. On a home connection the download works with an
up-to-date yt-dlp; the rest of the path (download, decode, transcribe, chart) is tested
with a stand-in for yt-dlp (`tests/test_web.py`, `tests/e2e/find.e2e.js`).

## When something goes wrong

- **"Windows protected your PC"**: the installer isn't code-signed yet. More info → Run
  anyway.
- **YouTube asks to sign in / a download fails**: yt-dlp may be out of date; it updates
  itself within a day of starting the app (restart the app to try again). The song page
  also takes a pasted YouTube link, and an upload of a recording you have.
- **The log**: `%LOCALAPPDATA%\Drum Agent\logs\drum-agent.log`.

## Next

A Mac build (`fetch_tools.py --platform mac`, a `.app` in a `.dmg`), then using the app
from a phone on the same Wi-Fi.
