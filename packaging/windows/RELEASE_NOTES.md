## Drum Agent for Windows

Type a song and get its drum chart. Drum Agent finds the recording among your own music
files, listens to the drums and writes them out as real drum sheet music you can play
along with, print and export (PDF, MusicXML, MIDI). Or drop in any recording you have, or
describe a beat ("a funky groove at 96 BPM with ghost notes") and get an original chart.

### Install
1. Download **DrumAgent-Setup.exe** below.
2. Open it. Windows may say "Windows protected your PC" because the app is new and not
   signed yet: click **More info**, then **Run anyway**.
3. Click through the installer. Drum Agent opens, and it's in the Start menu.

Windows 10 or 11, 64-bit. No administrator rights needed. About {size_gb} GB on disk.

### Good to know
- Songs are looked for in your Music folder (and in the folders named by the
  `DRUM_AGENT_MUSIC_DIRS` environment variable). A song you don't have as a file can be
  uploaded from anywhere on your computer.
- Charts of songs you didn't write are for your own practice. They are marked "Transcribed
  for personal practice. Not for distribution." Posting them publicly needs the music
  publisher's permission. Beats you make, and charts of your own songs, are yours to share.
- Everything happens on your computer. The app connects to the internet only to identify
  songs (MusicBrainz, iTunes, Deezer): names and lengths, never audio. YouTube and
  streaming services are never downloaded from.
- In a full band recording, Drum Agent first separates the drums from the other instruments
  (the HTDemucs model, on your computer), then writes out what it hears. The app shows each
  step while it works.
- Automatic transcription is not perfect: bars it is unsure about are marked for you to
  check by ear.
- Your charts are kept in `%LOCALAPPDATA%\Drum Agent` (they stay if you uninstall).

Ships with LilyPond (GPL), FFmpeg (LGPL) and the HTDemucs model (MIT, run with PyTorch,
BSD): see `tools\NOTICES.txt` in the install folder.
