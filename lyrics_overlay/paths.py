"""Filesystem locations. Pure module — no Qt."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / "SpotifyLyricsOverlay"
    return Path.home() / ".config" / "spotify-lyrics-overlay"


CONFIG_DIR: Path = _config_dir()
SETTINGS_PATH: Path = CONFIG_DIR / "settings.json"
TOKEN_PATH: Path = CONFIG_DIR / "spotify_token.json"
LYRICS_CACHE_DIR: Path = CONFIG_DIR / "lyrics_cache_v2"
ART_CACHE_DIR: Path = CONFIG_DIR / "art_cache"
LOG_DIR: Path = CONFIG_DIR / "logs"
V1_TOKEN_PATH: Path = CONFIG_DIR / ".spotify_cache"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, LYRICS_CACHE_DIR, ART_CACHE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
