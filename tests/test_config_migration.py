"""Tests for lyrics_overlay.config — v1 migration, clamps, deep-merge, atomic save.

Self-contained: stdlib + pytest only. All filesystem access is redirected to
``tmp_path`` by monkeypatching ``lyrics_overlay.paths`` constants, so no real
%APPDATA% files are ever touched.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

# Make the repo root importable regardless of how pytest was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyrics_overlay import paths  # noqa: E402
from lyrics_overlay.config import (  # noqa: E402
    DEFAULTS,
    load_config,
    migrate_v1,
    save_config,
)

# Mirrors a real v1 settings.json (every v1 key, several customized).
V1_FULL: dict = {
    "opacity": 0.85,
    "font_family": "Segoe UI",
    "font_size": 12,
    "text_color": "#BBBBBB",
    "highlight_color": "#aa00ff",
    "shadow_color": "#000000",
    "bg_color": "#000000",
    "bg_opacity": 0.29,
    "position_x": -1,
    "position_y": 10,
    "lines_visible": 1,
    "poll_interval_ms": 3000,
    "spotify_client_id": "0123456789abcdef0123456789abcdef",
    "spotify_client_secret": "fedcba9876543210fedcba9876543210",
    "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
    "click_through": False,
    "width_percent": 95,
    "sync_offset_ms": 250,
    "show_track_info": False,
    "max_line_width_percent": 90,
    "bold_current": False,
    "show_title": False,
}


@pytest.fixture()
def settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config persistence into tmp_path; returns the settings file."""
    target = tmp_path / "settings.json"
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(paths, "SETTINGS_PATH", target)
    return target


# ---------------------------------------------------------------------------
# migrate_v1 — pure dict mapping
# ---------------------------------------------------------------------------


