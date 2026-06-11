"""Console entry point. Use LyricOverlay.pyw for a window-less launch."""

import os
import sys

# Under pythonw the std streams are None; anything that prints would die (cpython
# #122633). Must run before any other import.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lyrics_overlay.app import run
    sys.exit(run(sys.argv[1:]))
