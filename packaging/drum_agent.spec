# PyInstaller recipe for the Drum Agent app (one folder: dist/DrumAgent/).
#   pyinstaller packaging/drum_agent.spec --noconfirm
# The tools (LilyPond, ffmpeg, yt-dlp, Deno) are not part of this: packaging/fetch_tools.py
# puts them in dist/DrumAgent/tools, where drum_agent.desktop finds them.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is set by PyInstaller
ICON = os.path.join(ROOT, "build", "drum-agent.ico")

datas = collect_data_files("drum_agent") + collect_data_files("librosa") + collect_data_files("xmlschema")
datas += collect_data_files("webview")
# The example song shown in My Charts on the first start (drum_agent/web/catalog.py looks two
# folders above the package: <bundle>/examples/specs).
datas += [(os.path.join(ROOT, "examples", "specs", "03_full_song_northbound.yaml"), os.path.join("examples", "specs"))]

hiddenimports = collect_submodules("drum_agent") + collect_submodules("uvicorn") + ["webview"]
try:  # the drum separation (HTDemucs), when the build machine installed demucs and PyTorch
    import demucs  # noqa: F401
    datas += collect_data_files("demucs")  # its model list (remote/*.yaml, files.txt)
    # What loading and running the model needs; the model's class is named inside the checkpoint,
    # so the analysis can't see it. (Not all of demucs: its training code needs much more.)
    hiddenimports += ["demucs." + m for m in ("pretrained", "apply", "repo", "states", "utils", "htdemucs",
                                               "hdemucs", "demucs", "transformer", "spec")]
except ImportError:
    pass

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "launch.py")],  # noqa: F821
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["yt_dlp", "pytest", "verovio", "pdfplumber", "matplotlib", "IPython", "notebook", "PyQt5", "PyQt6",
              "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
# Python's UTF-8 mode: files and tool output are UTF-8 whatever the Windows code page (the code
# also says so everywhere; this covers the libraries).
options = [("X utf8", None, "OPTION")]
exe = EXE(  # noqa: F821
    pyz, a.scripts, options, exclude_binaries=True, name="DrumAgent", console=False,
    icon=ICON if os.path.isfile(ICON) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DrumAgent")  # noqa: F821