class TestMigrateV1:
    def test_v1_dict_in_v2_out(self) -> None:
        out = migrate_v1(V1_FULL)
        assert out["schema_version"] == 2
        # Result is a COMPLETE v2 config (every default key present).
        assert set(DEFAULTS) <= set(out)

    def test_kept_keys(self) -> None:
        out = migrate_v1(V1_FULL)
        assert out["spotify_client_id"] == V1_FULL["spotify_client_id"]
        assert out["spotify_redirect_uri"] == V1_FULL["spotify_redirect_uri"]
        assert out["sync_offset_ms"] == 250
        assert out["click_through"] is False
        assert out["show_track_info"] is False
        assert out["bg_opacity"] == pytest.approx(0.29)
        assert out["highlight_color"] == "#aa00ff"

    def test_secret_dropped(self) -> None:
        out = migrate_v1(V1_FULL)
        assert "spotify_client_secret" not in out

    def test_v1_only_keys_dropped(self) -> None:
        out = migrate_v1(V1_FULL)
        for gone in (
            "opacity",
            "text_color",
            "bg_color",
            "shadow_color",
            "position_x",
            "position_y",
            "bold_current",
            "show_title",
        ):
            assert gone not in out, gone

    def test_font_and_layout_take_v2_defaults(self) -> None:
        out = migrate_v1(V1_FULL)
        # v1 font_size was pt, v2 is px — never carried over.
        assert out["font_size"] == DEFAULTS["font_size"]
        assert out["font_family"] == DEFAULTS["font_family"]
        # max_line_width_percent is not in the keep list.
        assert out["max_line_width_percent"] == DEFAULTS["max_line_width_percent"]
        # position_x/y dropped in favor of presets.
        assert out["position_preset"] == "top-center"
        assert out["positions"] == {}

    def test_accent_auto_false_for_custom_color(self) -> None:
        out = migrate_v1({"highlight_color": "#aa00ff"})
        assert out["highlight_color"] == "#aa00ff"
        assert out["accent_auto"] is False

    def test_accent_auto_true_for_default_color(self) -> None:
        out = migrate_v1({"highlight_color": "#1DB954"})
        assert out["accent_auto"] is True
        assert out["highlight_color"] == "#1DB954"

    def test_accent_auto_true_for_default_color_case_insensitive(self) -> None:
        out = migrate_v1({"highlight_color": "#1db954"})
        assert out["accent_auto"] is True

    def test_accent_auto_true_when_color_missing(self) -> None:
        out = migrate_v1({})
        assert out["accent_auto"] is True
        assert out["highlight_color"] == DEFAULTS["highlight_color"]

    def test_invalid_color_ignored(self) -> None:
        out = migrate_v1({"highlight_color": "green"})
        assert out["highlight_color"] == DEFAULTS["highlight_color"]
        assert out["accent_auto"] is True

    def test_width_percent_clamped(self) -> None:
        assert migrate_v1({"width_percent": 95})["width_percent"] == 90
        assert migrate_v1({"width_percent": 10})["width_percent"] == 30
        assert migrate_v1({"width_percent": 70})["width_percent"] == 70

    def test_lines_visible_clamped(self) -> None:
        assert migrate_v1({"lines_visible": 1})["lines_visible"] == 3
        assert migrate_v1({"lines_visible": 9})["lines_visible"] == 7

    def test_poll_interval_clamped(self) -> None:
        assert migrate_v1({"poll_interval_ms": 300})["poll_interval_ms"] == 1000
        assert migrate_v1({"poll_interval_ms": 3000})["poll_interval_ms"] == 3000

    def test_sync_offset_clamped(self) -> None:
        assert migrate_v1({"sync_offset_ms": 99999})["sync_offset_ms"] == 5000
        assert migrate_v1({"sync_offset_ms": -99999})["sync_offset_ms"] == -5000

    def test_bg_opacity_clamped(self) -> None:
        assert migrate_v1({"bg_opacity": 1.5})["bg_opacity"] == 1.0
        assert migrate_v1({"bg_opacity": -0.2})["bg_opacity"] == 0.0

    def test_garbage_types_fall_back_to_defaults(self) -> None:
        out = migrate_v1(
            {
                "width_percent": "wide",
                "lines_visible": None,
                "click_through": "yes",
                "spotify_client_id": 123,
                "bg_opacity": "dark",
            }
        )
        assert out["width_percent"] == DEFAULTS["width_percent"]
        assert out["lines_visible"] == DEFAULTS["lines_visible"]
        assert out["click_through"] is DEFAULTS["click_through"]
        assert out["spotify_client_id"] == ""
        assert out["bg_opacity"] == DEFAULTS["bg_opacity"]

    def test_empty_v1_dict_yields_pure_defaults(self) -> None:
        assert migrate_v1({}) == DEFAULTS

    def test_input_not_mutated(self) -> None:
        old = copy.deepcopy(V1_FULL)
        migrate_v1(old)
        assert old == V1_FULL

    def test_output_is_independent_of_defaults(self) -> None:
        out = migrate_v1({})
        out["hotkeys"]["toggle_visible"] = "changed"
        assert DEFAULTS["hotkeys"]["toggle_visible"] == "Ctrl+Alt+F9"


