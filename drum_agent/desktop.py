"""The Drum Agent app on a person's own computer (`python -m drum_agent app`, and the
installed app's entry point).

It runs the studio in personal mode (`DRUM_AGENT_MODE=personal`: a song typed by name is
found on YouTube and charted for the user's own practice) on 127.0.0.1 at a free port,
with the tools the installer put beside it (LilyPond, ffmpeg, yt-dlp, Deno), and shows it
in its own window (the system web view: WebView2 on Windows, WebKit on a Mac). Without a
web view it shows a small window with "Open Drum Agent" (the default browser) and "Quit".
Closing the window stops the app. A second launch opens the running app instead of
starting another one.

Data (charts, decoded recordings, the log) lives in the user's folder:
%LOCALAPPDATA%\\Drum Agent on Windows, ~/Library/Application Support/Drum Agent on a Mac,
~/.local/share/drum-agent elsewhere. The app talks to the internet only to identify songs
(MusicBrainz, iTunes, Deezer), to search and download from YouTube, and to keep yt-dlp
up to date (YouTube changes often; an old yt-dlp stops working).
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

log = logging.getLogger("drum_agent.desktop")
TITLE = "Drum Agent"
YTDLP_UPDATE_EVERY_S = 24 * 3600
EXE = ".exe" if os.name == "nt" else ""


def data_dir() -> Path:
    if os.environ.get("DRUM_AGENT_DATA_DIR"):
        return Path(os.environ["DRUM_AGENT_DATA_DIR"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / TITLE
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / TITLE
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "drum-agent"


def tools_dir() -> Path | None:
    """The tools shipped with the installed app (`tools/` in the bundle), or $DRUM_AGENT_TOOLS."""
    if os.environ.get("DRUM_AGENT_TOOLS"):
        return Path(os.environ["DRUM_AGENT_TOOLS"])
    if getattr(sys, "frozen", False):
        for base in (Path(sys.executable).parent, Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))):
            if (base / "tools").is_dir():
                return base / "tools"
    return None


def configure(data: Path, tools: Path | None) -> None:
    """Point the studio at its data and at the shipped tools (they come first on PATH)."""
    os.environ["DRUM_AGENT_MODE"] = "personal"
    os.environ["DRUM_AGENT_DATA_DIR"] = str(data / "studio")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(data / "cache" / "numba"))
    os.environ.setdefault("DRUM_AGENT_AUDIO_CACHE", str(data / "cache" / "audio"))
    paths = [str(data / "bin")]  # yt-dlp is copied here, where it can update itself
    if tools is not None:
        lily = tools / "lilypond" / "bin" / f"lilypond{EXE}"
        if lily.is_file():
            os.environ["DRUM_AGENT_LILYPOND"] = str(lily)
        paths += [str(p) for p in (tools / "ffmpeg" / "bin", tools / "deno") if p.is_dir()]
    os.environ["PATH"] = os.pathsep.join([*paths, os.environ.get("PATH", "")])


def install_ytdlp(data: Path, tools: Path | None) -> Path | None:
    """The shipped yt-dlp, copied into the user's folder once (an installed copy can't update itself
    there without administrator rights). Returns its path, or None when none is shipped."""
    shipped = tools / "yt-dlp" / f"yt-dlp{EXE}" if tools is not None else None
    target = data / "bin" / f"yt-dlp{EXE}"
    if shipped is None or not shipped.is_file():
        return target if target.is_file() else None
    stamp = data / "bin" / "yt-dlp.shipped"
    mark = f"{shipped.stat().st_size}:{int(shipped.stat().st_mtime)}"
    if not target.is_file() or (stamp.is_file() and stamp.read_text() != mark and _older(target, shipped)):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shipped, target)
        if os.name != "nt":
            target.chmod(0o755)
        stamp.write_text(mark)
    elif not stamp.is_file():
        stamp.write_text(mark)
    return target


def _older(a: Path, b: Path) -> bool:
    return a.stat().st_mtime < b.stat().st_mtime


def update_ytdlp(exe: Path, data: Path) -> None:
    """`yt-dlp -U`, at most once a day, in the background; failures only go to the log."""
    stamp = data / "bin" / "yt-dlp.updated"
    if stamp.is_file() and time.time() - stamp.stat().st_mtime < YTDLP_UPDATE_EVERY_S:
        return

    def run():
        try:
            out = subprocess.run([str(exe), "-U"], capture_output=True, text=True, timeout=300,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log.info("yt-dlp -U: %s", " ".join((out.stdout + out.stderr).split())[-300:])
            stamp.write_text(str(time.time()))
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("could not update yt-dlp: %s", exc)
    threading.Thread(target=run, name="yt-dlp-update", daemon=True).start()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def healthy(url: str, timeout: float = 2.0) -> bool:
    """Is the studio answering? (503 counts: it runs, with a tool missing, and the page says which.)"""
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 503
    except OSError:
        return False


def running_instance(data: Path) -> str | None:
    """The URL of this user's app if it is already running."""
    try:
        info = json.loads((data / "app.json").read_text())
        url = f"http://127.0.0.1:{int(info['port'])}"
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return url if healthy(url) else None


