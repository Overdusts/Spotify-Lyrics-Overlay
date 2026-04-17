import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from config import load_config, save_config, migrate_legacy_config
from lyrics_sync import LyricSyncEngine
from lyrics_fetcher import fetch_lyrics, CACHE_INSTRUMENTAL
from settings_dialog import SettingsDialog


class LyricsFetchWorker(QThread):
    """Fetch lyrics in a background thread."""
    # Emits: (result, fetch_token)
    # result is list[(ms,text)] | 'INSTRUMENTAL' | None
    finished = pyqtSignal(object, object)

    def __init__(self, track_name, artist, duration_s, token, album=None):
        super().__init__()
        self._track_name = track_name
        self._artist = artist
        self._duration_s = duration_s
        self._token = token
        self._album = album

    def run(self):
        result = fetch_lyrics(self._track_name, self._artist,
                              self._duration_s, self._album)
        self.finished.emit(result, self._token)


def main():
    migrate_legacy_config()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = load_config()

    # Spotify credentials check
    if not cfg["spotify_client_id"] or not cfg["spotify_client_secret"]:
        dlg = SettingsDialog(cfg)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.Tool)
        result = dlg.exec_()
        if result:
            cfg = dlg.cfg
        if not cfg["spotify_client_id"] or not cfg["spotify_client_secret"]:
            QMessageBox.warning(None, "Spotify Lyrics Overlay",
                "Spotify credentials are required.\n\n"
                "1. Go to developer.spotify.com\n"
                "2. Create an app\n"
                "3. Copy Client ID and Secret\n"
                "4. Add redirect URI: http://127.0.0.1:8888/callback\n\n"
                "Run the app again after setting up credentials.")
            sys.exit(1)

    from auth import get_spotify_client
    try:
        sp = get_spotify_client(cfg["spotify_client_id"],
                                cfg["spotify_client_secret"],
                                cfg["spotify_redirect_uri"])
        sp.current_playback()
    except Exception as e:
        QMessageBox.critical(None, "Spotify Auth Error",
            f"Could not connect to Spotify:\n{e}\n\nCheck your credentials and try again.")
        sys.exit(1)

    from spotify_poller import SpotifyPoller
    from overlay_window import OverlayWindow
    from tray_icon import TrayIcon

    sync_engine = LyricSyncEngine()
    poller = SpotifyPoller(sp, cfg["poll_interval_ms"])
    overlay = OverlayWindow(cfg, poller, sync_engine)
    overlay.show()

    def open_settings():
        dlg = SettingsDialog(cfg)
        def on_applied(new_cfg):
            nonlocal cfg
            cfg = new_cfg
            overlay.update_config(cfg)
            poller.set_poll_interval(cfg.get("poll_interval_ms", 1000))
        dlg.settings_applied.connect(on_applied)
        dlg.exec_()

    tray = TrayIcon(overlay, open_settings)
    tray.show()

    # --- Track + lyrics wiring ---
    state = {"fetch_worker": None, "fetch_token": None}

    def on_lyrics_fetched(result, token):
        if token != state["fetch_token"]:
            return
        if result == CACHE_INSTRUMENTAL:
            sync_engine.set_instrumental()
            overlay.set_instrumental()
        elif result:
            sync_engine.set_lyrics(result)
            overlay.set_lyrics_ready()
        else:
            sync_engine.clear()
            overlay.set_no_lyrics()
        state["fetch_worker"] = None

    def on_track_changed(info):
        # Use proper track_id (passed through info) for staleness check
        token = (info.get("name", ""), info.get("artist", ""),
                 info.get("duration_ms", 0))
        state["fetch_token"] = token
        sync_engine.clear()
        overlay.set_track_info(info)

        worker = LyricsFetchWorker(
            info["name"], info["artist"],
            info["duration_ms"] / 1000.0,
            token, album=info.get("album"),
        )
        worker.finished.connect(on_lyrics_fetched)
        state["fetch_worker"] = worker
        worker.start()

    poller.track_changed.connect(on_track_changed)
    # Pause/resume handled naturally via poller.is_playing in overlay tick
    poller.start()

    # --- Global hotkeys ---
    hotkey_listener = None
    try:
        from hotkeys import HotkeyListener
        hotkey_listener = HotkeyListener()

        def toggle_visibility():
            if overlay.isVisible():
                overlay.hide()
            else:
                overlay.show()

        def toggle_clickthrough():
            cfg["click_through"] = not cfg.get("click_through", False)
            overlay.update_config(cfg)
            save_config(cfg)
            state_msg = "Click-through ON" if cfg["click_through"] else "Click-through OFF"
            overlay.show_status(state_msg)

        def adjust_offset(delta_ms):
            if delta_ms == 0:
                cfg["sync_offset_ms"] = 0
            else:
                cfg["sync_offset_ms"] = cfg.get("sync_offset_ms", 0) + delta_ms
            save_config(cfg)
            off = cfg["sync_offset_ms"]
            sign = "+" if off > 0 else ""
            overlay.show_status(f"Sync offset: {sign}{off} ms")

        hotkey_listener.toggle_visible.connect(toggle_visibility)
        hotkey_listener.toggle_clickthrough.connect(toggle_clickthrough)
        hotkey_listener.offset_changed.connect(adjust_offset)
        hotkey_listener.start()
    except Exception:
        pass

    exit_code = app.exec_()
    poller.stop()
    poller.wait(2000)
    if hotkey_listener:
        hotkey_listener.stop()
        hotkey_listener.wait(1000)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
