import time
from PyQt5.QtCore import QThread, pyqtSignal


class SpotifyPoller(QThread):
    track_changed = pyqtSignal(dict)
    position_updated = pyqtSignal(int)
    playback_stopped = pyqtSignal()

    def __init__(self, sp_client, poll_interval_ms=3000):
        super().__init__()
        self.sp = sp_client
        self.poll_interval = poll_interval_ms / 1000.0
        self._running = True
        self._current_track_id = None
        self._anchor_progress = 0
        self._anchor_time = 0.0
        self._is_playing = False

    def stop(self):
        self._running = False

    def get_interpolated_position(self):
        if not self._is_playing:
            return self._anchor_progress
        elapsed = (time.monotonic() - self._anchor_time) * 1000
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

            # Track change
            if track_id != self._current_track_id:
                self._current_track_id = track_id
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                self.track_changed.emit({
                    "name": item.get("name", ""),
                    "artist": artists,
                    "album": item.get("album", {}).get("name", ""),
                    "duration_ms": item.get("duration_ms", 0),
                })

            # Seek detection
            interpolated = self.get_interpolated_position()
            if abs(progress_ms - interpolated) > 3000:
                pass  # re-anchor below

            # Anchor
            self._anchor_progress = progress_ms
            self._anchor_time = time.monotonic()
            self._is_playing = is_playing

            if not is_playing:
                self.playback_stopped.emit()

            time.sleep(self.poll_interval)
