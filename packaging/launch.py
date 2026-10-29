"""Entry point of the packaged Drum Agent app (PyInstaller): `drum_agent.desktop.main`."""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # A windowed app has no console: give libraries that write to stdout/stderr somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    from drum_agent.desktop import main
    sys.exit(main())
