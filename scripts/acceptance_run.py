"""The whole workflow on a real, annotated recording, through the web app's API.

Search (optional: needs the internet) -> pick the song -> its source (no licensed provider:
it needs a recording) -> upload the recording with its rights basis -> the transcription
job and its stages -> the chart (every bar, its strokes) -> its files (PDF, MusicXML, MIDI)
-> edit one stroke and save -> reopen both versions -> export. Then the chart's own strokes
are scored against the recording's human annotations, so "it works" says how well.

The recording is an MDB Drums track (Southall et al., ISMIR 2017; MedleyDB audio, CC
BY-NC-SA 4.0, used here for a non-commercial evaluation): a real band and drummer, every
stroke annotated. `scripts/eval_real.py --download` puts it in the local cache; nothing is
committed. The app runs as a shared server, so this script is one visitor (a cookie jar).

    python -m drum_agent serve --port 8000 &
    python scripts/acceptance_run.py http://127.0.0.1:8000 --track Britpop [--search "Back in Black - AC/DC"]

Only development-split tracks: the test split is held out (CLAUDE.md), run once per model.

Prints every step's evidence; exits 1 at the first failed step.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_real import (
    CLASSES,
    OURS_TO_MDB,
    TRAIN,
    _f,
    _paths,
    read_annotations,
    score_track,
)


class Failed(Exception):
    pass


def check(cond: bool, what: str) -> None:
    if not cond:
        raise Failed(what)
    print(f"ok - {what}", flush=True)


class App:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, *, json_body=None, data: bytes | None = None, headers: dict | None = None,
             raw: bool = False):
        h = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=300) as r:
                body = r.read()
        except urllib.error.HTTPError as exc:
            raise Failed(f"{method} {path}: HTTP {exc.code} {exc.read()[:300]!r}") from None
        return body if raw else json.loads(body)

    def wait(self, job_id: str, timeout: float = 3600) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            job = self.call("GET", f"/api/jobs/{job_id}")
            if job["status"] in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(2)
        raise Failed(f"job {job_id} still running after {timeout:.0f} s")


def multipart(fields: dict[str, str], name: str, filename: str, content: bytes) -> tuple[bytes, dict]:
    b = "----drumagent" + uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"}


def chart_strokes(score: dict) -> list[tuple[float, str]]:
    """(time in the recording, MDB class) of every stroke in the chart (chart.json)."""
    return [(h["time"], OURS_TO_MDB.get(h["inst"], "OT")) for m in score["measures"] for h in m["hits"]
            if h.get("time") is not None]


def accuracy(ref: list[tuple[float, str]], est: list[tuple[float, str]]) -> dict:
    per = score_track(ref, est)
    tp = sum(per[c]["tp"] for c in CLASSES)
    n_ref = sum(per[c]["ref"] for c in CLASSES)
    n_est = sum(per[c]["est"] for c in CLASSES)
    f, p, r = _f(tp, n_ref, n_est)
    err = sum(per[c]["err_ms"] for c in CLASSES)
    return {"per_class": {c: round(_f(per[c]["tp"], per[c]["ref"], per[c]["est"])[0], 3) for c in CLASSES},
            "F": round(f, 3), "P": round(p, 3), "R": round(r, 3), "missed": n_ref - tp, "extra": n_est - tp,
            "annotated": n_ref, "timing_ms": round(err / tp, 1) if tp else None}


def run(app: App, track: str, search: str | None, expect_separation: bool = False) -> None:
    paths = _paths(track)
    check(paths["mix"].is_file() and paths["class"].is_file(),
          f"the recording and its annotations are in the cache ({paths['mix'].name}; eval_real.py --download)")
    h = app.call("GET", "/api/health")
    check(h["ok"], "the app is up: " + ", ".join(f"{k} {'ok' if v['ok'] else 'MISSING'}" for k, v in h["checks"].items()))
    print(f"   mode {h['mode']}; drum separation {'installed' if h['separation']['available'] else 'not installed'}")
    if expect_separation:
        check(h["separation"]["available"], f"the drum separation is installed ({h['separation'].get('model')})")

    if search:  # 1. search: real catalog providers (MusicBrainz, iTunes, Deezer; Spotify, YouTube with keys)
        r = app.call("GET", "/api/search?q=" + urllib.parse.quote(search))
        for st in r["providers"]:
            print(f"   {st['provider']}: {st['state']} {st.get('detail') or ''}".rstrip())
        for x in r["results"][:3]:
            print(f"   {x['title']} | {x['artist']} | {x.get('album') or '-'} | {x.get('duration_s')} s | {x.get('url')}")
        check(len(r["results"]) >= 1, f"the search for {search!r} returns real recordings")

    # 2. pick the song; 3. its source: without a licensed provider it needs a recording
    d = app.call("POST", "/api/songs", json_body={"title": track, "artist": "MusicDelta (MDB Drums)"})
    sid = d["song"]["id"]
    check(d["resolution"]["case"] == "NEEDS_SOURCE", f"the song needs a recording: {d['resolution']['detail'][:120]}")

    # 4. upload the recording with its rights basis; 5. the transcription job
    body, headers = multipart({"rights": "licensed"}, "file", paths["mix"].name, paths["mix"].read_bytes())
    up = app.call("POST", f"/api/songs/{sid}/upload", data=body, headers=headers)
    t0 = time.time()
    job = app.wait(up["job"]["id"])
    stages = ", ".join(f"{s['name']} {(s.get('ended_at') or 0) - (s.get('started_at') or 0):.1f}s"
                       for s in job["stages"] if s["status"] == "done")
    check(job["status"] == "succeeded", f"the recording is transcribed in {time.time() - t0:.0f} s ({stages})")

    # 6. the chart
    chart = app.call("GET", f"/api/charts/{job['chart_id']}")
    if expect_separation:
        notes = chart["summary"].get("notes") or []
        check(bool(notes) and notes[0].startswith("The drums were separated from the band"),
              "the drums were separated from the band first (HTDemucs ran on the server)")
    score = app.call("GET", chart["files"]["chart.json"])
    hits = sum(len(m["hits"]) for m in score["measures"])
    insts = sorted({h["inst"] for m in score["measures"] for h in m["hits"]})
    flagged = sum(1 for m in score["measures"] if m.get("uncertain"))
    timeline = chart["view"]["timeline"]
    check(chart["bars"] >= 4 and hits > 0, f"the chart: {chart['bars']} bars, {hits} strokes on {len(insts)} instruments "
          f"({', '.join(insts)}), {flagged} bars flagged for review, status {chart['status']}")
    check(chart["view"]["timeline_kind"] == "performed" and timeline[0]["t"] < 5,
          f"bars are placed on the recording's own time: bar 1 at {timeline[0]['t']:.2f} s, bar "
          f"{len(timeline)} at {timeline[-1]['t']:.2f} s")

    # 7. how well: the chart's own strokes against the human annotations
    acc = accuracy(read_annotations(paths["class"]), chart_strokes(score))
    print("   onset F at 50 ms per class: " + ", ".join(f"{c} {v}" for c, v in acc["per_class"].items()))
    check(acc["F"] > 0.3, f"the chart against the annotations, all 5 classes: F {acc['F']} (P {acc['P']}, R {acc['R']}), "
          f"{acc['missed']} of {acc['annotated']} strokes missed, {acc['extra']} extra, mean timing error "
          f"{acc['timing_ms']} ms")

    # 8. edit one stroke and save a version; 9. reopen both
    files = {k: app.call("GET", v, raw=True) for k, v in chart["files"].items() if k != "chart.json"}
    bar = next(i for i, m in enumerate(score["measures"]) if m["hits"] and i > 0)
    removed = score["measures"][bar]["hits"].pop(0)
    v2 = app.call("POST", f"/api/projects/{sid}/versions",
                  json_body={"score": score, "base_chart_id": chart["id"], "note": "acceptance: one stroke removed"})
    check(v2["version"] == 2, f"an edit is saved as version 2 (bar {bar + 1}: {removed['inst']} at {removed['pos']} removed)")
    project = app.call("GET", f"/api/projects/{sid}")
    again = app.call("GET", app.call("GET", f"/api/charts/{v2['id']}")["files"]["chart.json"])
    first = app.call("GET", app.call("GET", f"/api/charts/{chart['id']}")["files"]["chart.json"])
    n1 = sum(len(m["hits"]) for m in first["measures"])
    n2 = sum(len(m["hits"]) for m in again["measures"])
    check([c["version"] for c in project["charts"]] == [2, 1] and n2 == n1 - 1,
          f"reopened: versions 1 and 2 are both stored, version 2 has one stroke fewer ({n1} -> {n2})")

    # 10. export
    v2files = app.call("GET", f"/api/charts/{v2['id']}")["files"]
    pdf = app.call("GET", v2files["chart.pdf"], raw=True)
    xml = app.call("GET", v2files["chart.musicxml"], raw=True)
    mid = app.call("GET", v2files["chart.mid"], raw=True)
    check(pdf[:4] == b"%PDF" and b"score-partwise" in xml[:400] and mid[:4] == b"MThd",
          f"exported: PDF {len(pdf) // 1024} kB, MusicXML {len(xml) // 1024} kB, MIDI {len(mid)} bytes "
          f"(version 1 kept: {', '.join(sorted(files))})")


def main() -> int:
    p = argparse.ArgumentParser(description="the whole workflow on a real, annotated recording")
    p.add_argument("base", help="e.g. http://127.0.0.1:8000")
    p.add_argument("--track", default="Britpop", choices=TRAIN, help="an MDB Drums development track (default Britpop)")
    p.add_argument("--search", help="also a real catalog search for this text (needs the internet)")
    p.add_argument("--expect-separation", action="store_true", help="the drum separation must be installed and run")
    args = p.parse_args()
    try:
        run(App(args.base), args.track, args.search, args.expect_separation)
    except Failed as exc:
        print(f"FAILED - {exc}", flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
