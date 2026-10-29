"""Check a running Drum Agent app end to end through its API (the packaged app, in CI).

    python packaging/smoke_test.py http://127.0.0.1:8765 --take take.wav [--expect-separation] [--search]

The app must run with DRUM_AGENT_MUSIC_DIRS naming a folder that holds the take as
"Drum Agent - Smoke Test Song.wav".

1. health: every tool ready (LilyPond, ffmpeg, ffprobe, the classifier, the database), the
   personal mode, and the music folder found;
2. a beat from a description, engraved (a PDF comes back);
3. a recording uploaded with a rights basis, transcribed (the drums separated from the band
   first, with --expect-separation) and engraved;
4. a song typed by name, found in the music folder and charted for personal practice;
5. with --search, a real catalog search (MusicBrainz, iTunes, Deezer) for a song: the
   results and every provider's state.

Standard library only. Prints each result; exits 1 at the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class Failed(Exception):
    pass


def check(cond: bool, what: str) -> None:
    if not cond:
        raise Failed(what)
    print(f"ok - {what}", flush=True)


class App:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, *, json_body=None, data: bytes | None = None,
             headers: dict | None = None, raw: bool = False):
        h = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
        except urllib.error.HTTPError as exc:
            raise Failed(f"{method} {path}: HTTP {exc.code} {exc.read()[:400]!r}") from None
        return body if raw else json.loads(body)

    def wait(self, job: dict, timeout: float = 900) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            job = self.call("GET", f"/api/jobs/{job['id']}")
            if job["status"] in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(1)
        raise Failed(f"job {job['id']} still {job['status']} after {timeout:.0f} s")

    def pdf(self, chart_id: str) -> bytes:
        chart = self.call("GET", f"/api/charts/{chart_id}")
        return self.call("GET", chart["files"]["chart.pdf"], raw=True)


def multipart(fields: dict[str, str], name: str, filename: str, content: bytes) -> tuple[bytes, dict]:
    b = "----drumagent" + uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"}


def run(app: App, take: Path, expect_separation: bool = False, search: bool = False) -> None:
    h = app.call("GET", "/api/health")
    for name, c in h["checks"].items():
        check(c["ok"], f"{name} ready {c.get('version') or ''}".strip())
    check(h["mode"] == "personal", "the app runs in personal mode")
    check(h["library"]["available"], f"songs can be found in the music folders ({h['library']['detail']})")
    if expect_separation:
        check(h["separation"]["available"], f"the drum separation is installed ({h['separation']['model']})")

    r = app.call("POST", "/api/beats", json_body={"prompt": "A rock beat at 120 BPM, 4 bars, crash on the one"})
    job = app.wait(r["job"])
    check(job["status"] == "succeeded", f"a beat is generated ({job.get('error') or 'chart ' + str(job['chart_id'])})")
    check(app.pdf(job["chart_id"])[:4] == b"%PDF", "the beat is engraved by LilyPond (PDF)")

    song = app.call("POST", "/api/songs", json_body={"title": "Smoke Test Take", "artist": "Drum Agent"})["song"]
    body, headers = multipart({"rights": "own"}, "file", "take.wav", take.read_bytes())
    r = app.call("POST", f"/api/songs/{song['id']}/upload", data=body, headers=headers)
    t0 = time.time()
    job = app.wait(r["job"])
    check(job["status"] == "succeeded", f"an uploaded recording is transcribed ({job.get('error') or 'ok'}, "
                                        f"{time.time() - t0:.0f} s)")
    chart = app.call("GET", f"/api/charts/{job['chart_id']}")
    if expect_separation:
        notes = chart["summary"].get("notes") or []
        check(bool(notes) and notes[0].startswith("The drums were separated from the band"),
              "the drums were separated from the band first (HTDemucs ran in the app)")
    check(chart["bars"] >= 4 and app.pdf(chart["id"])[:4] == b"%PDF",
          f"its chart is engraved: {chart['bars']} bars, status {chart['status']}")

    song = app.call("POST", "/api/songs", json_body={"title": "Smoke Test Song", "artist": "Drum Agent"})["song"]
    found = app.call("GET", f"/api/songs/{song['id']}/library")
    check([f["name"] for f in found["files"]][:1] == ["Drum Agent - Smoke Test Song.wav"],
          f"the song is found in the music folder ({', '.join(found['folders'])})")
    r = app.call("POST", f"/api/songs/{song['id']}/library", json_body={"personal": True})
    job = app.wait(r["job"])
    check(job["status"] == "succeeded", f"it is charted from the file ({job.get('error') or 'ok'})")
    chart = app.call("GET", f"/api/charts/{job['chart_id']}")
    check(chart["shareable"] is False and app.pdf(chart["id"])[:4] == b"%PDF",
          "its chart is engraved and marked for personal practice")

    if search:
        r = app.call("GET", "/api/search?q=" + urllib.parse.quote("Back in Black - AC/DC"))
        for st in r["providers"]:
            print(f"   {st['provider']}: {st['state']} {st.get('detail') or ''}".rstrip())
        for x in r["results"][:3]:
            print(f"   {x['title']} | {x['artist']} | {x.get('album') or '-'} | {x.get('duration_s')} s | {x.get('url')}")
        check(any(st["state"] == "ok" for st in r["providers"]) and len(r["results"]) >= 1,
              "a real catalog search answers (MusicBrainz, iTunes, Deezer)")


def main() -> int:
    p = argparse.ArgumentParser(description="check a running Drum Agent app")
    p.add_argument("base", help="e.g. http://127.0.0.1:8765")
    p.add_argument("--take", type=Path, required=True, help="a WAV recording of drums to upload")
    p.add_argument("--search", action="store_true", help="also a real catalog search (needs the internet)")
    p.add_argument("--expect-separation", action="store_true", help="the drum separation must be installed and run")
    args = p.parse_args()
    try:
        run(App(args.base), args.take, args.expect_separation, args.search)
    except Failed as exc:
        print(f"FAILED - {exc}", flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
