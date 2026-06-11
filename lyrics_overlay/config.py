"""Configuration: defaults, atomic persistence, and v1 -> v2 migration.

Pure module — zero Qt imports. The only filesystem side effects live in
:func:`load_config` / :func:`save_config` (reading/writing
``paths.SETTINGS_PATH``). :func:`migrate_v1` only maps dicts; the migration's
filesystem side effects (deleting the legacy ``V1_TOKEN_PATH``, the one-time
re-auth dialog) are handled by ``app.py``, not here.

``DEFAULTS`` is the schema-2 reference config and must be treated as
read-only; :func:`load_config` always returns an independent deep copy.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import tempfile
from collections.abc import Mapping
from typing import Any

from lyrics_overlay import paths

logger = logging.getLogger(__name__)

__all__ = ["DEFAULTS", "SCHEMA_VERSION", "load_config", "save_config", "migrate_v1"]

SCHEMA_VERSION = 2

DEFAULTS: dict = {
    "schema_version": 2,
    # spotify
    "spotify_client_id": "",
    "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
    "poll_interval_ms": 1000,            # clamp 1000..5000
    # appearance
    "style_preset": "panel",             # minimal|panel|cinema
    "font_family": "Segoe UI Variable Display",   # fallback handled at font resolve
    "font_size": 28,                     # px, 16..48
    "alignment": "left",                 # left|center
    "fill_mode": "white",                # white|accent|classic
    "word_motion": "subtle",             # subtle|bounce|off
    "accent_auto": True,
    "highlight_color": "#1DB954",        # manual accent when accent_auto false
    "bg_opacity": 0.35,                  # 0..1
    "legibility_mode": "shadow",         # shadow|outline|scrim
    "lines_visible": 5,                  # 3..7
    "width_percent": 56,                 # 30..90
    "max_line_width_percent": 92,        # 50..100
    "animation_budget": "full",          # full|reduced|minimal
    "show_dots": True,
    "show_track_info": True,             # toast on/off
    # position
    "position_preset": "top-center",     # top-center|bottom-center|custom
    "positions": {},                     # per QScreen.name(): {"preset": str, "x": int, "y": int}
    "monitor": "",                       # QScreen.name() or "" = primary
    "snap_enabled": True,
    "locked": True,
    # behavior
    "click_through": True,
    "fullscreen_hide": True,
    "show_over_games": False,
    "launch_at_startup": False,
    "fps_cap": 60,                       # 30|60|0 (0 = display rate)
    # sync
    "sync_offset_ms": 0,                 # positive = lyrics earlier; ±5000
    # hotkeys: empty string disables an action
    "hotkeys": {
        "toggle_visible": "Ctrl+Alt+F9",
        "toggle_clickthrough": "Ctrl+Alt+F10",
        "offset_minus": "Ctrl+Alt+Left",
        "offset_plus": "Ctrl+Alt+Right",
        "offset_reset": "Ctrl+Alt+0",
    },
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Numeric clamps applied on EVERY load (disk values included, not only migration).
_INT_RANGES: dict[str, tuple[int, int]] = {
    "poll_interval_ms": (1000, 5000),
    "font_size": (16, 48),
    "lines_visible": (3, 7),
    "width_percent": (30, 90),
    "max_line_width_percent": (50, 100),
    "sync_offset_ms": (-5000, 5000),
}

_FLOAT_RANGES: dict[str, tuple[float, float]] = {
    "bg_opacity": (0.0, 1.0),
}

_CHOICE_KEYS: dict[str, tuple[str, ...]] = {
    "style_preset": ("minimal", "panel", "cinema"),
    "alignment": ("left", "center"),
    "fill_mode": ("white", "accent", "classic"),
    "word_motion": ("subtle", "bounce", "off"),
    "legibility_mode": ("shadow", "outline", "scrim"),
    "animation_budget": ("full", "reduced", "minimal"),
    "position_preset": ("top-center", "bottom-center", "custom"),
}

_FPS_CAPS: tuple[int, ...] = (30, 60, 0)

_BOOL_KEYS: tuple[str, ...] = (
    "accent_auto",
    "show_dots",
    "show_track_info",
    "snap_enabled",
    "locked",
    "click_through",
    "fullscreen_hide",
    "show_over_games",
    "launch_at_startup",
)

_STR_KEYS: tuple[str, ...] = (
    "spotify_client_id",
    "spotify_redirect_uri",
    "font_family",
    "monitor",
)

# v1 keys that survive migration (everything else is intentionally dropped:
# spotify_client_secret, font_size [v1 was pt], font_family, position_x/y,
# text_color, opacity, bg_color, shadow_color, bold_current, show_title, ...).
_V1_KEPT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "spotify_client_id",
        "spotify_redirect_uri",
        "sync_offset_ms",
        "click_through",
        "show_track_info",
        "bg_opacity",
        "highlight_color",
        "width_percent",
        "lines_visible",
        "poll_interval_ms",
    }
)


def _clamp(value: Any, lo: Any, hi: Any) -> Any:
    return max(lo, min(hi, value))


def _coerce_int(value: Any, fallback: int) -> int:
    """Best-effort int coercion; bools and garbage fall back."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value)) if math.isfinite(value) else fallback
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return fallback
    return fallback


