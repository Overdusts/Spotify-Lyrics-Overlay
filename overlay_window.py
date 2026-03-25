import math
from PyQt5.QtWidgets import QWidget, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt, QRectF, QTimer, QPointF
from PyQt5.QtGui import (
    QPainter, QFont, QColor, QPainterPath, QFontMetrics, QPen,
    QRadialGradient, QLinearGradient, QTransform,
)


def ease_out_back(t):
    """Overshoot bounce easing — gives a satisfying pop."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_out_cubic(t):
    return 1 - pow(1 - t, 3)


class OverlayWindow(QWidget):
    def __init__(self, config, poller, sync_engine):
        super().__init__()
        self.cfg = config
        self.poller = poller
        self.sync = sync_engine
        self._drag_pos = None
        self._current_index = -1
        self._no_lyrics = False
        self._line_progress = 0.0
        self._prev_lit_count = 0

        self._setup_window()
        self._apply_config()

        # 60fps for smooth animation
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(16)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _apply_config(self):
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()

        w = int(screen.width() * self.cfg["width_percent"] / 100)
        font_size = self.cfg["font_size"]
        h = font_size * 3 + 30  # enough room for pop scale

        x = self.cfg["position_x"]
        if x < 0:
            x = (screen.width() - w) // 2
        y = self.cfg["position_y"]

        self.setGeometry(x, y, w, h)

        if self.cfg.get("click_through"):
            self.setWindowFlags(self.windowFlags() | Qt.WindowTransparentForInput)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowTransparentForInput)
        self.show()

    def update_config(self, config):
        self.cfg = config
        self._apply_config()
        self.update()

    def set_track_info(self, info):
        self._no_lyrics = False
        self._current_index = -1
        self._prev_lit_count = 0
        self.update()

    def set_no_lyrics(self):
        self._no_lyrics = True
        self.update()

    def _on_tick(self):
        if not self.sync.lines or not self.sync.is_synced:
            return

        pos_ms = self.poller.get_interpolated_position()
        new_idx = self.sync.get_current_index(pos_ms)

        if new_idx != self._current_index:
            self._prev_lit_count = 0
            self._current_index = new_idx

        timestamps = self.sync._timestamps
        if new_idx < len(timestamps):
            line_start = timestamps[new_idx]
            line_end = timestamps[new_idx + 1] if new_idx + 1 < len(timestamps) else line_start + 4000
            duration = max(line_end - line_start, 1)
            self._line_progress = max(0.0, min(1.0, (pos_ms - line_start) / duration))
        else:
            self._line_progress = 1.0

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        r = QRectF(self.rect())

        lines = self.sync.lines
        if not lines and not self._no_lyrics:
            painter.end()
            return

        highlight = QColor(self.cfg["highlight_color"])
        font_family = self.cfg["font_family"]
        font_size = self.cfg["font_size"]

        if self._no_lyrics or self._current_index < 0 or self._current_index >= len(lines):
            painter.end()
            return

        text = lines[self._current_index]
        words = text.split()
        if not words:
            painter.end()
            return

        f = QFont(font_family, font_size, QFont.Bold)
        fm = QFontMetrics(f)
        space_w = fm.horizontalAdvance(" ")
        word_widths = [fm.horizontalAdvance(w) for w in words]
        total_w = sum(word_widths) + space_w * (len(words) - 1)

        start_x = (r.width() - total_w) / 2
        center_y = r.height() / 2

        progress = self._line_progress
        # Word index as float — which word is currently popping
        lit_float = progress * len(words)

        x = start_x
        for i, word in enumerate(words):
            word_w = word_widths[i]
            word_center_x = x + word_w / 2
            word_center_y = center_y

            # Calculate animation state for this word
            word_trigger = i  # word lights up when lit_float passes i
            time_since_trigger = lit_float - word_trigger

            if time_since_trigger < 0:
                # Not yet reached — dim and small
                scale = 0.75
                opacity = 0.18
                color = QColor(255, 255, 255, int(255 * opacity))
                glow = False
            elif time_since_trigger < 1.0:
                # Currently popping in!
                t = min(time_since_trigger, 1.0)
                scale = 0.75 + 0.35 * ease_out_back(t)  # overshoot to 1.1 then settle ~1.0
                opacity = 0.18 + 0.82 * ease_out_cubic(t)
                # Color transitions from dim to highlight
                color = QColor(highlight)
                color.setAlpha(int(255 * opacity))
                glow = t > 0.1
            else:
                # Already lit — fully visible, settled
                fade_back = min((time_since_trigger - 1.0) * 0.5, 1.0)
                scale = 1.0 + 0.1 * (1 - fade_back)  # subtle settle from 1.1 to 1.0
                color = QColor(highlight)
                # Slight dim for older words so current one pops more
                brightness = max(0.6, 1.0 - fade_back * 0.4)
                color.setAlpha(int(255 * brightness))
                glow = fade_back < 0.5

            painter.save()

            # Transform: scale around word center
            painter.translate(word_center_x, word_center_y)
            painter.scale(scale, scale)
            painter.translate(-word_center_x, -word_center_y)

            # Build text path
            baseline_y = center_y + fm.ascent() / 2 - fm.descent() / 2
            word_path = QPainterPath()
            word_path.addText(x, baseline_y, f, word)

            # Glow effect for the actively popping word
            if glow and time_since_trigger < 2.0:
                glow_strength = 1.0 - min(time_since_trigger, 2.0) / 2.0
                glow_color = QColor(highlight)
                glow_color.setAlpha(int(50 * glow_strength))
                for radius in [6, 4, 2]:
                    painter.strokePath(word_path, QPen(glow_color, radius, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

            # Dark outline for readability
            painter.strokePath(word_path, QPen(QColor(0, 0, 0, 180), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

            # Fill word
            painter.fillPath(word_path, color)

            painter.restore()

            x += word_w + space_w

        painter.end()

    # --- Dragging ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        pos = self.pos()
        self.cfg["position_x"] = pos.x()
        self.cfg["position_y"] = pos.y()
        from config import save_config
        save_config(self.cfg)
