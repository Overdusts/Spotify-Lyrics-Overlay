import time
import math
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import (
    QPainter, QFont, QColor, QPainterPath, QFontMetrics, QPen,
)


def ease_out_cubic(t):
    return 1 - pow(1 - t, 3)


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


class OverlayState:
    IDLE = "idle"           # no song playing
    LOADING = "loading"     # fetching lyrics
    LYRICS = "lyrics"       # showing lyrics
    INSTRUMENTAL = "instrumental"
    NO_LYRICS = "no_lyrics"


class OverlayWindow(QWidget):
    def __init__(self, config, poller, sync_engine):
        super().__init__()
        self.cfg = config
        self.poller = poller
        self.sync = sync_engine
        self._drag_pos = None
        self._current_index = -1
        self._line_progress = 0.0
        self._state = OverlayState.IDLE

        # Track info (displayed briefly on change)
        self._track_name = ""
        self._track_artist = ""
        self._track_info_shown_at = 0.0

        # Status message (e.g. "Sync offset: +200ms") shown briefly
        self._status_message = ""
        self._status_shown_at = 0.0

        # Smooth scroll
        self._scroll_offset = 0.0
        self._scroll_target = 0.0
        self._scroll_velocity = 0.0
        self._last_tick_time = time.monotonic()

        # Caches
        self._cached_font_key = None
        self._cached_font = None
        self._cached_fm = None
        self._cached_space_w = 0
        self._cached_dim_font = None
        self._cached_dim_fm = None
        self._cached_dim_space_w = 0

        # Per-line wrap cache — keyed by (line_index, font_key, max_width)
        self._wrap_cache = {}

        # Dirty tracking — only repaint when needed
        self._dirty = True
        self._last_paint_state = None

        self._setup_window()
        self._apply_config()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(16)

    # --- Window setup ---
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
        # Extra height for potential wrap + track info header
        h = int(font_size * 2.2 * (lines_visible + 1) + 50)

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
        self._wrap_cache.clear()
        self._dirty = True

    def update_config(self, config):
        self.cfg = config
        self._apply_config()

    # --- State management ---
    def set_track_info(self, info):
        self._track_name = info.get("name", "")
        self._track_artist = info.get("artist", "")
        self._track_info_shown_at = time.monotonic()
        self._state = OverlayState.LOADING
        self._current_index = -1
        self._scroll_offset = 0.0
        self._scroll_target = 0.0
        self._wrap_cache.clear()
        self._dirty = True

    def set_lyrics_ready(self):
        self._state = OverlayState.LYRICS
        self._current_index = 0
        self._scroll_offset = 0.0
        self._scroll_target = 0.0
        self._dirty = True

    def set_no_lyrics(self):
        self._state = OverlayState.NO_LYRICS
        self._dirty = True

    def set_instrumental(self):
        self._state = OverlayState.INSTRUMENTAL
        self._dirty = True

    def set_idle(self):
        self._state = OverlayState.IDLE
        self._dirty = True

    def show_status(self, message):
        """Show a transient status message (sync offset change etc.)."""
        self._status_message = message
        self._status_shown_at = time.monotonic()
        self._dirty = True

    # --- Font caching ---
    def _get_fonts(self):
        key = (self.cfg["font_family"], self.cfg["font_size"])
        if key != self._cached_font_key:
            self._cached_font = QFont(key[0], key[1], QFont.Bold)
            self._cached_fm = QFontMetrics(self._cached_font)
            self._cached_space_w = self._cached_fm.horizontalAdvance(" ")
            self._cached_dim_font = QFont(key[0], key[1], QFont.Normal)
            self._cached_dim_fm = QFontMetrics(self._cached_dim_font)
            self._cached_dim_space_w = self._cached_dim_fm.horizontalAdvance(" ")
            self._cached_font_key = key
            self._wrap_cache.clear()
        return (self._cached_font, self._cached_fm, self._cached_space_w,
                self._cached_dim_font, self._cached_dim_fm, self._cached_dim_space_w)

    def _wrap_line(self, text, fm, space_w, max_width, cache_key):
        """Wrap a line into rows that fit within max_width. Returns list of list of (word, width)."""
        if cache_key in self._wrap_cache:
            return self._wrap_cache[cache_key]
        words = text.split()
        if not words:
            self._wrap_cache[cache_key] = [[]]
            return [[]]

        rows = []
        current = []
        current_w = 0
        for w in words:
            ww = fm.horizontalAdvance(w)
            needed = ww if not current else current_w + space_w + ww
            if needed > max_width and current:
                rows.append(current)
                current = [(w, ww)]
                current_w = ww
            else:
                current.append((w, ww))
                current_w = needed
        if current:
            rows.append(current)
        self._wrap_cache[cache_key] = rows
        return rows

    # --- Ticking ---
    def _on_tick(self):
        if not self.isVisible():
            return

        now = time.monotonic()
        dt = min(now - self._last_tick_time, 0.05)
        self._last_tick_time = now

        need_update = self._dirty

        # Track info header fades after 4 seconds
        if self._track_info_shown_at > 0:
            age = now - self._track_info_shown_at
            if age < 4.5:
                need_update = True  # animating fade

        # Status message fades after 2 seconds
        if self._status_shown_at > 0:
            age = now - self._status_shown_at
            if age < 2.5:
                need_update = True

        # Only advance lyrics when playing + have synced lyrics
        if self._state == OverlayState.LYRICS and self.poller.is_playing and self.sync.is_synced:
            offset_ms = self.cfg.get("sync_offset_ms", 0)
            pos_ms = self.poller.get_interpolated_position() + offset_ms
            new_idx = self.sync.get_current_index(pos_ms)

            if new_idx != self._current_index:
                self._current_index = new_idx
                self._scroll_target = float(new_idx)
                need_update = True

            bounds = self.sync.line_bounds(new_idx)
            if bounds:
                line_start, line_end = bounds
                duration = max(line_end - line_start, 1)
                new_progress = max(0.0, min(1.0, (pos_ms - line_start) / duration))
                if abs(new_progress - self._line_progress) > 0.001:
                    self._line_progress = new_progress
                    need_update = True
            else:
                self._line_progress = 1.0

        # Smooth scroll spring
        diff = self._scroll_target - self._scroll_offset
        if abs(diff) > 0.001 or abs(self._scroll_velocity) > 0.001:
            spring = 25.0
            damping = 10.0
            force = diff * spring - self._scroll_velocity * damping
            self._scroll_velocity += force * dt
            self._scroll_offset += self._scroll_velocity * dt
            if abs(diff) < 0.001 and abs(self._scroll_velocity) < 0.01:
                self._scroll_offset = self._scroll_target
                self._scroll_velocity = 0.0
            need_update = True

        if need_update:
            self._dirty = False
            self.update()

    # --- Painting ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        r = QRectF(self.rect())
        bg_op = self.cfg.get("bg_opacity", 0.0)
        if bg_op > 0.01:
            bg = QColor(self.cfg.get("bg_color", "#000000"))
            bg.setAlphaF(bg_op)
            painter.setBrush(bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(r, 14, 14)

        f, fm, space_w, dim_font, dim_fm, dim_space_w = self._get_fonts()
        highlight = QColor(self.cfg["highlight_color"])

        # Paint track info header (fades in/out)
        self._paint_track_info(painter, r, dim_font, dim_fm)

        # Paint status message (overlay bottom)
        self._paint_status(painter, r, dim_font, dim_fm)

        # Paint main content based on state
        if self._state == OverlayState.IDLE:
            painter.end()
            return

        if self._state == OverlayState.LOADING:
            self._paint_center_message(painter, r, dim_font, dim_fm, "Loading lyrics…",
                                        pulse=True)
            painter.end()
            return

        if self._state == OverlayState.INSTRUMENTAL:
            self._paint_center_message(painter, r, f, fm, "♪  Instrumental  ♪",
                                        color=highlight, pulse=True)
            painter.end()
            return

        if self._state == OverlayState.NO_LYRICS:
            self._paint_center_message(painter, r, dim_font, dim_fm,
                                        "No lyrics available")
            painter.end()
            return

        # State: LYRICS
        lines = self.sync.lines
        if not lines or self._current_index < 0 or self._current_index >= len(lines):
            painter.end()
            return

        lines_visible = self.cfg.get("lines_visible", 3)
        max_line_width_pct = self.cfg.get("max_line_width_percent", 90) / 100.0
        max_width = r.width() * max_line_width_pct
        line_height = int(self.cfg["font_size"] * 2.0)

        center_y_base = r.height() / 2
        scroll_frac = self._scroll_offset - self._scroll_target
        half = lines_visible // 2 + 2

        for offset in range(-half, half + 1):
            idx = self._current_index + offset
            if idx < 0 or idx >= len(lines):
                continue

            text = lines[idx]
            if not text.strip():
                continue

            visual_offset = offset + scroll_frac
            y_center = center_y_base + visual_offset * line_height
            if y_center < -line_height or y_center > r.height() + line_height:
                continue

            edge_fade = 1.0
            if abs(visual_offset) > half - 1:
                edge_fade = max(0.0, 1.0 - (abs(visual_offset) - (half - 1)))

            is_active = (idx == self._current_index)
            is_past = (idx < self._current_index)

            if is_active:
                self._paint_karaoke_wrapped(painter, r, f, fm, space_w,
                                              highlight, y_center, edge_fade,
                                              max_width, idx, text)
            else:
                self._paint_context_wrapped(painter, r, dim_font, dim_fm,
                                             dim_space_w, text, y_center,
                                             is_past, highlight, edge_fade,
                                             offset, max_width, idx)

        painter.end()

    def _paint_track_info(self, painter, r, font, fm):
        """Show track name briefly when song changes."""
        if not self.cfg.get("show_track_info", True):
            return
        if self._track_info_shown_at <= 0:
            return
        age = time.monotonic() - self._track_info_shown_at
        if age > 4.5:
            return

        # Fade in (0-0.3s), visible (0.3-3.5s), fade out (3.5-4.5s)
        if age < 0.3:
            alpha = age / 0.3
        elif age < 3.5:
            alpha = 1.0
        else:
            alpha = max(0.0, 1.0 - (age - 3.5) / 1.0)

        label = self._track_name
        if self._track_artist:
            label = f"{self._track_name}  ·  {self._track_artist}"

        # Draw at top
        small = QFont(font)
        small.setPointSize(max(9, self.cfg["font_size"] - 8))
        small_fm = QFontMetrics(small)
        tw = small_fm.horizontalAdvance(label)
        x = (r.width() - tw) / 2
        y = 14 + small_fm.ascent()

        path = QPainterPath()
        path.addText(x, y, small, label)
        painter.strokePath(path, QPen(QColor(0, 0, 0, int(180 * alpha)), 2.5,
                                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.fillPath(path, QColor(255, 255, 255, int(200 * alpha)))

    def _paint_status(self, painter, r, font, fm):
        """Show sync offset / other status briefly at bottom."""
        if self._status_shown_at <= 0:
            return
        age = time.monotonic() - self._status_shown_at
        if age > 2.5:
            return
        if age < 0.2:
            alpha = age / 0.2
        elif age < 1.8:
            alpha = 1.0
        else:
            alpha = max(0.0, 1.0 - (age - 1.8) / 0.7)

        small = QFont(font)
        small.setPointSize(max(9, self.cfg["font_size"] - 6))
        small_fm = QFontMetrics(small)
        tw = small_fm.horizontalAdvance(self._status_message)
        x = (r.width() - tw) / 2
        y = r.height() - 14

        path = QPainterPath()
        path.addText(x, y, small, self._status_message)
        painter.strokePath(path, QPen(QColor(0, 0, 0, int(200 * alpha)), 3.0,
                                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        highlight = QColor(self.cfg["highlight_color"])
        highlight.setAlpha(int(255 * alpha))
        painter.fillPath(path, highlight)

    def _paint_center_message(self, painter, r, font, fm, text, color=None, pulse=False):
        """Center a static message in the overlay."""
        if pulse:
            phase = (time.monotonic() % 1.5) / 1.5
            alpha = 0.5 + 0.5 * (0.5 + 0.5 * math.cos(phase * 2 * math.pi))
            self._dirty = True  # force re-tick for animation
        else:
            alpha = 1.0

        tw = fm.horizontalAdvance(text)
        x = (r.width() - tw) / 2
        y = r.height() / 2 + fm.ascent() / 2 - fm.descent() / 2

        path = QPainterPath()
        path.addText(x, y, font, text)
        painter.strokePath(path, QPen(QColor(0, 0, 0, int(200 * alpha)), 3.0,
                                       Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        c = color if color else QColor(255, 255, 255)
        fill = QColor(c)
        fill.setAlpha(int(220 * alpha))
        painter.fillPath(path, fill)

    def _paint_context_wrapped(self, painter, r, font, fm, space_w, text, center_y,
                                 is_past, highlight, edge_fade, offset, max_width, line_idx):
        """Draw a dim/past line with wrapping."""
        cache_key = (line_idx, self._cached_font_key, int(max_width), "ctx")
        rows = self._wrap_line(text, fm, space_w, max_width, cache_key)
        if not rows:
            return

        row_h = fm.height()
        total_h = row_h * len(rows)

        dist = abs(offset)
        if is_past:
            alpha = max(0.08, 0.25 - (dist - 1) * 0.06) * edge_fade
            color = QColor(highlight)
            color.setAlpha(int(255 * alpha))
            outline_alpha = int(100 * alpha / 0.25)
        else:
            alpha = max(0.06, 0.18 - (dist - 1) * 0.04) * edge_fade
            color = QColor(255, 255, 255, int(255 * alpha))
            outline_alpha = int(100 * alpha / 0.18)
        outline_color = QColor(0, 0, 0, min(255, outline_alpha))

        start_y = center_y - total_h / 2 + fm.ascent()

        for ri, row in enumerate(rows):
            total_w = sum(w for _, w in row) + space_w * max(0, len(row) - 1)
            x = (r.width() - total_w) / 2
            y = start_y + ri * row_h
            for word, ww in row:
                path = QPainterPath()
                path.addText(x, y, font, word)
                painter.strokePath(path, QPen(outline_color, 2.0,
                                               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.fillPath(path, color)
                x += ww + space_w

    def _paint_karaoke_wrapped(self, painter, r, f, fm, space_w, highlight,
                                 center_y, edge_fade, max_width, line_idx, text):
        """Active line with karaoke fill + wrapping."""
        cache_key = (line_idx, self._cached_font_key, int(max_width), "active")
        rows = self._wrap_line(text, fm, space_w, max_width, cache_key)
        if not rows:
            return

        row_h = fm.height()
        total_h = row_h * len(rows)
        start_y = center_y - total_h / 2 + fm.ascent()

        # Compute total width across all words, then fill proportion in pixels
        all_word_widths = [w for row in rows for _, w in row]
        n_words = len(all_word_widths)
        if n_words == 0:
            return
        total_char_w = sum(all_word_widths)
        fill_pixel = self._line_progress * total_char_w

        word_global_idx = 0
        cumulative = 0.0

        for ri, row in enumerate(rows):
            row_w = sum(w for _, w in row) + space_w * max(0, len(row) - 1)
            x = (r.width() - row_w) / 2
            y_baseline = start_y + ri * row_h
            y_center_row = y_baseline - fm.ascent() / 2 + fm.descent() / 2

            for word, word_w in row:
                word_local_start = cumulative
                word_local_end = cumulative + word_w

                if fill_pixel >= word_local_end:
                    word_fill = 1.0
                elif fill_pixel <= word_local_start:
                    word_fill = 0.0
                else:
                    word_fill = (fill_pixel - word_local_start) / word_w

                # Scale
                if word_fill <= 0:
                    scale = 0.88
                elif word_fill < 1.0:
                    t = ease_out_back(min(word_fill * 2, 1.0))
                    scale = 0.88 + 0.18 * t
                else:
                    scale = 1.0

                painter.save()
                word_cx = x + word_w / 2
                painter.translate(word_cx, y_center_row)
                painter.scale(scale, scale)
                painter.translate(-word_cx, -y_center_row)

                path = QPainterPath()
                path.addText(x, y_baseline, f, word)

                # Dark outline
                painter.strokePath(path, QPen(QColor(0, 0, 0, int(180 * edge_fade)), 3.0,
                                               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

                if word_fill <= 0:
                    painter.fillPath(path, QColor(255, 255, 255, int(55 * edge_fade)))
                elif word_fill >= 1.0:
                    glow = QColor(highlight)
                    glow.setAlpha(int(40 * edge_fade))
                    painter.strokePath(path, QPen(glow, 4, Qt.SolidLine,
                                                   Qt.RoundCap, Qt.RoundJoin))
                    fill = QColor(highlight)
                    fill.setAlpha(int(255 * edge_fade))
                    painter.fillPath(path, fill)
                else:
                    # Partial fill
                    painter.fillPath(path, QColor(255, 255, 255, int(55 * edge_fade)))
                    clip_x = x + word_w * word_fill
                    painter.save()
                    clip_rect = QRectF(x - 6, y_baseline - fm.ascent() - 4,
                                        clip_x - x + 6, fm.height() + 8)
                    painter.setClipRect(clip_rect)
                    glow = QColor(highlight)
                    glow.setAlpha(int(35 * edge_fade))
                    painter.strokePath(path, QPen(glow, 4, Qt.SolidLine,
                                                   Qt.RoundCap, Qt.RoundJoin))
                    fill = QColor(highlight)
                    fill.setAlpha(int(255 * edge_fade))
                    painter.fillPath(path, fill)
                    painter.restore()

                painter.restore()
                x += word_w + space_w
                cumulative += word_w
                word_global_idx += 1

            # Account for spaces between words in width, but karaoke fill skips them
            # (space doesn't need coloring)

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