# ---------------------------------------------------------------------------
# load_config — read, migrate, merge, clamp
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, settings_path: Path) -> None:
        cfg = load_config()
        assert cfg == DEFAULTS
        # Independent copy, nested dicts included.
        assert cfg is not DEFAULTS
        assert cfg["hotkeys"] is not DEFAULTS["hotkeys"]
        assert cfg["positions"] is not DEFAULTS["positions"]
        # Nothing migrated -> nothing written.
        assert not settings_path.exists()

    def test_corrupt_json_returns_defaults(self, settings_path: Path) -> None:
        settings_path.write_text("{this is not json", encoding="utf-8")
        assert load_config() == DEFAULTS

    def test_non_object_json_returns_defaults(self, settings_path: Path) -> None:
        settings_path.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_config() == DEFAULTS

    def test_bom_tolerated(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(DEFAULTS), encoding="utf-8-sig")
        assert load_config() == DEFAULTS

    def test_v1_file_migrated_and_saved_back(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(V1_FULL), encoding="utf-8")
        cfg = load_config()
        assert cfg["schema_version"] == 2
        assert cfg["accent_auto"] is False
        assert cfg["width_percent"] == 90
        assert cfg["spotify_client_id"] == V1_FULL["spotify_client_id"]
        # Migration is persisted atomically right away.
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk == cfg
        assert on_disk["schema_version"] == 2
        assert "spotify_client_secret" not in on_disk

    def test_explicit_schema_version_1_migrates(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 1, "highlight_color": "#ff0000"}),
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg["schema_version"] == 2
        assert cfg["accent_auto"] is False
        assert cfg["highlight_color"] == "#ff0000"

    def test_v2_file_not_rewritten(self, settings_path: Path) -> None:
        text = json.dumps(DEFAULTS, indent=2)
        settings_path.write_text(text, encoding="utf-8")
        cfg = load_config()
        assert cfg == DEFAULTS
        assert settings_path.read_text(encoding="utf-8") == text

    def test_clamps_applied_to_disk_values(self, settings_path: Path) -> None:
        """Out-of-range values from disk are clamped on load, not just migration."""
        bad = copy.deepcopy(DEFAULTS)
        bad.update(
            {
                "font_size": 100,
                "bg_opacity": 2.5,
                "sync_offset_ms": -9000,
                "width_percent": 10,
                "lines_visible": 99,
                "max_line_width_percent": 10,
                "poll_interval_ms": 50,
                "fps_cap": 45,
            }
        )
        settings_path.write_text(json.dumps(bad), encoding="utf-8")
        cfg = load_config()
        assert cfg["font_size"] == 48
        assert cfg["bg_opacity"] == 1.0
        assert cfg["sync_offset_ms"] == -5000
        assert cfg["width_percent"] == 30
        assert cfg["lines_visible"] == 7
        assert cfg["max_line_width_percent"] == 50
        assert cfg["poll_interval_ms"] == 1000
        assert cfg["fps_cap"] == 60

    def test_fps_cap_zero_means_display_rate(self, settings_path: Path) -> None:
        good = copy.deepcopy(DEFAULTS)
        good["fps_cap"] = 0
        settings_path.write_text(json.dumps(good), encoding="utf-8")
        assert load_config()["fps_cap"] == 0

    def test_enum_values_fall_back(self, settings_path: Path) -> None:
        bad = copy.deepcopy(DEFAULTS)
        bad.update(
            {
                "style_preset": "fancy",
                "word_motion": "wild",
                "alignment": "right",
                "fill_mode": 7,
                "legibility_mode": "neon",
                "animation_budget": "max",
                "position_preset": "left-center",
            }
        )
        settings_path.write_text(json.dumps(bad, default=str), encoding="utf-8")
        cfg = load_config()
        assert cfg["style_preset"] == "panel"
        assert cfg["word_motion"] == "subtle"
        assert cfg["alignment"] == "left"
        assert cfg["fill_mode"] == "white"
        assert cfg["legibility_mode"] == "shadow"
        assert cfg["animation_budget"] == "full"
        assert cfg["position_preset"] == "top-center"

    def test_hotkeys_deep_merge_partial(self, settings_path: Path) -> None:
        partial = {
            "schema_version": 2,
            "hotkeys": {"toggle_visible": "Ctrl+Shift+L", "offset_plus": ""},
        }
        settings_path.write_text(json.dumps(partial), encoding="utf-8")
        hotkeys = load_config()["hotkeys"]
        # User customization wins.
        assert hotkeys["toggle_visible"] == "Ctrl+Shift+L"
        # Empty string = deliberately disabled; preserved.
        assert hotkeys["offset_plus"] == ""
        # Missing actions are filled in from DEFAULTS.
        assert hotkeys["toggle_clickthrough"] == "Ctrl+Alt+F10"
        assert hotkeys["offset_minus"] == "Ctrl+Alt+Left"
        assert hotkeys["offset_reset"] == "Ctrl+Alt+0"

    def test_hotkeys_non_string_value_dropped(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "hotkeys": {"toggle_visible": 123}}),
            encoding="utf-8",
        )
        assert load_config()["hotkeys"]["toggle_visible"] == "Ctrl+Alt+F9"

    def test_hotkeys_not_a_dict(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "hotkeys": "all"}), encoding="utf-8"
        )
        assert load_config()["hotkeys"] == DEFAULTS["hotkeys"]

    def test_v1_config_gains_all_hotkey_actions(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(V1_FULL), encoding="utf-8")
        assert load_config()["hotkeys"] == DEFAULTS["hotkeys"]

    def test_unknown_keys_preserved(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "future_feature": 42}), encoding="utf-8"
        )
        assert load_config()["future_feature"] == 42

    def test_positions_entries_validated(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "positions": {
                        "\\\\.\\DISPLAY1": {"preset": "custom", "x": 10, "y": 20},
                        "broken": "nope",
                    },
                }
            ),
            encoding="utf-8",
        )
        positions = load_config()["positions"]
        assert positions == {"\\\\.\\DISPLAY1": {"preset": "custom", "x": 10, "y": 20}}

    def test_invalid_highlight_color_reset(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "highlight_color": "purple"}),
            encoding="utf-8",
        )
        assert load_config()["highlight_color"] == DEFAULTS["highlight_color"]

    def test_non_string_monitor_reset(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "monitor": 3}), encoding="utf-8"
        )
        assert load_config()["monitor"] == ""

    def test_bool_keys_repaired(self, settings_path: Path) -> None:
        settings_path.write_text(
            json.dumps({"schema_version": 2, "click_through": "on", "locked": 1}),
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg["click_through"] is True
        assert cfg["locked"] is True


# ---------------------------------------------------------------------------
# save_config — atomic persistence
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_roundtrip(self, settings_path: Path) -> None:
        cfg = load_config()
        cfg["font_size"] = 30
        cfg["hotkeys"]["toggle_visible"] = "Ctrl+Shift+L"
        save_config(cfg)
        assert json.loads(settings_path.read_text(encoding="utf-8")) == cfg

    def test_no_tmp_leftover(self, settings_path: Path) -> None:
        save_config(copy.deepcopy(DEFAULTS))
        leftovers = [p.name for p in settings_path.parent.iterdir()]
        assert leftovers == ["settings.json"]

    def test_overwrites_existing_file(self, settings_path: Path) -> None:
        settings_path.write_text("garbage that should disappear", encoding="utf-8")
        save_config(copy.deepcopy(DEFAULTS))
        assert json.loads(settings_path.read_text(encoding="utf-8")) == DEFAULTS

    def test_creates_parent_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nested = tmp_path / "deep" / "nested" / "settings.json"
        monkeypatch.setattr(paths, "CONFIG_DIR", nested.parent)
        monkeypatch.setattr(paths, "SETTINGS_PATH", nested)
        save_config(copy.deepcopy(DEFAULTS))
        assert json.loads(nested.read_text(encoding="utf-8")) == DEFAULTS

    def test_failed_serialization_keeps_previous_file(self, settings_path: Path) -> None:
        """If the new payload can't be written, the old file must survive intact."""
        good = copy.deepcopy(DEFAULTS)
        save_config(good)
        with pytest.raises(TypeError):
            save_config({"bad": {1, 2, 3}})  # sets are not JSON-serializable
        assert json.loads(settings_path.read_text(encoding="utf-8")) == good
        # And the failed attempt left no tmp file behind.
        leftovers = [p.name for p in settings_path.parent.iterdir()]
        assert leftovers == ["settings.json"]

    def test_non_ascii_preserved(self, settings_path: Path) -> None:
        cfg = copy.deepcopy(DEFAULTS)
        cfg["font_family"] = "游ゴシック Médium"
        save_config(cfg)
        assert (
            json.loads(settings_path.read_text(encoding="utf-8"))["font_family"]
            == "游ゴシック Médium"
        )


# ---------------------------------------------------------------------------
# end-to-end: full v1 -> v2 -> reload cycle
# ---------------------------------------------------------------------------


def test_full_migration_cycle(settings_path: Path) -> None:
    """v1 file -> migrated load -> persisted -> second load is a clean v2 read."""
    settings_path.write_text(json.dumps(V1_FULL), encoding="utf-8")
    first = load_config()
    second = load_config()  # now reads the persisted v2 file, no migration
    assert first == second
    assert second["schema_version"] == 2
    assert second["accent_auto"] is False
    assert second["highlight_color"] == "#aa00ff"
    assert "spotify_client_secret" not in second
