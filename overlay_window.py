import time
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import (
    QPainter, QFont, QColor, QPainterPath, QFontMetrics, QPen,
    QLinearGradient,
)


def ease_out_cubic(t):
    return 1 - pow(1 - t, 3)


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def lerp(a, b, t):
    return a + (b - a) * t


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

        # Smooth scroll state
        self._scroll_offset = 0.0      # current animated offset (float line index)
        self._scroll_target = 0.0      # target offset (integer line index)
        self._scroll_velocity = 0.0
        self._last_tick_time = time.monotonic()

        # Font metrics cache
        self._cached_font = None
        self._cached_dim_font = None
        self._cached_fm = None
        self._cached_dim_fm = None
        self._cached_space_w = 0
        self._cached_dim_space_w = 0
        self._cached_font_key = None

        # Word width cache for active line
        self._cached_line_index = -1
        self._cached_words = []
        self._cached_word_widths = []
        self._cached_total_w = 0

        self._setup_window()
        self._apply_config()

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
        h = int(font_size * 2.0 * lines_visible + 40)

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
        self._scroll_offset = 0.0
        self._scroll_target = 0.0
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

    def _get_fonts(self):
        """Return cached fonts and metrics."""
        key = (self.cfg["font_family"], self.cfg["font_size"])
        if key != self._cached_font_key:
            self._cached_font = QFont(key[0], key[1], QFont.Bold)
            self._cached_fm = QFontMetrics(self._cached_font)
            self._cached_space_w = self._cached_fm.horizontalAdvance(" ")
            self._cached_dim_font = QFont(key[0], key[1], QFont.Normal)
            self._cached_dim_fm = QFontMetrics(self._cached_dim_font)
            self._cached_dim_space_w = self._cached_dim_fm.horizontalAdvance(" ")
            self._cached_font_key = key
            self._cached_line_index = -1
        return (self._cached_font, self._cached_fm, self._cached_space_w,
                self._cached_dim_font, self._cached_dim_fm, self._cached_dim_space_w)

    def _get_word_widths(self, line_index, text, fm):
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
        now = time.monotonic()
        dt = min(now - self._last_tick_time, 0.05)  # cap at 50ms
        self._last_tick_time = now

        if not self.sync.lines or not self.sync.is_synced:
            return

        if self.poller.is_playing:
            pos_ms = self.poller.get_interpolated_position()
            new_idx = self.sync.get_current_index(pos_ms)

            if new_idx != self._current_index:
                self._current_index = new_idx
                self._scroll_target = float(new_idx)

            timestamps = self.sync._timestamps
            if new_idx < len(timestamps):
                line_start = timestamps[new_idx]
                line_end = timestamps[new_idx + 1] if new_idx + 1 < len(timestamps) else line_start + 4000
                duration = max(line_end - line_start, 1)
                self._line_progress = max(0.0, min(1.0, (pos_ms - line_start) / duration))
            else:
                self._line_progress = 1.0

        # Smooth scroll — spring-damper towards target
        diff = self._scroll_target - self._scroll_offset
        if abs(diff) < 0.001:
            self._scroll_offset = self._scroll_target
            self._scroll_velocity = 0.0
        else:
            # Critically damped spring for snappy but smooth motion
            spring = 25.0
            damping = 10.0
            force = diff * spring - self._scroll_velocity * damping
            self._scroll_velocity += force * dt
            self._scroll_offset += self._scroll_velocity * dt

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

        f, fm, space_w, dim_font, dim_fm, dim_space_w = self._get_fonts()
        highlight = QColor(self.cfg["highlight_color"])

        lines_visible = self.cfg.get("lines_visible", 3)
        line_height = int(self.cfg["font_size"] * 2.0)

        center_y_base = r.height() / 2

        # How many extra lines to render for smooth scrolling
        render_extra = 2
        half = lines_visible // 2 + render_extra

        # Scroll offset relative to current target
        scroll_frac = self._scroll_offset - self._scroll_target

        for offset in range(-half, half + 1):
            idx = self._current_index + offset
            if idx < 0 or idx >= len(lines):
                continue

            text = lines[idx]
            if not text.strip():
                continue

            # Y position with smooth scroll offset
            visual_offset = offset + scroll_frac
            y_center = center_y_base + visual_offset * line_height

            # Skip if off-screen
            if y_center < -line_height or y_center > r.height() + line_height:
                continue

            # Fade at edges
            edge_fade = 1.0
            if abs(visual_offset) > half - 1:
                edge_fade = max(0.0, 1.0 - (abs(visual_offset) - (half - 1)))

            is_active = (idx == self._current_index)
            is_past = (idx < self._current_index)

            if is_active:
                self._paint_karaoke_line(painter, r, f, fm, space_w,
                                         highlight, y_center, edge_fade)
            else:
                self._paint_context_line(painter, r, dim_font, dim_fm, dim_space_w,
                                          text, y_center, is_past, highlight, edge_fade, offset)

        painter.end()

    def _paint_context_line(self, painter, r, font, fm, space_w,
                             text, center_y, is_past, highlight, edge_fade, offset):
        """Draw a context line — past lines in faded highlight, future lines dim white."""
        words = text.split()
        if not words:
            return
        widths = [fm.horizontalAdvance(w) for w in words]
        total = sum(widths) + space_w * max(0, len(words) - 1)
        x = (r.width() - total) / 2
        baseline_y = center_y + fm.ascent() / 2 - fm.descent() / 2

        dist = abs(offset)

        if is_past:
            # Past lines — faded highlight color (already sung)
            alpha = max(0.08, 0.25 - (dist - 1) * 0.06) * edge_fade
            color = QColor(highlight)
            color.setAlpha(int(255 * alpha))
            outline_alpha = int(100 * alpha / 0.25)
        else:
            # Future lines — dim white
            alpha = max(0.06, 0.18 - (dist - 1) * 0.04) * edge_fade
            color = QColor(255, 255, 255, int(255 * alpha))
            outline_alpha = int(100 * alpha / 0.18)

        outline_color = QColor(0, 0, 0, min(255, outline_alpha))

        for i, word in enumerate(words):
            path = QPainterPath()
            path.addText(x, baseline_y, font, word)
            painter.strokePath(path, QPen(outline_color, 2.0,
                                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.fillPath(path, color)
            x += widths[i] + space_w

    def _paint_karaoke_line(self, painter, r, f, fm, space_w,
                             highlight, center_y, edge_fade):
        """Paint active line with karaoke fill — words fill left to right."""
        lines = self.sync.lines
        text = lines[self._current_index]
        words, word_widths, total_w = self._get_word_widths(self._current_index, text, fm)
        if not words:
            return

        start_x = (r.width() - total_w) / 2
        baseline_y = center_y + fm.ascent() / 2 - fm.descent() / 2

        progress = self._line_progress
        n = len(words)

        # Calculate cumulative positions for fill boundary
        word_starts = []
        pos = 0.0
        for i in range(n):
            word_starts.append(pos)
            pos += word_widths[i] + (space_w if i < n - 1 else 0)

        # Fill position in pixels from start
        fill_pixel = progress * total_w

        x = start_x
        for i, word in enumerate(words):
            word_w = word_widths[i]
            word_cx = x + word_w / 2
            word_local_start = word_starts[i]
            word_local_end = word_local_start + word_w

            # How much of this word is filled (0 to 1)
            if fill_pixel >= word_local_end:
                word_fill = 1.0
            elif fill_pixel <= word_local_start:
                word_fill = 0.0
            else:
                word_fill = (fill_pixel - word_local_start) / word_w

            # Scale: unfilled words are slightly smaller, filled pop up
            if word_fill <= 0:
                scale = 0.85
            elif word_fill < 1.0:
                t = ease_out_back(min(word_fill * 2, 1.0))
                scale = 0.85 + 0.2 * t  # pops to ~1.05 then settles
            else:
                scale = 1.0

            painter.save()

            # Scale around word center
            painter.translate(word_cx, center_y)
            painter.scale(scale, scale)
            painter.translate(-word_cx, -center_y)

            word_path = QPainterPath()
            word_path.addText(x, baseline_y, f, word)

            # 1) Dark outline for readability
            painter.strokePath(word_path, QPen(QColor(0, 0, 0, int(180 * edge_fade)), 3.0,
                                               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

            if word_fill <= 0:
                # Unfilled — dim white
                painter.fillPath(word_path, QColor(255, 255, 255, int(50 * edge_fade)))
            elif word_fill >= 1.0:
                # Fully filled — bright highlight with subtle glow
                glow_color = QColor(highlight)
                glow_color.setAlpha(int(40 * edge_fade))
                painter.strokePath(word_path, QPen(glow_color, 4,
                                                    Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                filled = QColor(highlight)
                filled.setAlpha(int(255 * edge_fade))
                painter.fillPath(word_path, filled)
            else:
                # Partially filled — clip-based karaoke fill
                # Draw dim base
                painter.fillPath(word_path, QColor(255, 255, 255, int(50 * edge_fade)))

                # Clip to filled portion and draw highlight
                clip_x = x + word_w * word_fill
                painter.save()
                clip_rect = QRectF(x - 5, center_y - fm.height(), clip_x - x + 5, fm.height() * 2)
                painter.setClipRect(clip_rect)

                # Glow on the fill edge
                glow_color = QColor(highlight)
                glow_color.setAlpha(int(35 * edge_fade))
                painter.strokePath(word_path, QPen(glow_color, 4,
                                                    Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

                filled = QColor(highlight)
                filled.setAlpha(int(255 * edge_fade))
                painter.fillPath(word_path, filled)
                painter.restore()

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
