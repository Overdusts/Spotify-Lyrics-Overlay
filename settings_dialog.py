from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QPushButton, QColorDialog, QFontComboBox, QCheckBox, QLineEdit,
    QGroupBox, QFormLayout, QTabWidget, QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor


class SettingsDialog(QDialog):
    settings_applied = pyqtSignal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = dict(config)
        self.setWindowTitle("Lyrics Overlay Settings")
        self.setMinimumWidth(420)
        self._build_ui()
        self._set_dark_theme()

    def _set_dark_theme(self):
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #e0e0e0; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; padding-top: 14px; color: #ccc; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #ccc; }
            QLineEdit, QSpinBox, QFontComboBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #555; border-radius: 4px; padding: 4px; }
            QPushButton { background: #1DB954; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; }
            QPushButton:hover { background: #1ed760; }
            QPushButton#colorBtn { background: #333; border: 1px solid #666; min-width: 60px; }
            QSlider::groove:horizontal { background: #444; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #1DB954; width: 14px; margin: -4px 0; border-radius: 7px; }
            QCheckBox { color: #ccc; }
            QTabWidget::pane { border: 1px solid #444; background: #1e1e1e; }
            QTabBar::tab { background: #2a2a2a; color: #aaa; padding: 8px 16px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #1e1e1e; color: #1DB954; }
        """)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- Appearance Tab ---
        appear = QWidget()
        aform = QFormLayout(appear)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(self.font_combo.font())
        self.font_combo.setCurrentText(self.cfg["font_family"])
        aform.addRow("Font:", self.font_combo)

        self.font_size = QSpinBox()
        self.font_size.setRange(10, 60)
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
        aform.addRow("Width:", self.width_spin)

        self._text_color_btn = self._make_color_btn("text_color")
        aform.addRow("Text Color:", self._text_color_btn)

        self._hl_color_btn = self._make_color_btn("highlight_color")
        aform.addRow("Highlight Color:", self._hl_color_btn)

        self._bg_color_btn = self._make_color_btn("bg_color")
        aform.addRow("Background Color:", self._bg_color_btn)

        self.bg_opacity = QSlider(Qt.Horizontal)
        self.bg_opacity.setRange(0, 100)
        self.bg_opacity.setValue(int(self.cfg["bg_opacity"] * 100))
        aform.addRow("BG Opacity:", self.bg_opacity)

        self.bold_check = QCheckBox("Bold current line")
        self.bold_check.setChecked(self.cfg["bold_current"])
        aform.addRow(self.bold_check)

        self.title_check = QCheckBox("Show track title")
        self.title_check.setChecked(self.cfg["show_title"])
        aform.addRow(self.title_check)

        tabs.addTab(appear, "Appearance")

        # --- Spotify Tab ---
        spot = QWidget()
        sform = QFormLayout(spot)

        self.client_id = QLineEdit(self.cfg["spotify_client_id"])
        self.client_id.setPlaceholderText("Your Spotify Client ID")
        sform.addRow("Client ID:", self.client_id)

        self.client_secret = QLineEdit(self.cfg["spotify_client_secret"])
        self.client_secret.setPlaceholderText("Your Spotify Client Secret")
        self.client_secret.setEchoMode(QLineEdit.Password)
        sform.addRow("Client Secret:", self.client_secret)

        self.redirect_uri = QLineEdit(self.cfg["spotify_redirect_uri"])
        sform.addRow("Redirect URI:", self.redirect_uri)

        note = QLabel("Get credentials at developer.spotify.com\nCreate an app, add the redirect URI above.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        sform.addRow(note)

        tabs.addTab(spot, "Spotify")

        layout.addWidget(tabs)

        # Buttons
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
        color = self.cfg[key]
        btn.setStyleSheet(f"background: {color}; border: 1px solid #666; min-width: 60px; min-height: 24px;")
        btn.clicked.connect(lambda _, k=key, b=btn: self._pick_color(k, b))
        return btn

    def _pick_color(self, key, btn):
        c = QColorDialog.getColor(QColor(self.cfg[key]), self)
        if c.isValid():
            self.cfg[key] = c.name()
            btn.setStyleSheet(f"background: {c.name()}; border: 1px solid #666; min-width: 60px; min-height: 24px;")

    def _on_save(self):
        self.cfg["font_family"] = self.font_combo.currentText()
        self.cfg["font_size"] = self.font_size.value()
        self.cfg["lines_visible"] = self.lines_spin.value()
        self.cfg["width_percent"] = self.width_spin.value()
        self.cfg["bg_opacity"] = self.bg_opacity.value() / 100.0
        self.cfg["bold_current"] = self.bold_check.isChecked()
        self.cfg["show_title"] = self.title_check.isChecked()
        self.cfg["spotify_client_id"] = self.client_id.text().strip()
        self.cfg["spotify_client_secret"] = self.client_secret.text().strip()
        self.cfg["spotify_redirect_uri"] = self.redirect_uri.text().strip()

        from config import save_config
        save_config(self.cfg)
        self.settings_applied.emit(self.cfg)
        self.accept()
