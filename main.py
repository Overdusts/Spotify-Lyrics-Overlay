import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt

from config import load_config, save_config
from lyrics_sync import LyricSyncEngine
from lyrics_fetcher import fetch_lyrics
from settings_dialog import SettingsDialog


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = load_config()

    # Check for Spotify credentials
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
                "4. Add redirect URI: http://localhost:8888/callback\n\n"
                "Run the app again after setting up credentials.")
            sys.exit(1)

    # Connect to Spotify
    from auth import get_spotify_client
    try:
        sp = get_spotify_client(cfg["spotify_client_id"], cfg["spotify_client_secret"], cfg["spotify_redirect_uri"])
        # Test connection
        sp.current_playback()
    except Exception as e:
        QMessageBox.critical(None, "Spotify Auth Error",
            f"Could not connect to Spotify:\n{e}\n\nCheck your credentials and try again.")
        sys.exit(1)

    # Create components
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
        dlg.settings_applied.connect(on_applied)
        dlg.exec_()

    tray = TrayIcon(overlay, open_settings)
    tray.show()

    # Wire signals
    def on_track_changed(info):
        overlay.set_track_info(info)
        duration_s = info["duration_ms"] / 1000.0
        lyrics = fetch_lyrics(info["name"], info["artist"], duration_s)
        if lyrics:
            sync_engine.set_lyrics(lyrics)
            overlay._current_index = 0
            overlay.update()
        else:
            sync_engine.set_lyrics([])
            overlay.set_no_lyrics()

    poller.track_changed.connect(on_track_changed)
    poller.start()

    exit_code = app.exec_()
    poller.stop()
    poller.wait(2000)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
