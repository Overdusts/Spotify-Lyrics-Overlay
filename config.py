import json
import os
import sys


def _get_config_dir():
    """Pick a safe, writable config directory across platforms."""
    # Windows: %APPDATA%\SpotifyLyricsOverlay
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = os.path.join(appdata, "SpotifyLyricsOverlay")
    else:
        # Linux/Mac fallback
        d = os.path.expanduser("~/.config/spotify-lyrics-overlay")
    try:
        os.makedirs(d, exist_ok=True)
        # Verify writable
        test_path = os.path.join(d, ".write_test")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        return d
    except Exception:
        # Last resort: directory of the script
        return os.path.dirname(os.path.abspath(sys.argv[0] if not getattr(sys, 'frozen', False) else sys.executable))


CONFIG_DIR = _get_config_dir()
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
CACHE_DIR = os.path.join(CONFIG_DIR, "lyrics_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

DEFAULTS = {
    "font_family": "Segoe UI",
    "font_size": 22,
    "text_color": "#FFFFFF",
    "highlight_color": "#1DB954",
    "bg_color": "#000000",
    "bg_opacity": 0.0,
    "position_x": -1,
    "position_y": 40,
    "lines_visible": 3,
    "poll_interval_ms": 1000,
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
    "click_through": True,
    "width_percent": 70,
    "sync_offset_ms": 0,  # positive = lyrics advance earlier, negative = later
    "show_track_info": True,  # briefly show track name on change
    "max_line_width_percent": 90,  # wrap lines wider than this % of window
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            cfg.update(user)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def migrate_legacy_config():
    """Move old settings.json from the script directory to APPDATA if it exists."""
    legacy_dir = os.path.dirname(os.path.abspath(sys.argv[0] if not getattr(sys, 'frozen', False) else sys.executable))
    legacy_path = os.path.join(legacy_dir, "settings.json")
    if legacy_path != CONFIG_PATH and os.path.exists(legacy_path) and not os.path.exists(CONFIG_PATH):
        try:
            import shutil
            shutil.copy2(legacy_path, CONFIG_PATH)
        except Exception:
            pass
