import time
from PyQt5.QtCore import QThread, pyqtSignal


class SpotifyPoller(QThread):
    track_changed = pyqtSignal(dict)
    position_updated = pyqtSignal(int)
    playback_stopped = pyqtSignal()
    playback_resumed = pyqtSignal()

    def __init__(self, sp_client, poll_interval_ms=1000):
        super().__init__()
        self.sp = sp_client
        self.poll_interval = poll_interval_ms / 1000.0
        self._running = True
        self._current_track_id = None
        self._anchor_progress = 0
        self._anchor_time = 0.0
        self._is_playing = False
        # Smooth drift correction: instead of jumping to the API position,
        # we nudge our playback speed slightly to converge over ~1 second.
        self._speed = 1.0  # effective playback speed multiplier

    def stop(self):
        self._running = False

    @property
    def is_playing(self):
        return self._is_playing

    def get_interpolated_position(self):
        if not self._is_playing:
            return self._anchor_progress
        elapsed = (time.monotonic() - self._anchor_time) * 1000 * self._speed
        return int(self._anchor_progress + elapsed)

    def run(self):
        while self._running:
            try:
                pb = self.sp.current_playback()
            except Exception:
                time.sleep(self.poll_interval)
                continue

            if pb is None or pb.get("item") is None:
                if self._is_playing:
                    self._is_playing = False
                    self.playback_stopped.emit()
                time.sleep(self.poll_interval)
                continue

            item = pb["item"]
            track_id = item.get("id") or item.get("uri")
            progress_ms = pb.get("progress_ms", 0)
            is_playing = pb.get("is_playing", False)

            # Track change — hard reset
            if track_id != self._current_track_id:
                self._current_track_id = track_id
                self._anchor_progress = progress_ms
                self._anchor_time = time.monotonic()
                self._is_playing = is_playing
                self._speed = 1.0
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                self.track_changed.emit({
                    "name": item.get("name", ""),
                    "artist": artists,
                    "album": item.get("album", {}).get("name", ""),
                    "duration_ms": item.get("duration_ms", 0),
                })
                time.sleep(self.poll_interval)
                continue

            # Compare our interpolated position with what Spotify reports
            interpolated = self.get_interpolated_position()
            drift = progress_ms - interpolated  # positive = we're behind

            if abs(drift) > 1500:
                # Large drift = user seeked or buffering — hard re-anchor
                self._anchor_progress = progress_ms
                self._anchor_time = time.monotonic()
                self._speed = 1.0
            else:
                # Small drift — smooth correction over next poll interval.
                # Adjust speed so we converge to the correct position.
                # If we're 200ms behind, speed up slightly; if ahead, slow down.
                correction_window = self.poll_interval * 1000  # ms until next poll
                if correction_window > 0 and is_playing:
                    # Target: cover (correction_window + drift) in correction_window of real time
                    self._speed = max(0.8, min(1.2, (correction_window + drift) / correction_window))
                # Re-anchor with current values (keeps interpolation fresh)
                self._anchor_progress = progress_ms
                self._anchor_time = time.monotonic()

            was_playing = self._is_playing
            self._is_playing = is_playing

            if not is_playing and was_playing:
                self._speed = 1.0
                self.playback_stopped.emit()
            elif is_playing and not was_playing:
                self.playback_resumed.emit()

            time.sleep(self.poll_interval)
