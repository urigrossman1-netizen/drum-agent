# How to use Drum Agent (on your Windows PC)

## Start it

- Double-click **Drum Agent (dev)** on your desktop. The studio opens in its own window.
- Or open it in your web browser: run `scripts\windows\studio.cmd`, then go to
  <http://127.0.0.1:8000>. Only this computer can open that address.

The first start takes a little longer, because it prepares the example chart.

## Make a chart of a song

1. Click **Create**, then **Song to Chart**.
2. Type the song and the artist, then press Enter.
3. Pick the right recording from the list. If it isn't listed, use **Add song** at the bottom.
4. On the song's page you have two ways to give it the audio:
   - **Find it and make the chart.** If the song file is in your **Music** folder,
     Drum Agent finds it by itself. Tick the box that says the chart is for your own
     practice. To search other folders too, add them to `DRUM_AGENT_MUSIC_DIRS` in the
     `.env` file.
   - **Upload a recording.** Drop in a WAV, MP3, FLAC, M4A, AAC or OGG file (up to 200 MB
     and 20 minutes). Then choose why you're allowed to transcribe it: your own recording,
     permission, a licence, public domain, your own song, or your own practice.
5. Watch the steps:
   1. reading the audio;
   2. separating the drums from the band (the longest step: about as long as the song, or a
      little more on a laptop);
   3. detecting the strokes;
   4. finding the tempo and the bars;
   5. engraving.
6. The chart opens. Bars marked **(?)** are the ones to check by ear first.

Drum Agent never downloads audio from YouTube, Spotify or other streaming services: their
rules don't allow it. YouTube and Spotify help you find and identify songs, and a YouTube
result plays in YouTube's own player once the key is set (see below).

## Practise with the chart

- **Play** the drums alone, the recording with the chart, or the recording alone.
- **Speed**, **loop**, **metronome** and **count-in** are in the player bar.
- Click a bar to start from there. The current bar lights up as it plays.

## Fix what's wrong

- Click a bar, then use the grid under the notation to add or remove hits, or mark accents,
  ghost notes and flams. Undo with Ctrl+Z.
- **Save** keeps a new version. Earlier versions, including the computer's original
  transcription, stay available.

## Export

**PDF** (to print), **MusicXML** (opens in MuseScore, Sibelius, Dorico), **MIDI**.

## Make an original beat

**Create** → **Create a Beat**, then describe it in your own words, for example "a
powerful pop-punk beat at 165 BPM with a two-bar tom fill every eight bars".

## Turn on the extras (optional keys)

Open the `.env` file in the project folder with Notepad. Paste each key after its `=`,
save, and restart Drum Agent. **Settings** in the studio shows each one as configured or
not.

| Key | What it turns on | Where to get it | Cost |
|---|---|---|---|
| `YOUTUBE_API_KEY` | YouTube results in song search, and the YouTube player | Google Cloud console → APIs & Services → enable **YouTube Data API v3** → Credentials → Create credentials → API key | free (about 100 searches a day) |
| `ANTHROPIC_API_KEY` | Claude: names the sections (Intro, Verse, Chorus…), reads beat descriptions and typed edit requests. It never writes notes | console.anthropic.com → API Keys → Create Key (add credit first) | pay per use; a few cents for many charts |
| `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` | Spotify results in song search (song details only) | developer.spotify.com → Dashboard → Create app → Settings | free |

Keep keys private: never paste them into a chat, a screenshot or a file you share. The
`.env` file is never uploaded to GitHub.

## When something goes wrong

- **"No drum strokes detected"**: is there a drum part? Try a different file.
- **Wrong tempo or bar lines**: check the tempo on the chart. Re-transcribing with a tempo
  hint is coming to the studio; for now the command line takes `--bpm`.
- **Anything else**: the app's log is in `%LOCALAPPDATA%\Drum Agent\logs` (the window app)
  or in the window where `studio.cmd` runs.
