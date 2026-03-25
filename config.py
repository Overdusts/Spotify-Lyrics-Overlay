import json
import os
import sys

CONFIG_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if not getattr(sys, 'frozen', False) else sys.executable))
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "opacity": 0.85,
    "font_family": "Segoe UI",
    "font_size": 20,
    "text_color": "#AAAAAA",
    "highlight_color": "#1DB954",
    "shadow_color": "#000000",
    "bg_color": "#000000",
    "bg_opacity": 0.35,
    "position_x": -1,
    "position_y": 30,
    "lines_visible": 3,
    "poll_interval_ms": 3000,
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
    "click_through": False,
    "width_percent": 60,
    "bold_current": True,
    "show_title": True,
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
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
