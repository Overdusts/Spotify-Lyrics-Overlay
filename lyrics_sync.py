from bisect import bisect_right


class LyricSyncEngine:
    def __init__(self):
        self._timestamps = []
        self._lines = []
        self._synced = False
        self._instrumental = False

    def set_lyrics(self, timed_lines):
        """Set lyrics. timed_lines: list of (ms_or_None, text) or empty list."""
        self._instrumental = False
        if not timed_lines:
            self._timestamps = []
            self._lines = []
            self._synced = False
            return

        self._synced = timed_lines[0][0] is not None
        if self._synced:
            self._timestamps = [t[0] for t in timed_lines]
            self._lines = [t[1] for t in timed_lines]
        else:
            self._timestamps = []
            self._lines = [t[1] for t in timed_lines]

    def set_instrumental(self):
        self._instrumental = True
        self._timestamps = []
        self._lines = []
        self._synced = False

    def clear(self):
        self._timestamps = []
        self._lines = []
        self._synced = False
        self._instrumental = False

    @property
    def is_synced(self):
        return self._synced

    @property
    def is_instrumental(self):
        return self._instrumental

    @property
    def lines(self):
        return self._lines

    @property
    def timestamps(self):
        return self._timestamps

    def line_bounds(self, idx):
        """Return (start_ms, end_ms) for a line, or None if out of bounds."""
        if idx < 0 or idx >= len(self._timestamps):
            return None
        start = self._timestamps[idx]
        end = self._timestamps[idx + 1] if idx + 1 < len(self._timestamps) else start + 4000
        return start, end

    def get_current_index(self, position_ms):
        if not self._synced or not self._timestamps:
            return 0
        idx = bisect_right(self._timestamps, position_ms) - 1
        return max(0, idx)
