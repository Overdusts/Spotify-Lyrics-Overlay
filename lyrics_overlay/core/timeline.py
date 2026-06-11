"""Time -> lyric line/word mapping over a parsed :class:`LyricDoc`.

Pure module (zero Qt). All queries are driven by a playback position in
milliseconds (from :class:`lyrics_overlay.core.clock.PlaybackClock`) and are
cheap enough to call every frame: line bounds are precomputed at
construction and lookups bisect a sorted start array.

Conventions
-----------
* Line indices are indices into ``doc.lines``.
* A line's *bounds* run from its own stamp to the next stamped line's stamp
  (or ``start + 4000`` for the final stamped line).
* Word durations are exact when the document carries word-level timestamps;
  otherwise they are estimated as width-weighted shares of the line duration
  with a 120 ms-per-word floor, renormalized so they still sum to the line
  duration.
* An *interlude* is a gap > 4000 ms between consecutive stamped lines, plus
  the region before the first stamped line when it starts later than
  4000 ms. Unsynced documents never report interludes.
"""

from __future__ import annotations

import logging
from bisect import bisect_right

from lyrics_overlay.models import LyricDoc

log = logging.getLogger(__name__)

#: Synthetic duration (ms) granted to the final stamped line.
LINE_TAIL_MS = 4000

#: Gaps strictly longer than this (ms) count as interludes.
INTERLUDE_MIN_GAP_MS = 4000

#: Minimum estimated duration (ms) per word before renormalization.
WORD_FLOOR_MS = 120.0


class LyricTimeline:
    """Read-only time index over an immutable :class:`LyricDoc`."""

    __slots__ = ("_doc", "_starts", "_line_idx", "_bounds")

    def __init__(self, doc: LyricDoc) -> None:
        self._doc = doc
        # Stamped lines in time order (parsers already sort; sorting again is
        # cheap and keeps every query well-defined on adversarial input).
        stamped: list[tuple[int, int]] = sorted(
            (line.start_ms, i)
            for i, line in enumerate(doc.lines)
            if line.start_ms is not None
        )
        self._starts: list[int] = [start for start, _ in stamped]
        self._line_idx: list[int] = [i for _, i in stamped]
        # Precomputed (start, end) per doc-line index; None for unstamped.
        self._bounds: list[tuple[int, int] | None] = [None] * len(doc.lines)
        for k, (start, i) in enumerate(stamped):
            end = stamped[k + 1][0] if k + 1 < len(stamped) else start + LINE_TAIL_MS
            self._bounds[i] = (start, end)

    @property
    def doc(self) -> LyricDoc:
        return self._doc

    @property
    def synced(self) -> bool:
        return self._doc.synced

    def index_at(self, pos_ms: int) -> int:
        """Index of the line active at ``pos_ms``; -1 before the first stamp.

        Returns -1 for documents without any stamped lines.
        """
        k = bisect_right(self._starts, pos_ms) - 1
        if k < 0:
            return -1
        return self._line_idx[k]

    def line_bounds(self, idx: int) -> tuple[int, int] | None:
        """``(start_ms, end_ms)`` for line ``idx``; None if out of range or
        the line is unstamped. End is the next stamped line's start, or
        ``start + 4000`` for the final stamped line."""
        if 0 <= idx < len(self._bounds):
            return self._bounds[idx]
        return None

    def line_progress(self, idx: int, pos_ms: int) -> float:
        """Progress 0..1 of ``pos_ms`` through line ``idx``'s bounds."""
        bounds = self.line_bounds(idx)
        if bounds is None:
            return 0.0
        start, end = bounds
        span = end - start
        if span <= 0:
            # Degenerate (duplicate stamps): treat the line as instantaneous.
            return 1.0 if pos_ms >= start else 0.0
        return min(1.0, max(0.0, (pos_ms - start) / span))

    def word_durations_ms(self, idx: int, word_widths: list[float]) -> list[float]:
        """Per-word durations (ms) for line ``idx``.

        Exact path: when the line carries :class:`LyricWord` stamps, each
        duration is the delta to the next word's stamp (the last word runs to
        the line's end). ``word_widths`` is ignored and the result length is
        the stamped word count.

        Estimated path: width-weighted shares of the line duration with a
        120 ms-per-word floor, renormalized so the total equals the line
        duration exactly. Result length is ``len(word_widths)``.
        """
        bounds = self.line_bounds(idx)
        if bounds is None:
            return [0.0] * len(word_widths)
        start, end = bounds
        words = self._doc.lines[idx].words

        if words:  # exact path — trust the stamps
            n = len(words)
            if word_widths and len(word_widths) != n:
                log.debug(
                    "word_widths length %d != %d stamped words for line %d; using stamps",
                    len(word_widths), n, idx,
                )
            durations: list[float] = []
            for i, word in enumerate(words):
                word_end = words[i + 1].start_ms if i + 1 < n else end
                durations.append(float(max(0, word_end - word.start_ms)))
            return durations

        # Estimated path — width-weighted with floor, renormalized.
        n = len(word_widths)
        if n == 0:
            return []
        duration = float(end - start)
        if duration <= 0.0:
            return [0.0] * n
        total_width = sum(w for w in word_widths if w > 0.0)
        if total_width <= 0.0:
            raw = [duration / n] * n
        else:
            raw = [duration * max(w, 0.0) / total_width for w in word_widths]
        floored = [max(r, WORD_FLOOR_MS) for r in raw]
        scale = duration / sum(floored)
        return [d * scale for d in floored]

    def word_fills(self, idx: int, pos_ms: int, word_widths: list[float]) -> list[float]:
        """Per-word karaoke fill 0..1 at ``pos_ms``, via word durations.

        With word stamps, each word fills from its own stamp; otherwise
        estimated durations run back-to-back from the line start.
        """
        bounds = self.line_bounds(idx)
        if bounds is None:
            return [0.0] * len(word_widths)
        durations = self.word_durations_ms(idx, word_widths)
        words = self._doc.lines[idx].words
        if words:
            return [
                self._fill(pos_ms, float(word.start_ms), dur)
                for word, dur in zip(words, durations)
            ]
        fills: list[float] = []
        cursor = float(bounds[0])
        for dur in durations:
            fills.append(self._fill(pos_ms, cursor, dur))
            cursor += dur
        return fills

    @staticmethod
    def _fill(pos_ms: int, start_ms: float, duration_ms: float) -> float:
        if duration_ms <= 0.0:
            return 1.0 if pos_ms >= start_ms else 0.0
        return min(1.0, max(0.0, (pos_ms - start_ms) / duration_ms))

    def interlude(self, pos_ms: int) -> tuple[bool, float]:
        """``(active, progress)`` for instrumental gaps.

        Active during stamp-to-stamp gaps > 4000 ms and before the first
        stamped line when it starts later than 4000 ms; progress is 0..1
        through the gap. Unsynced documents always return ``(False, 0.0)``.
        """
        if not self._doc.synced or not self._starts:
            return (False, 0.0)
        first = self._starts[0]
        if pos_ms < first:
            if first > INTERLUDE_MIN_GAP_MS:
                return (True, min(1.0, max(0.0, pos_ms / first)))
            return (False, 0.0)
        k = bisect_right(self._starts, pos_ms) - 1  # >= 0: pos_ms >= first
        if k + 1 >= len(self._starts):
            return (False, 0.0)  # past the last stamp — outro, not interlude
        gap_start = self._starts[k]
        gap = self._starts[k + 1] - gap_start
        if gap > INTERLUDE_MIN_GAP_MS:
            return (True, min(1.0, max(0.0, (pos_ms - gap_start) / gap)))
        return (False, 0.0)