def _coerce_float(value: Any, fallback: float) -> float:
    """Best-effort finite-float coercion; bools and garbage fall back."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return fallback
    else:
        return fallback
    return result if math.isfinite(result) else fallback


def _schema_version_of(raw: Mapping[str, Any]) -> int:
    """Schema version of a raw on-disk dict; absent/garbage means v1."""
    try:
        return int(raw.get("schema_version", 1))
    except (TypeError, ValueError):
        return 1


def _merge_over_defaults(user: Mapping[str, Any]) -> dict:
    """Shallow merge of ``user`` over a deep copy of DEFAULTS.

    Unknown keys are preserved (forward compatibility); nested containers are
    deep-copied so the result never aliases the caller's data. The "hotkeys"
    deep merge happens in :func:`_normalize`.
    """
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in user.items():
        cfg[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
    return cfg


def _normalize(cfg: dict) -> dict:
    """Clamp ranges and repair invalid values in-place; returns ``cfg``.

    Applied to every loaded config — values straight from disk too, not just
    migration output — so the rest of the app can trust every key's type and
    range unconditionally.
    """
    cfg["schema_version"] = SCHEMA_VERSION

    for key, (lo, hi) in _INT_RANGES.items():
        cfg[key] = _clamp(_coerce_int(cfg.get(key), DEFAULTS[key]), lo, hi)

    for key, (flo, fhi) in _FLOAT_RANGES.items():
        cfg[key] = _clamp(_coerce_float(cfg.get(key), DEFAULTS[key]), flo, fhi)

    for key, choices in _CHOICE_KEYS.items():
        value = cfg.get(key)
        if not isinstance(value, str) or value not in choices:
            logger.debug("Invalid %s=%r; falling back to %r", key, value, DEFAULTS[key])
            cfg[key] = DEFAULTS[key]

    fps = _coerce_int(cfg.get("fps_cap"), DEFAULTS["fps_cap"])
    cfg["fps_cap"] = fps if fps in _FPS_CAPS else DEFAULTS["fps_cap"]

    for key in _BOOL_KEYS:
        if not isinstance(cfg.get(key), bool):
            cfg[key] = DEFAULTS[key]

    for key in _STR_KEYS:
        if not isinstance(cfg.get(key), str):
            cfg[key] = DEFAULTS[key]

    color = cfg.get("highlight_color")
    if isinstance(color, str) and _COLOR_RE.match(color.strip()):
        cfg["highlight_color"] = color.strip()
    else:
        cfg["highlight_color"] = DEFAULTS["highlight_color"]

    positions = cfg.get("positions")
    if isinstance(positions, Mapping):
        cfg["positions"] = {
            str(name): dict(entry)
            for name, entry in positions.items()
            if isinstance(entry, Mapping)
        }
    else:
        cfg["positions"] = {}

    # Deep-merge hotkeys so a v1/partial config gains newly added actions.
    # Empty string is a deliberate "disabled" value and is preserved.
    merged_hotkeys = dict(DEFAULTS["hotkeys"])
    user_hotkeys = cfg.get("hotkeys")
    if isinstance(user_hotkeys, Mapping):
        for action, sequence in user_hotkeys.items():
            if isinstance(sequence, str):
                merged_hotkeys[str(action)] = sequence
    cfg["hotkeys"] = merged_hotkeys

    return cfg


def migrate_v1(old: Mapping[str, Any]) -> dict:
    """Map a v1 settings dict to a complete v2 config dict.

    Pure dict-to-dict mapping: no file deletion, no dialogs (app.py owns the
    migration side effects). Kept keys are listed in ``_V1_KEPT_KEYS``; every
    other v1 key is dropped and its v2 default takes over. ``accent_auto`` is
    switched off only when the user had actually customized the v1 highlight
    color away from Spotify green.
    """
    cfg = copy.deepcopy(DEFAULTS)

    client_id = old.get("spotify_client_id")
    if isinstance(client_id, str):
        cfg["spotify_client_id"] = client_id.strip()

    redirect_uri = old.get("spotify_redirect_uri")
    if isinstance(redirect_uri, str) and redirect_uri.strip():
        cfg["spotify_redirect_uri"] = redirect_uri.strip()

    if "sync_offset_ms" in old:
        cfg["sync_offset_ms"] = _clamp(
            _coerce_int(old["sync_offset_ms"], DEFAULTS["sync_offset_ms"]), -5000, 5000
        )

    for key in ("click_through", "show_track_info"):
        if isinstance(old.get(key), bool):
            cfg[key] = old[key]

    if "bg_opacity" in old:
        cfg["bg_opacity"] = _clamp(
            _coerce_float(old["bg_opacity"], DEFAULTS["bg_opacity"]), 0.0, 1.0
        )

    color = old.get("highlight_color")
    if isinstance(color, str) and _COLOR_RE.match(color.strip()):
        color = color.strip()
        cfg["highlight_color"] = color
        if color.lower() != DEFAULTS["highlight_color"].lower():
            cfg["accent_auto"] = False

    if "width_percent" in old:
        cfg["width_percent"] = _clamp(
            _coerce_int(old["width_percent"], DEFAULTS["width_percent"]), 30, 90
        )

    if "lines_visible" in old:
        cfg["lines_visible"] = _clamp(
            _coerce_int(old["lines_visible"], DEFAULTS["lines_visible"]), 3, 7
        )

    if "poll_interval_ms" in old:
        cfg["poll_interval_ms"] = _clamp(
            _coerce_int(old["poll_interval_ms"], DEFAULTS["poll_interval_ms"]), 1000, 5000
        )

    cfg["schema_version"] = SCHEMA_VERSION

    dropped = sorted(set(old) - _V1_KEPT_KEYS)
    if dropped:
        logger.info("v1 migration dropped settings keys: %s", ", ".join(dropped))

    return cfg


def load_config() -> dict:
    """Read SETTINGS_PATH, migrate if needed, merge over DEFAULTS, clamp.

    Always returns a complete, validated, independent dict. A missing or
    corrupt file yields defaults. A v1 file (``schema_version`` < 2) is
    migrated via :func:`migrate_v1` and the migrated result is saved back.
    """
    settings_path = paths.SETTINGS_PATH

    try:
        # utf-8-sig tolerates a BOM left behind by external editors.
        text = settings_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        logger.info("No settings file at %s; using defaults", settings_path)
        return _normalize(copy.deepcopy(DEFAULTS))
    except OSError:
        logger.exception("Could not read %s; using defaults", settings_path)
        return _normalize(copy.deepcopy(DEFAULTS))

    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Corrupt settings JSON at %s; using defaults", settings_path)
        return _normalize(copy.deepcopy(DEFAULTS))

    if not isinstance(loaded, dict):
        logger.warning(
            "Settings root is %s, expected object; using defaults",
            type(loaded).__name__,
        )
        return _normalize(copy.deepcopy(DEFAULTS))

    migrated = False
    if _schema_version_of(loaded) < SCHEMA_VERSION:
        logger.info(
            "Migrating settings schema %d -> %d", _schema_version_of(loaded), SCHEMA_VERSION
        )
        loaded = migrate_v1(loaded)
        migrated = True

    cfg = _normalize(_merge_over_defaults(loaded))

    if migrated:
        save_config(cfg)

    return cfg


def save_config(cfg: dict) -> None:
    """Persist ``cfg`` to SETTINGS_PATH atomically (tmp file + ``os.replace``).

    A reader can never observe a partially written file. I/O failures are
    logged and swallowed (best-effort persistence must not crash the overlay);
    programming errors such as non-serializable values still propagate.
    """
    settings_path = paths.SETTINGS_PATH
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix="settings-", suffix=".tmp", dir=str(settings_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, settings_path)
        except BaseException:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            raise
    except OSError:
        logger.exception("Failed to save settings to %s", settings_path)
