from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QPushButton, QColorDialog, QFontComboBox, QCheckBox, QLineEdit,
    QFormLayout, QTabWidget, QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor


class SettingsDialog(QDialog):
    settings_applied = pyqtSignal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = dict(config)
        self.setWindowTitle("Lyrics Overlay Settings")
        self.setMinimumWidth(460)
        self._build_ui()
        self._set_dark_theme()

    def _set_dark_theme(self):
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #ccc; }
            QLineEdit, QSpinBox, QFontComboBox {
                background: #2a2a2a; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px; padding: 4px;
            }
            QPushButton {
                background: #1DB954; color: white; border: none;
                border-radius: 4px; padding: 6px 16px; font-weight: bold;
            }
            QPushButton:hover { background: #1ed760; }
            QPushButton#colorBtn {
                background: #333; border: 1px solid #666; min-width: 60px;
            }
            QSlider::groove:horizontal {
                background: #444; height: 6px; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1DB954; width: 14px; margin: -4px 0; border-radius: 7px;
            }
            QCheckBox { color: #ccc; }
            QTabWidget::pane { border: 1px solid #444; background: #1e1e1e; }
            QTabBar::tab {
                background: #2a2a2a; color: #aaa; padding: 8px 16px;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background: #1e1e1e; color: #1DB954; }
        """)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- Appearance ---
        appear = QWidget()
        aform = QFormLayout(appear)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentText(self.cfg["font_family"])
        aform.addRow("Font:", self.font_combo)

        self.font_size = QSpinBox()
        self.font_size.setRange(10, 80)
        self.font_size.setValue(self.cfg["font_size"])
        aform.addRow("Font Size:", self.font_size)

        self.lines_spin = QSpinBox()
        self.lines_spin.setRange(1, 9)
        self.lines_spin.setValue(self.cfg["lines_visible"])
        aform.addRow("Visible Lines:", self.lines_spin)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(20, 100)
        self.width_spin.setValue(self.cfg["width_percent"])
        self.width_spin.setSuffix("%")
        aform.addRow("Overlay Width:", self.width_spin)

        self.wrap_width_spin = QSpinBox()
        self.wrap_width_spin.setRange(40, 100)
        self.wrap_width_spin.setValue(self.cfg.get("max_line_width_percent", 90))
        self.wrap_width_spin.setSuffix("%")
        aform.addRow("Wrap Width:", self.wrap_width_spin)

        self._hl_color_btn = self._make_color_btn("highlight_color")
        aform.addRow("Highlight Color:", self._hl_color_btn)

        self._bg_color_btn = self._make_color_btn("bg_color")
        aform.addRow("Background Color:", self._bg_color_btn)

        self.bg_opacity = QSlider(Qt.Horizontal)
        self.bg_opacity.setRange(0, 100)
        self.bg_opacity.setValue(int(self.cfg["bg_opacity"] * 100))
        aform.addRow("Background Opacity:", self.bg_opacity)

        self.click_through_check = QCheckBox("Click-through (mouse passes through overlay)")
        self.click_through_check.setChecked(self.cfg.get("click_through", True))
        aform.addRow(self.click_through_check)

        self.track_info_check = QCheckBox("Show track name briefly on song change")
        self.track_info_check.setChecked(self.cfg.get("show_track_info", True))
        aform.addRow(self.track_info_check)

        tabs.addTab(appear, "Appearance")

        # --- Sync ---
        sync = QWidget()
        sform = QFormLayout(sync)

        self.sync_offset = QSpinBox()
        self.sync_offset.setRange(-5000, 5000)
        self.sync_offset.setSingleStep(50)
        self.sync_offset.setSuffix(" ms")
        self.sync_offset.setValue(self.cfg.get("sync_offset_ms", 0))
        sform.addRow("Sync Offset:", self.sync_offset)
        sform.addRow(QLabel("<small>Positive = lyrics earlier, negative = later.<br>"
                            "Hotkey: Ctrl+Alt+Left/Right (±100ms), Ctrl+Alt+0 to reset.</small>"))

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(300, 5000)
        self.poll_interval.setSingleStep(100)
        self.poll_interval.setSuffix(" ms")
        self.poll_interval.setValue(self.cfg.get("poll_interval_ms", 1000))
        sform.addRow("Poll Interval:", self.poll_interval)
        sform.addRow(QLabel("<small>How often to check Spotify for position updates. "
                            "Lower = more responsive seeks, more API usage.</small>"))

        tabs.addTab(sync, "Sync")

        # --- Spotify ---
        spot = QWidget()
        spform = QFormLayout(spot)

        self.client_id = QLineEdit(self.cfg["spotify_client_id"])
        self.client_id.setPlaceholderText("Your Spotify Client ID")
        spform.addRow("Client ID:", self.client_id)

        self.client_secret = QLineEdit(self.cfg["spotify_client_secret"])
        self.client_secret.setPlaceholderText("Your Spotify Client Secret")
        self.client_secret.setEchoMode(QLineEdit.Password)
        spform.addRow("Client Secret:", self.client_secret)

        self.redirect_uri = QLineEdit(self.cfg["spotify_redirect_uri"])
        spform.addRow("Redirect URI:", self.redirect_uri)

        note = QLabel("Get credentials at developer.spotify.com.\n"
                      "Create an app, add the redirect URI above.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        spform.addRow(note)

        tabs.addTab(spot, "Spotify")

        # --- Shortcuts (read-only info) ---
        sh = QWidget()
        shform = QVBoxLayout(sh)
        shform.addWidget(QLabel(
            "<b>Global Hotkeys</b><br><br>"
            "<table cellpadding='4'>"
            "<tr><td><b>Ctrl+Alt+F9</b></td><td>Show / Hide overlay</td></tr>"
            "<tr><td><b>Ctrl+Alt+F10</b></td><td>Toggle click-through</td></tr>"
            "<tr><td><b>Ctrl+Alt+Left</b></td><td>Lyrics -100 ms (appear later)</td></tr>"
            "<tr><td><b>Ctrl+Alt+Right</b></td><td>Lyrics +100 ms (appear earlier)</td></tr>"
            "<tr><td><b>Ctrl+Alt+0</b></td><td>Reset sync offset</td></tr>"
            "</table>"))
        shform.addStretch()
        tabs.addTab(sh, "Shortcuts")

        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save && Apply")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #444;")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _make_color_btn(self, key):
        btn = QPushButton()
        btn.setObjectName("colorBtn")
        color = self.cfg.get(key, "#FFFFFF")
        btn.setStyleSheet(f"background: {color}; border: 1px solid #666; "
                          f"min-width: 60px; min-height: 24px;")
        btn.clicked.connect(lambda _, k=key, b=btn: self._pick_color(k, b))
        return btn

    def _pick_color(self, key, btn):
        c = QColorDialog.getColor(QColor(self.cfg.get(key, "#FFFFFF")), self)
        if c.isValid():
            self.cfg[key] = c.name()
            btn.setStyleSheet(f"background: {c.name()}; border: 1px solid #666; "
                              f"min-width: 60px; min-height: 24px;")

    def _on_save(self):
        self.cfg["font_family"] = self.font_combo.currentText()
        self.cfg["font_size"] = self.font_size.value()
        self.cfg["lines_visible"] = self.lines_spin.value()
        self.cfg["width_percent"] = self.width_spin.value()
        self.cfg["max_line_width_percent"] = self.wrap_width_spin.value()
        self.cfg["bg_opacity"] = self.bg_opacity.value() / 100.0
        self.cfg["click_through"] = self.click_through_check.isChecked()
        self.cfg["show_track_info"] = self.track_info_check.isChecked()
        self.cfg["sync_offset_ms"] = self.sync_offset.value()
        self.cfg["poll_interval_ms"] = self.poll_interval.value()
        self.cfg["spotify_client_id"] = self.client_id.text().strip()
        self.cfg["spotify_client_secret"] = self.client_secret.text().strip()
        self.cfg["spotify_redirect_uri"] = self.redirect_uri.text().strip()

        from config import save_config
        save_config(self.cfg)
        self.settings_applied.emit(self.cfg)
        self.accept()
