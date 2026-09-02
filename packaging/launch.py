"""PyInstaller entry point: what `python -m chronogram_tg` does, as a script.

PyInstaller needs a plain script to freeze; this is that script and nothing
more. Double-clicking the packaged app passes no arguments, so main() opens
the window.
"""

import sys

from chronogram_tg.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
