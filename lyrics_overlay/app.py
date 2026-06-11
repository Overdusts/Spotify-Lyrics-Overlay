"""Composition root: builds, wires, runs, and tears down the whole app."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from lyrics_overlay import config, logsetup, paths
from lyrics_overlay.core.clock import PlaybackClock
from lyrics_overlay.core.palette import extract_palette
from lyrics_overlay.models import DEFAULT_PALETTE, Palette, TrackInfo

log = logging.getLogger(__name__)


def _image_pixels_48(image: QImage) -> list[tuple[int, int, int]]:
    small = image.scaled(
        48, 48,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_RGB32)
    pixels: list[tuple[int, int, int]] = []
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            pixels.append((c.red(), c.green(), c.blue()))
    return pixels


class _Authorizer(QObject):
    """Runs PKCE auth on a worker thread, reports back on the main thread."""

    done = Signal(bool, str)

    def __init__(self, redirect_uri: str, parent: QObject | None = None):
        super().__init__(parent)
        self.redirect_uri = redirect_uri
        self.client = None

    def start(self, client_id: str, done_cb) -> None:
        conn = self.done.connect(done_cb)

        def work() -> None:
            from lyrics_overlay.sources.spotify_auth import AuthFailed, build_client
            try:
                sp = build_client(client_id, self.redirect_uri)
                sp.me()  # force token acquisition now
            except AuthFailed as e:
                self.done.emit(False, e.user_message)
            except Exception as e:  # noqa: BLE001 — boundary
                log.exception("authorization failed")
                self.done.emit(False, str(e))
            else:
                self.client = sp
                self.done.emit(True, "")

        threading.Thread(target=work, daemon=True, name="spotify-auth").start()
        # caller is responsible for disconnecting via the returned connection if needed
        self._last_conn = conn


class Application:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.cfg: dict = {}
        self.qapp: Optional[QApplication] = None
        self.clock = PlaybackClock()
        self.source = None          # SpotifyPoller | DemoSource
        self.sp = None              # spotipy client
        self.lyrics = None          # LyricsService
        self.lyrics_cache = None    # LyricsCache
        self.artwork = None         # ArtworkLoader
        self.overlay = None         # OverlayWindow
        self.tray = None            # TrayIcon
        self.hotkeys = None         # HotkeyManager
        self.fullscreen = None      # FullscreenWatcher
        self.topmost = None         # TopmostReasserter
        self.settings_dialog = None
        self.current_track: TrackInfo | None = None
        self.user_hidden = False
        self.auto_hidden = False
        self.auth_balloon_shown = False

    # ---------------------------------------------------------------- startup

    def run(self) -> int:
        logsetup.guard_std_streams()
        logsetup.setup_logging(self.args.log_level)
        paths.ensure_dirs()

        self.qapp = QApplication(sys.argv[:1])
        self.qapp.setApplicationName("LyricOverlay")
        self.qapp.setQuitOnLastWindowClosed(False)

        if self.args.reset_config and paths.SETTINGS_PATH.exists():
            paths.SETTINGS_PATH.unlink()
            log.info("config reset by --reset-config")

        if not self.args.demo:
            from lyrics_overlay.win.instance import acquire_single_instance
            if not acquire_single_instance(self._on_activate_from_second_instance):
                log.info("another instance is running — activated it and exiting")
                return 0

        self.cfg = config.load_config()
        self._v1_migration_side_effects()

        if self.args.demo:
            self._build_demo_source()
        else:
            if not self._ensure_spotify():
                return 0 if self._became_demo else 1

        self._build_ui()
        self._wire()
        self._start()

        rc = self.qapp.exec()
        self._shutdown()
        return rc

    def _v1_migration_side_effects(self) -> None:
        """v1 tokens were confidential-flow; PKCE can't refresh them."""
        if paths.V1_TOKEN_PATH.exists():
            try:
                paths.V1_TOKEN_PATH.unlink()
            except OSError:
                log.warning("could not remove v1 token cache", exc_info=True)
            else:
                log.info("removed v1 token cache (PKCE migration)")
                if self.cfg.get("spotify_client_id"):
                    QMessageBox.information(
                        None, "Lyric Overlay",
                        "Lyric Overlay was upgraded to a more secure Spotify login\n"
                        "(PKCE — your client secret is no longer needed or stored).\n\n"
                        "You'll be asked to authorize once in your browser.",
                    )

    # ------------------------------------------------------------- demo / spotify

    _became_demo = False

    def _build_demo_source(self) -> None:
        from lyrics_overlay.sources.demo_source import DemoSource
        self.source = DemoSource(self.clock)
        self._became_demo = True
        log.info("running in demo mode")

    def _ensure_spotify(self) -> bool:
        """Returns True when a source exists (Spotify or demo-via-wizard)."""
        if not self.cfg.get("spotify_client_id"):
            choice = self._run_onboarding()
            if choice == "cancelled":
                return False
            if choice == "demo":
                self._build_demo_source()
                return True
            # "connected": client stored by authorize callback
        if self.sp is None:
            from lyrics_overlay.sources.spotify_auth import AuthFailed, build_client
            try:
                self.sp = build_client(
                    self.cfg["spotify_client_id"], self.cfg["spotify_redirect_uri"]
                )
                self.sp.me()
            except AuthFailed as e:
                QMessageBox.critical(None, "Spotify connection failed", e.user_message)
                choice = self._run_onboarding()
                if choice == "demo":
                    self._build_demo_source()
                    return True
                if choice != "connected" or self.sp is None:
                    return False
            except Exception as e:  # noqa: BLE001 — boundary
                log.exception("unexpected auth failure")
                QMessageBox.critical(None, "Spotify connection failed", str(e))
                return False
        from lyrics_overlay.sources.spotify_source import SpotifyPoller
        self.source = SpotifyPoller(self.sp, self.clock, self.cfg["poll_interval_ms"])
        return True

    def _run_onboarding(self) -> str:
        from lyrics_overlay.ui.onboarding import OnboardingWizard
        authorizer = _Authorizer(self.cfg.get(
            "spotify_redirect_uri", config.DEFAULTS["spotify_redirect_uri"]))

        def authorize(client_id: str, done_cb) -> None:
            def on_done(ok: bool, err: str) -> None:
                if ok:
                    self.sp = authorizer.client
                    self.cfg["spotify_client_id"] = client_id
                    config.save_config(self.cfg)
                done_cb(ok, err)
            authorizer.start(client_id, on_done)

        wizard = OnboardingWizard(self.cfg, authorize)
        wizard.exec()
        return wizard.choice

    # ---------------------------------------------------------------- build & wire

    def _build_ui(self) -> None:
        from lyrics_overlay.lyrics.cache import LyricsCache
        from lyrics_overlay.lyrics.service import LyricsService
        from lyrics_overlay.ui.artwork import ArtworkLoader
        from lyrics_overlay.ui.overlay import OverlayWindow
        from lyrics_overlay.ui.tray import TrayIcon
        from lyrics_overlay.win.hotkeys import HotkeyManager

        self.lyrics_cache = LyricsCache(paths.LYRICS_CACHE_DIR)
        self.lyrics = LyricsService(cache=self.lyrics_cache)
        self.artwork = ArtworkLoader()
        self.artwork.set_cinema(self.cfg.get("style_preset") == "cinema")

        def position_ms() -> int:
            return self.source.position_ms() + self.cfg.get("sync_offset_ms", 0)

        self.overlay = OverlayWindow(self.cfg, position_ms)
        self.tray = TrayIcon(self.cfg)
        self.hotkeys = HotkeyManager()

        from lyrics_overlay.win.fullscreen import FullscreenWatcher
        from lyrics_overlay.win.topmost import TopmostReasserter
        self.fullscreen = FullscreenWatcher(self.overlay)
        self.topmost = TopmostReasserter(self.overlay)

    def _wire(self) -> None:
        src, ovl, tray = self.source, self.overlay, self.tray

        src.track_changed.connect(self._on_track_changed)
        src.playback_state.connect(ovl.on_playback_state)
        src.connection_state.connect(self._on_connection_state)

        self.lyrics.lyrics_ready.connect(ovl.on_lyrics_ready)
        self.artwork.art_ready.connect(ovl.on_art_ready)
        self.artwork.art_large_ready.connect(ovl.on_art_ready)
        self.artwork.palette_ready.connect(self._on_palette_ready)

        self.hotkeys.toggle_visible.connect(self._toggle_visible)
        self.hotkeys.toggle_clickthrough.connect(self._toggle_clickthrough)
        self.hotkeys.offset_delta.connect(self._adjust_offset)

        tray.show_hide.connect(self._toggle_visible)
        tray.toggle_clickthrough.connect(self._toggle_clickthrough)
        tray.lock_toggled.connect(ovl.set_locked)
        tray.move_to_monitor.connect(ovl.move_to_screen)
        tray.resync.connect(self._resync_current)
        tray.open_settings.connect(self._open_settings)
        tray.run_demo.connect(self._spawn_demo)
        tray.quit_app.connect(self.qapp.quit)
        tray.messageClicked.connect(self._reconnect)

        self.fullscreen.fullscreen_changed.connect(self._on_fullscreen_changed)

    def _start(self) -> None:
        statuses = self.hotkeys.register_from_config(self.cfg.get("hotkeys", {}))
        failed = [a for a, (ok, _err) in statuses.items() if not ok]
        if failed:
            self.tray.show_balloon(
                "Some hotkeys unavailable",
                "In use by another app: " + ", ".join(failed)
                + ". Rebind them in Settings → Shortcuts.",
            )

        self.tray.show()
        self.overlay.apply_config(self.cfg)
        self.overlay.show()
        if not self.cfg.get("locked", True):
            self.overlay.set_locked(False)

        if self.cfg.get("show_over_games"):
            self.topmost.start()
        elif self.cfg.get("fullscreen_hide", True):
            self.fullscreen.start()

        self.source.start()

    # ---------------------------------------------------------------- handlers

    def _on_track_changed(self, track: TrackInfo) -> None:
        self.current_track = track
        self.overlay.on_track_changed(track)
        self.tray.set_track(track.name, track.artist)

        if self.args.demo or self._became_demo:
            from lyrics_overlay.sources.demo_source import demo_art_image, load_demo_track
            _info, doc = load_demo_track()
            self.overlay.on_lyrics_ready(track.id, doc)
            img = demo_art_image()
            self.overlay.on_art_ready(track.id, img)
            try:
                palette = extract_palette(_image_pixels_48(img))
            except Exception:  # noqa: BLE001 — palette is cosmetic
                log.exception("demo palette extraction failed")
                palette = DEFAULT_PALETTE
            self._on_palette_ready(track.id, palette)
            return

        if track.is_episode:
            return  # poller emits EPISODE connection state; no lyrics lookup
        self.lyrics.request(track)
        self.artwork.fetch(track)

    def _on_palette_ready(self, track_id: str, palette: Palette) -> None:
        if not self.cfg.get("accent_auto", True):
            return
        self.overlay.on_palette_ready(track_id, palette)
        self.tray.set_palette(palette)

    def _on_connection_state(self, kind: str, msg: str) -> None:
        self.overlay.on_connection_state(kind, msg)
        if kind == "AUTH_REQUIRED" and not self.auth_balloon_shown:
            self.auth_balloon_shown = True
            self.tray.show_balloon(
                "Spotify needs to reconnect",
                "Click here to re-authorize Lyric Overlay.",
            )
        elif kind == "OK":
            self.auth_balloon_shown = False

    def _toggle_visible(self) -> None:
        self.user_hidden = self.overlay.isVisible()
        self.auto_hidden = False
        self.overlay.toggle_visible()

    def _toggle_clickthrough(self) -> None:
        enabled = not self.cfg.get("click_through", True)
        self.cfg["click_through"] = enabled
        self.overlay.set_click_through(enabled)
        config.save_config(self.cfg)
        self.overlay.show_pill(
            "Click-through on" if enabled else "Click-through off")

    def _adjust_offset(self, delta_ms: int) -> None:
        off = 0 if delta_ms == 0 else self.cfg.get("sync_offset_ms", 0) + delta_ms
        off = max(-5000, min(5000, off))
        self.cfg["sync_offset_ms"] = off
        config.save_config(self.cfg)
        self.overlay.kick()
        sign = "+" if off > 0 else ""
        self.overlay.show_pill(f"Sync {sign}{off} ms")

    def _on_fullscreen_changed(self, fullscreen: bool) -> None:
        if not self.cfg.get("fullscreen_hide", True) or self.cfg.get("show_over_games"):
            return
        if fullscreen:
            if self.overlay.isVisible():
                self.auto_hidden = True
                self.overlay.hide()
        elif self.auto_hidden and not self.user_hidden:
            self.auto_hidden = False
            self.overlay.show()

    def _resync_current(self) -> None:
        if self.current_track and not (self.args.demo or self._became_demo):
            self.lyrics.resync(self.current_track)
            self.overlay.show_pill("Re-syncing lyrics…")

    def _spawn_demo(self) -> None:
        from PySide6.QtCore import QProcess
        import lyrics_overlay
        main_py = str(paths.Path(lyrics_overlay.__file__).parent.parent / "main.py")
        QProcess.startDetached(sys.executable, [main_py, "--demo"])

    def _on_activate_from_second_instance(self) -> None:
        self.user_hidden = False
        if self.overlay is not None:
            self.overlay.show()
            self.overlay.raise_()

    # ---------------------------------------------------------------- settings

    def _open_settings(self) -> None:
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        from lyrics_overlay.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self.cfg,
            hotkey_statuses=dict(self.hotkeys.statuses),
            cache_size_bytes=self.lyrics_cache.size_bytes(),
        )
        self.settings_dialog = dlg
        dlg.config_changed.connect(self._apply_config)
        dlg.reconnect_requested.connect(self._reconnect)
        dlg.disconnect_requested.connect(self._disconnect)
        dlg.run_wizard_requested.connect(self._rerun_wizard)
        dlg.demo_requested.connect(self._spawn_demo)
        dlg.resync_requested.connect(self._resync_current)
        dlg.clear_cache_requested.connect(self._clear_cache)
        dlg.open_logs_requested.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.LOG_DIR))))
        dlg.finished.connect(self._on_settings_closed)
        dlg.show()

    def _on_settings_closed(self, _result: int) -> None:
        if self.settings_dialog is not None:
            self.settings_dialog.deleteLater()
            self.settings_dialog = None

    def _apply_config(self, new_cfg: dict) -> None:
        old_startup = self.cfg.get("launch_at_startup", False)
        old_hotkeys = dict(self.cfg.get("hotkeys", {}))
        old_poll = self.cfg.get("poll_interval_ms", 1000)

        self.cfg.clear()
        self.cfg.update(new_cfg)

        self.overlay.apply_config(self.cfg)
        self.artwork.set_cinema(self.cfg.get("style_preset") == "cinema")

        if self.cfg.get("poll_interval_ms", 1000) != old_poll and hasattr(
                self.source, "set_poll_interval"):
            self.source.set_poll_interval(self.cfg["poll_interval_ms"])

        if self.cfg.get("hotkeys", {}) != old_hotkeys:
            self.hotkeys.unregister_all()
            statuses = self.hotkeys.register_from_config(self.cfg.get("hotkeys", {}))
            if self.settings_dialog is not None:
                self.settings_dialog.set_hotkey_statuses(statuses)

        if self.cfg.get("launch_at_startup", False) != old_startup:
            from lyrics_overlay.win.startup import set_launch_at_startup
            try:
                set_launch_at_startup(self.cfg["launch_at_startup"])
            except OSError:
                log.exception("startup registration failed")

        if self.cfg.get("show_over_games"):
            self.fullscreen.stop()
            self.topmost.start()
        else:
            self.topmost.stop()
            if self.cfg.get("fullscreen_hide", True):
                self.fullscreen.start()
            else:
                self.fullscreen.stop()

    def _reconnect(self) -> None:
        if self.args.demo or self._became_demo or not self.cfg.get("spotify_client_id"):
            return
        from lyrics_overlay.sources.spotify_auth import delete_token_cache
        self._stop_source()
        delete_token_cache()
        self.sp = None
        if self._ensure_spotify():
            self.source.track_changed.connect(self._on_track_changed)
            self.source.playback_state.connect(self.overlay.on_playback_state)
            self.source.connection_state.connect(self._on_connection_state)
            self.source.start()
            self.overlay.show_pill("Reconnected to Spotify")

    def _disconnect(self) -> None:
        from lyrics_overlay.sources.spotify_auth import delete_token_cache
        self._stop_source()
        delete_token_cache()
        self.sp = None
        self.overlay.on_connection_state("AUTH_REQUIRED", "Disconnected")
        self.tray.show_balloon("Disconnected",
                               "Spotify access removed. Reconnect from Settings → Account.")

    def _clear_cache(self) -> None:
        self.lyrics_cache.clear()
        self.overlay.show_pill("Lyrics cache cleared")

    # ---------------------------------------------------------------- shutdown

    def _stop_source(self) -> None:
        if self.source is None:
            return
        try:
            self.source.stop()
            if hasattr(self.source, "wait"):
                self.source.wait(3000)
        except Exception:  # noqa: BLE001 — boundary
            log.exception("source stop failed")

    def _shutdown(self) -> None:
        log.info("shutting down")
        try:
            self.hotkeys.unregister_all()
        except Exception:  # noqa: BLE001
            log.exception("hotkey unregister failed")
        self.fullscreen.stop()
        self.topmost.stop()
        self.overlay.close()
        self._stop_source()
        if self.lyrics is not None:
            self.lyrics.shutdown(2000)
        config.save_config(self.cfg)
        self.tray.hide()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="lyric-overlay",
                                     description="Spotify lyrics overlay")
    parser.add_argument("--demo", action="store_true",
                        help="run with a bundled demo track (no Spotify needed)")
    parser.add_argument("--fps-log", action="store_true",
                        help="log frame-time histogram")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--reset-config", action="store_true")
    args = parser.parse_args(argv)

    if args.fps_log:
        import os
        os.environ["LYRICOVERLAY_FPS_LOG"] = "1"

    return Application(args).run()
