"""The Drum Agent app on a person's own computer (`python -m drum_agent app`, and the
installed app's entry point).

It runs the studio in personal mode (`DRUM_AGENT_MODE=personal`: a song typed by name is
found among the user's own audio files and charted for their own practice) on 127.0.0.1
at a free port, with the tools the installer put beside it (LilyPond, FFmpeg, the drum
separation model), and shows it
in its own window (the system web view: WebView2 on Windows, WebKit on a Mac). Without a
web view it shows a small window with "Open Drum Agent" (the default browser) and "Quit".
Closing the window stops the app. A second launch opens the running app instead of
starting another one.

Data (charts, decoded recordings, the log) lives in the user's folder:
%LOCALAPPDATA%\\Drum Agent on Windows, ~/Library/Application Support/Drum Agent on a Mac,
~/.local/share/drum-agent elsewhere. The app talks to the internet only to identify songs
(MusicBrainz, iTunes, Deezer; Spotify and the YouTube Data API when keys are configured):
metadata only, never audio.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
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
    paths = []
    if tools is not None:
        lily = tools / "lilypond" / "bin" / f"lilypond{EXE}"
        if lily.is_file():
            os.environ["DRUM_AGENT_LILYPOND"] = str(lily)
        paths += [str(p) for p in (tools / "ffmpeg" / "bin",) if p.is_dir()]
        if (tools / "torch").is_dir():  # the drum separation model, shipped: no download on the first song
            os.environ.setdefault("TORCH_HOME", str(tools / "torch"))
    os.environ["PATH"] = os.pathsep.join([*paths, os.environ.get("PATH", "")])


def hide_console_windows() -> None:
    """Windows: the tools (LilyPond, FFmpeg) are console programs, and a windowed app that
    starts one gets a black console window popping up every time. Start them all without one."""
    if os.name != "nt" or getattr(subprocess.Popen, "no_window", False):
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    class Popen(subprocess.Popen):
        no_window = True

        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | flag
            super().__init__(*args, **kwargs)
    subprocess.Popen = Popen  # subprocess.run and friends look it up here


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
        info = json.loads((data / "app.json").read_text(encoding="utf-8"))
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


def seed_examples() -> threading.Thread:
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
    thread = threading.Thread(target=run, name="seed", daemon=True)
    thread.start()
    return thread


LOADING = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#0b1020;color:#e8ecf8;font:16px system-ui,sans-serif}
body{display:grid;place-items:center}.b{text-align:center}.s{width:34px;height:34px;margin:0 auto 18px;
border:3px solid #2a3350;border-top-color:#2ee6a6;border-radius:50%;animation:r 0.9s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}p{color:#98a2c0;font-size:13px}</style></head>
<body><div class="b"><div class="s"></div><strong>Starting Drum Agent…</strong><p>This takes a few seconds (longer the first time).</p>
</div></body></html>"""


WINDOW = (1360, 900)


def window_size(screens) -> dict:
    """The window opens at 1360 x 900, or maximized when the main screen has less room than that
    (title bar and taskbar included): a 1366 x 768 laptop, or 1920 x 1080 at 125 % scaling."""
    w, h = WINDOW
    roomy = bool(screens) and screens[0].width >= w + 40 and screens[0].height >= h + 100
    return {"width": w, "height": h, "maximized": not roomy}


def studio_ready(url: str, seeding: threading.Thread, seed_wait: float = 120.0) -> bool:
    """The studio answers, with the example chart in place: the first start engraves it, and
    its card would otherwise show a song without a chart."""
    seeding.join(timeout=seed_wait)
    return wait_ready(url)


def show_window(url: str, ready) -> bool:
    """The studio in its own window (pywebview). Blocks until the window is closed; False without one."""
    try:
        import webview
    except ImportError:
        return False
    try:
        try:
            screens = webview.screens
        except Exception:  # noqa: BLE001 - no screen information: window_size() maximizes
            screens = []
        win = webview.create_window(TITLE, html=LOADING, min_size=(900, 640), background_color="#0b1020",
                                    **window_size(screens))

        def load():
            if ready():
                win.load_url(url)
            else:
                win.load_html(LOADING.replace("Starting Drum Agent…", "Drum Agent could not start")
                              .replace("This takes a few seconds (longer the first time).",
                                       f"See the log in {data_dir() / 'logs'}"))
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
    args = p.parse_args(argv)

    hide_console_windows()
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    _logging(data)
    tools = tools_dir()
    configure(data, tools)
    if not args.headless:
        url = running_instance(data)
        if url is not None:  # already running: show it, don't start a second one
            log.info("already running at %s", url)
            if not show_window(url, lambda: True):
                webbrowser.open(url)
            return 0

    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}"
    server = start_server(port)
    seeding = seed_examples()
    (data / "app.json").write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    log.info("%s %s on %s (tools: %s)", TITLE, _version(), url, tools)
    try:
        if args.headless:
            print(f"{TITLE} is running at {url}", flush=True)
            try:
                while not server.should_exit:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        elif not show_window(url, lambda: studio_ready(url, seeding)):
            if studio_ready(url, seeding):
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
