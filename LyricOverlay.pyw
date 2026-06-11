"""Windowed entry point (no console) — target this from the Run key or a shortcut."""

import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lyrics_overlay.app import run  # noqa: E402

sys.exit(run(sys.argv[1:]))
