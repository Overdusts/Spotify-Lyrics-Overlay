from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont


def make_icon():
    """Create a simple programmatic tray icon (green music note on dark bg)."""
    px = QPixmap(64, 64)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1DB954"))
    p.setPen(QColor("#1DB954"))
    p.drawEllipse(8, 8, 48, 48)
    p.setPen(QColor("#fff"))
    f = QFont("Segoe UI", 28, QFont.Bold)
    p.setFont(f)
    p.drawText(px.rect(), 0x0084, "♪")  # AlignCenter
    p.end()
    return QIcon(px)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, overlay, open_settings_cb, parent=None):
        super().__init__(make_icon(), parent)
        self.overlay = overlay
        self.setToolTip("Spotify Lyrics Overlay")

        menu = QMenu()

        toggle_action = QAction("Show / Hide  (Ctrl+Alt+F9)", menu)
        toggle_action.triggered.connect(self._toggle_overlay)
        menu.addAction(toggle_action)

        clickthrough_action = QAction("Toggle Click-Through  (Ctrl+Alt+F10)", menu)
        clickthrough_action.triggered.connect(self._toggle_clickthrough)
        menu.addAction(clickthrough_action)

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(open_settings_cb)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activate)

    def _toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()

    def _toggle_clickthrough(self):
        from config import save_config
        self.overlay.cfg["click_through"] = not self.overlay.cfg.get("click_through", False)
        self.overlay.update_config(self.overlay.cfg)
        save_config(self.overlay.cfg)

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_overlay()

    def _quit(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
