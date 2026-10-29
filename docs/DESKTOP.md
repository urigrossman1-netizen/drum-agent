# The Drum Agent app (Windows)

The app is the studio ([WEB_APP.md](WEB_APP.md)) running on a person's own computer, in
personal mode: a song typed by name is found among the user's own audio files (their
music folders) and charted for their own practice; any other recording they have can be
dropped in. Download: the release "Drum Agent for Windows"
(`releases/latest/download/DrumAgent-Setup.exe`).

## How it runs

`drum_agent/desktop.py` (`python -m drum_agent app`, and the installed `DrumAgent.exe`):

- **Personal mode** (`DRUM_AGENT_MODE=personal`) on `127.0.0.1` at a free port: nothing
  listens on the network.
- **Tools** shipped beside it, first on `PATH`: LilyPond 2.26.0 (`tools/lilypond`, used
  through `DRUM_AGENT_LILYPOND`) and FFmpeg (`tools/ffmpeg/bin`).
- **Music folders**: `~/Music` (on Windows `C:\Users\<you>\Music`) and the folders named in
  `DRUM_AGENT_MUSIC_DIRS`, read only (`drum_agent/web/library.py`).
- **Drum separation** inside the app: PyTorch (CPU) and demucs, with the HTDemucs weights
  and their bag file in `tools/torch/hub/checkpoints` (`TORCH_HOME`). They are loaded from
  there (`separate.shipped()`; demucs would otherwise download its model from the Hugging
  Face Hub), so no song downloads a model and the separation works offline. A band
  recording's drums are separated before they are transcribed; it takes about as long as
  the song on a two-thread CPU, less on a bigger one. Measured in `docs/MODELS.md`.
- **Data** in `%LOCALAPPDATA%\Drum Agent` (a Mac: `~/Library/Application Support/Drum
  Agent`): `studio/` (the charts, decoded recordings and database), `logs/drum-agent.log`,
  `cache/`. Uninstalling keeps it.
- **Window**: the studio in its own window (pywebview, Edge WebView2), 1360 x 900, or
  maximized on a screen with less room than that (`window_size`). Without a web view,
  a small window with "Open Drum Agent" (the browser) and "Quit". Closing the window
  stops the app. A second start opens the running app (`app.json` holds its port).
- **Internet**: identifying songs (MusicBrainz, iTunes, Deezer; Spotify and the YouTube
  Data API when keys are set): metadata only. No audio is downloaded from anywhere; no
  accounts, no telemetry.

## Building it

`.github/workflows/windows-app.yml` builds on a Windows runner (Python 3.12):

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install ".[desktop]" demucs pyinstaller pillow
python packaging/make_icon.py                                   # build/drum-agent.ico
pyinstaller packaging/drum_agent.spec --noconfirm --clean       # dist/DrumAgent/
python packaging/fetch_tools.py --platform windows --dest dist/DrumAgent/tools --separation
iscc /DAppVersion=1.0.0 packaging\windows\DrumAgent.iss         # dist/DrumAgent-Setup.exe
```

`tools/NOTICES.txt` lists each tool's licence and source: LilyPond GPL-3.0+, FFmpeg
LGPL-2.1+ (an LGPL build), the HTDemucs model MIT (run with PyTorch, BSD, and demucs,
MIT). The installer is about 420 MB.

## How it is tested

Every build, before anything is published:

1. `packaging/smoke_test.py` drives the built app (`DrumAgent.exe --headless`) through its
   API: every tool ready (LilyPond, FFmpeg, the classifier, the database), personal mode,
   the music folder found, drum separation installed; a beat generated and engraved; a
   recording uploaded, its drums separated by HTDemucs, transcribed and engraved; a song
   typed by name found in the music folder and charted; and a real catalog search
   (MusicBrainz, iTunes, Deezer) for "Back in Black".
2. The installer is built, installed silently, and the installed app is opened normally
   (its window): it must start its studio. A screenshot of the screen is printed in the
   job's log (base64 JPEG after `SCREENSHOT:`).
3. Only then is `DrumAgent-Setup.exe` published, as a new release under the run's own tag
   (`app-windows-<run>`); the older releases are deleted only after it is up, so the
   download link always has a file.

## When something goes wrong

- **"Windows protected your PC"**: the installer isn't code-signed yet. More info → Run
  anyway.
- **The song isn't found**: the file must be in a music folder and named or tagged with
  the song's title and artist (`Artist - Title.mp3`, or tags). Set `DRUM_AGENT_MUSIC_DIRS`
  for other folders, or upload the file on the song page.
- **The log**: `%LOCALAPPDATA%\Drum Agent\logs\drum-agent.log`.

## Next

A Mac build (`fetch_tools.py --platform mac`, a `.app` in a `.dmg`), then using the app
from a phone on the same Wi-Fi.
