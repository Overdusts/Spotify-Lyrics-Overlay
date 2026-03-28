import math
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QRectF, QTimer, QPointF
from PyQt5.QtGui import (
    QPainter, QFont, QColor, QPainterPath, QFontMetrics, QPen,
    QTransform,
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
        self._paused = False
        self._line_progress = 0.0

        # Font metrics cache — only recalculate when font settings change
        self._cached_font = None
        self._cached_fm = None
        self._cached_space_w = 0
        self._cached_font_key = None  # (family, size) tuple

        # Word width cache — only recalculate when line changes
        self._cached_line_index = -1
        self._cached_words = []
        self._cached_word_widths = []
        self._cached_total_w = 0

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
        screen = QApplication.primaryScreen().geometry()

        w = int(screen.width() * self.cfg["width_percent"] / 100)
        font_size = self.cfg["font_size"]
        lines_visible = self.cfg.get("lines_visible", 3)
        h = int(font_size * 1.8 * lines_visible + 30)

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

        # Invalidate font cache on config change
        self._cached_font_key = None

    def update_config(self, config):
        self.cfg = config
        self._apply_config()
        self.update()

    def set_track_info(self, info):
        self._no_lyrics = False
        self._paused = False
        self._current_index = -1
        self._cached_line_index = -1
        self.update()

    def set_no_lyrics(self):
        self._no_lyrics = True
        self.update()

    def set_paused(self):
        self._paused = True
        self.update()

    def set_resumed(self):
        self._paused = False
        self.update()

    def _get_font_and_metrics(self):
        """Return (QFont, QFontMetrics, space_width), cached between frames."""
        key = (self.cfg["font_family"], self.cfg["font_size"])
        if key != self._cached_font_key:
            self._cached_font = QFont(key[0], key[1], QFont.Bold)
            self._cached_fm = QFontMetrics(self._cached_font)
            self._cached_space_w = self._cached_fm.horizontalAdvance(" ")
            self._cached_font_key = key
            self._cached_line_index = -1  # force word width recalc
        return self._cached_font, self._cached_fm, self._cached_space_w

    def _get_word_widths(self, line_index, text, fm):
        """Return (words, widths, total_width), cached when line hasn't changed."""
        if line_index == self._cached_line_index:
            return self._cached_words, self._cached_word_widths, self._cached_total_w
        words = text.split()
        widths = [fm.horizontalAdvance(w) for w in words]
        space_w = self._cached_space_w
        total = sum(widths) + space_w * max(0, len(words) - 1)
        self._cached_line_index = line_index
        self._cached_words = words
        self._cached_word_widths = widths
        self._cached_total_w = total
        return words, widths, total

    def _on_tick(self):
        # Don't tick when paused or no lyrics
        if not self.poller.is_playing:
            return
        if not self.sync.lines or not self.sync.is_synced:
            return

        pos_ms = self.poller.get_interpolated_position()
        new_idx = self.sync.get_current_index(pos_ms)

        if new_idx != self._current_index:
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

        r = QRectF(self.rect())
        lines = self.sync.lines

        if not lines and not self._no_lyrics:
            painter.end()
            return

        if self._no_lyrics or self._current_index < 0 or self._current_index >= len(lines):
            painter.end()
            return

        f, fm, space_w = self._get_font_and_metrics()
        highlight = QColor(self.cfg["highlight_color"])
        dim_font = QFont(f)
        dim_font.setWeight(QFont.Normal)
        dim_fm = QFontMetrics(dim_font)

        lines_visible = self.cfg.get("lines_visible", 3)
        line_height = int(self.cfg["font_size"] * 1.8)

        # Calculate vertical layout: current line centered, others around it
        lines_above = (lines_visible - 1) // 2
        lines_below = lines_visible - 1 - lines_above
        center_y_base = r.height() / 2

        # Draw surrounding lines (dimmed, no animation)
        for offset in range(-lines_above, lines_below + 1):
            idx = self._current_index + offset
            if idx < 0 or idx >= len(lines):
                continue

            y_center = center_y_base + offset * line_height

            if offset == 0:
                # Current line — draw with word animation
                self._paint_active_line(painter, r, f, fm, space_w, highlight, y_center)
            else:
                # Context line — dim, simple text
                text = lines[idx]
                if not text.strip():
                    continue
                dim_words = text.split()
                dim_widths = [dim_fm.horizontalAdvance(w) for w in dim_words]
                dim_space = dim_fm.horizontalAdvance(" ")
                total = sum(dim_widths) + dim_space * max(0, len(dim_words) - 1)
                x = (r.width() - total) / 2
                baseline_y = y_center + dim_fm.ascent() / 2 - dim_fm.descent() / 2

                # Fade more for lines further away
                dist = abs(offset)
                alpha = max(0.06, 0.15 - (dist - 1) * 0.04)

                for i, word in enumerate(dim_words):
                    path = QPainterPath()
                    path.addText(x, baseline_y, dim_font, word)
                    # Outline
                    painter.strokePath(path, QPen(QColor(0, 0, 0, int(120 * alpha / 0.15)), 2.5,
                                                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    painter.fillPath(path, QColor(255, 255, 255, int(255 * alpha)))
                    x += dim_widths[i] + dim_space

        painter.end()

    def _paint_active_line(self, painter, r, f, fm, space_w, highlight, center_y):
        """Paint the current lyric line with word-by-word pop animation."""
        lines = self.sync.lines
        text = lines[self._current_index]
        words, word_widths, total_w = self._get_word_widths(self._current_index, text, fm)
        if not words:
            return

        start_x = (r.width() - total_w) / 2
        baseline_y = center_y + fm.ascent() / 2 - fm.descent() / 2

        progress = self._line_progress
        lit_float = progress * len(words)

        x = start_x
        for i, word in enumerate(words):
            word_w = word_widths[i]
            word_cx = x + word_w / 2
            word_cy = center_y

            word_trigger = i
            time_since = lit_float - word_trigger

            if time_since < 0:
                scale = 0.75
                opacity = 0.18
                color = QColor(255, 255, 255, int(255 * opacity))
                glow = False
            elif time_since < 1.0:
                t = min(time_since, 1.0)
                scale = 0.75 + 0.35 * ease_out_back(t)
                opacity = 0.18 + 0.82 * ease_out_cubic(t)
                color = QColor(highlight)
                color.setAlpha(int(255 * opacity))
                glow = t > 0.1
            else:
                fade_back = min((time_since - 1.0) * 0.5, 1.0)
                scale = 1.0 + 0.1 * (1 - fade_back)
                color = QColor(highlight)
                brightness = max(0.6, 1.0 - fade_back * 0.4)
                color.setAlpha(int(255 * brightness))
                glow = fade_back < 0.5

            painter.save()

            painter.translate(word_cx, word_cy)
            painter.scale(scale, scale)
            painter.translate(-word_cx, -word_cy)

            word_path = QPainterPath()
            word_path.addText(x, baseline_y, f, word)

            # Glow for active word
            if glow and time_since < 2.0:
                glow_strength = 1.0 - min(time_since, 2.0) / 2.0
                glow_color = QColor(highlight)
                glow_color.setAlpha(int(50 * glow_strength))
                for radius in [6, 4, 2]:
                    painter.strokePath(word_path, QPen(glow_color, radius,
                                                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

            # Dark outline
            painter.strokePath(word_path, QPen(QColor(0, 0, 0, 180), 3.5,
                                               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            # Fill
            painter.fillPath(word_path, color)

            painter.restore()
            x += word_w + space_w

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