def start_server(port: int):
    """The studio on 127.0.0.1:port in a background thread. Returns the uvicorn server."""
    import uvicorn

    from .web.app import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None))
    threading.Thread(target=server.run, name="studio", daemon=True).start()
    return server


def wait_ready(url: str, timeout: float = 120.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if healthy(url):
            return True
        time.sleep(0.2)
    return False


def seed_examples() -> None:
    """The example song's chart in My Charts, the first time (best effort, in the background)."""
    def run():
        try:
            from .web.catalog import seed_examples as seed
            from .web.jobs import JobRunner
            from .web.store import Store, default_data_dir
            store = Store(default_data_dir())
            seed(store, JobRunner(store, start=False))
            store.close()
        except Exception:  # noqa: BLE001 - a missing example never stops the app
            log.exception("could not add the example chart")
    threading.Thread(target=run, name="seed", daemon=True).start()


LOADING = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#0b1020;color:#e8ecf8;font:16px system-ui,sans-serif}
body{display:grid;place-items:center}.b{text-align:center}.s{width:34px;height:34px;margin:0 auto 18px;
border:3px solid #2a3350;border-top-color:#2ee6a6;border-radius:50%;animation:r 0.9s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}p{color:#98a2c0;font-size:13px}</style></head>
<body><div class="b"><div class="s"></div><strong>Starting Drum Agent…</strong><p>This takes a few seconds.</p>
</div></body></html>"""


def show_window(url: str, ready) -> bool:
    """The studio in its own window (pywebview). Blocks until the window is closed; False without one."""
    try:
        import webview
    except ImportError:
        return False
    try:
        win = webview.create_window(TITLE, html=LOADING, width=1360, height=900, min_size=(900, 640),
                                    background_color="#0b1020")

        def load():
            if ready():
                win.load_url(url)
            else:
                win.load_html(LOADING.replace("Starting Drum Agent…", "Drum Agent could not start")
                              .replace("This takes a few seconds.", f"See the log in {data_dir() / 'logs'}"))
        webview.start(load)
        return True
    except Exception:  # noqa: BLE001 - no web view on this system: the small window below
        log.exception("no web view; falling back to the browser")
        return False


def show_launcher(url: str) -> None:
    """A small window with "Open Drum Agent" (the default browser) and "Quit"; blocks until closed."""
    webbrowser.open(url)
    try:
        import tkinter as tk
    except ImportError:  # no window toolkit at all: run until the process is stopped
        print(f"{TITLE} is running at {url} (stop it with Ctrl+C)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    root = tk.Tk()
    root.title(TITLE)
    root.geometry("360x150")
    tk.Label(root, text=f"{TITLE} is running.", font=("TkDefaultFont", 12, "bold")).pack(pady=(18, 4))
    tk.Label(root, text="It opens in your web browser.").pack()
    row = tk.Frame(root)
    row.pack(pady=14)
    tk.Button(row, text="Open Drum Agent", command=lambda: webbrowser.open(url)).pack(side="left", padx=6)
    tk.Button(row, text="Quit", command=root.destroy).pack(side="left", padx=6)
    root.mainloop()


def _logging(data: Path) -> None:
    (data / "logs").mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(data / "logs" / "drum-agent.log", maxBytes=2_000_000,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="drum-agent app", description="Drum Agent on your own computer")
    p.add_argument("--headless", action="store_true", help="no window: serve until stopped (for tests)")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    p.add_argument("--no-update", action="store_true", help="don't update yt-dlp")
    args = p.parse_args(argv)

    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    _logging(data)
    tools = tools_dir()
    configure(data, tools)
    ytdlp = install_ytdlp(data, tools)
    if not args.headless:
        url = running_instance(data)
        if url is not None:  # already running: show it, don't start a second one
            log.info("already running at %s", url)
            if not show_window(url, lambda: True):
                webbrowser.open(url)
            return 0
    if ytdlp is not None and not args.no_update:
        update_ytdlp(ytdlp, data)

    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}"
    server = start_server(port)
    seed_examples()
    (data / "app.json").write_text(json.dumps({"port": port, "pid": os.getpid()}))
    log.info("%s %s on %s (tools: %s)", TITLE, _version(), url, tools)
    try:
        if args.headless:
            print(f"{TITLE} is running at {url}", flush=True)
            try:
                while not server.should_exit:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        elif not show_window(url, lambda: wait_ready(url)):
            if wait_ready(url):
                show_launcher(url)
    finally:
        server.should_exit = True
        try:
            (data / "app.json").unlink()
        except OSError:
            pass
    return 0


def _version() -> str:
    from . import __version__
    return __version__


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
