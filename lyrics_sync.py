from bisect import bisect_right


class LyricSyncEngine:
    def __init__(self):
        self._timestamps = []
        self._lines = []
        self._synced = False

    def set_lyrics(self, timed_lines):
        """Set lyrics. timed_lines: list of (ms_or_None, text)."""
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

    @property
    def is_synced(self):
        return self._synced

    @property
    def lines(self):
        return self._lines

    def get_current_index(self, position_ms):
        if not self._synced or not self._timestamps:
            return 0
        idx = bisect_right(self._timestamps, position_ms) - 1
        return max(0, idx)
