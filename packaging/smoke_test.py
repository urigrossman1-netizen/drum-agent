"""Check a running Drum Agent app end to end through its API (the packaged app, in CI).

    python packaging/smoke_test.py http://127.0.0.1:8765 --take take.wav [--expect-download]

1. health: every tool ready (LilyPond, ffmpeg, ffprobe, the classifier, the database), the
   personal mode, and songs findable online (yt-dlp found);
2. a beat from a description, engraved (a PDF comes back);
3. a recording uploaded with a rights basis, transcribed and engraved;
4. a YouTube search for a song (titles and lengths only);
5. finding and charting that song. On a home connection it is charted. GitHub's servers are
   refused by YouTube ("Sign in to confirm you're not a bot"): that must come back as a
   clear download_failed, not a crash. --expect-download makes the chart required.

Standard library only. Prints each result; exits 1 at the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
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


def run(app: App, take: Path, expect_download: bool) -> None:
    h = app.call("GET", "/api/health")
    for name, c in h["checks"].items():
        check(c["ok"], f"{name} ready {c.get('version') or ''}".strip())
    check(h["mode"] == "personal", "the app runs in personal mode")
    check(h["online"]["available"], f"songs can be found online ({h['online']['detail']})")

    r = app.call("POST", "/api/beats", json_body={"prompt": "A rock beat at 120 BPM, 4 bars, crash on the one"})
    job = app.wait(r["job"])
    check(job["status"] == "succeeded", f"a beat is generated ({job.get('error') or 'chart ' + str(job['chart_id'])})")
    check(app.pdf(job["chart_id"])[:4] == b"%PDF", "the beat is engraved by LilyPond (PDF)")

    song = app.call("POST", "/api/songs", json_body={"title": "Smoke Test Take", "artist": "Drum Agent"})["song"]
    body, headers = multipart({"rights": "own"}, "file", "take.wav", take.read_bytes())
    r = app.call("POST", f"/api/songs/{song['id']}/upload", data=body, headers=headers)
    job = app.wait(r["job"])
    check(job["status"] == "succeeded", f"an uploaded recording is transcribed ({job.get('error') or 'ok'})")
    chart = app.call("GET", f"/api/charts/{job['chart_id']}")
    check(chart["bars"] >= 4 and app.pdf(chart["id"])[:4] == b"%PDF",
          f"its chart is engraved: {chart['bars']} bars, status {chart['status']}")

    song = app.call("POST", "/api/songs", json_body={"title": "Back in Black", "artist": "AC/DC",
                                                    "duration_s": 255})["song"]
    found = app.call("GET", f"/api/songs/{song['id']}/videos")
    for v in found["videos"][:3]:
        print(f"   {v['title']} | {v['channel']} | {v['duration_s']} s | {v['url']}")
    check(len(found["videos"]) >= 1, "YouTube is searched from the app (yt-dlp and its JavaScript runtime work)")

    r = app.call("POST", f"/api/songs/{song['id']}/find", json_body={"personal": True})
    job = app.wait(r["job"], timeout=1500)
    if job["status"] == "succeeded":
        check(app.pdf(job["chart_id"])[:4] == b"%PDF", "the song was found, downloaded and charted from its name")
    elif expect_download:
        raise Failed(f"the song could not be charted from its name: {job['error_code']}: {job['error']}")
    else:
        check(job["error_code"] == "download_failed" and bool(job["error"]),
              "the download was refused (expected on GitHub's servers) and reported clearly")
        print(f"   reported: {job['error'][:300]}")


def main() -> int:
    p = argparse.ArgumentParser(description="check a running Drum Agent app")
    p.add_argument("base", help="e.g. http://127.0.0.1:8765")
    p.add_argument("--take", type=Path, required=True, help="a WAV recording of drums to upload")
    p.add_argument("--expect-download", action="store_true", help="the YouTube download must work here")
    args = p.parse_args()
    try:
        run(App(args.base), args.take, args.expect_download)
    except Failed as exc:
        print(f"FAILED - {exc}", flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
