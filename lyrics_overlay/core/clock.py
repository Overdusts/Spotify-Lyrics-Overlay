"""Playback position clock — lock-free anchor extrapolation.

The poller thread (writer) swaps a single frozen :class:`PlaybackAnchor`
reference; the render thread (reader) grabs that one reference and
extrapolates from it. CPython attribute assignment is atomic, so no lock is
needed and a reader can never observe a torn anchor: it either sees the old
complete anchor or the new complete anchor.

Position is a *pull*, not a push — the render tick calls
:meth:`PlaybackClock.position_ms` at render rate, so lyric time advances
smoothly between 1 s poll ticks.
"""

from __future__ import annotations

import logging
import time

from lyrics_overlay.models import PlaybackAnchor

log = logging.getLogger(__name__)


class PlaybackClock:
    """Monotonic-time playback position estimator.

    Writers call :meth:`set_anchor` whenever fresh truth arrives (poll tick,
    seek, pause/resume, drift-correction speed nudge). Readers call
    :meth:`position_ms` whenever they need the current position.
    """

    __slots__ = ("_anchor",)

    def __init__(self) -> None:
        # Start paused at zero: position_ms() is well-defined before the
        # first real anchor arrives.
        self._anchor: PlaybackAnchor = PlaybackAnchor(
            progress_ms=0,
            mono_time=time.monotonic(),
            speed=1.0,
            playing=False,
        )

    def set_anchor(
        self,
        progress_ms: int,
        speed: float = 1.0,
        playing: bool = True,
        mono_time: float | None = None,
    ) -> None:
        """Swap in a new anchor (single atomic reference assignment).

        ``mono_time`` defaults to ``time.monotonic()`` *now*; pass an explicit
        value when anchoring against a timestamp captured earlier (e.g. taken
        right before a blocking API call) or in tests.
        """
        if mono_time is None:
            mono_time = time.monotonic()
        self._anchor = PlaybackAnchor(
            progress_ms=int(progress_ms),
            mono_time=float(mono_time),
            speed=float(speed),
            playing=bool(playing),
        )

    def anchor(self) -> PlaybackAnchor:
        """Return the current frozen anchor snapshot."""
        return self._anchor

    def position_ms(self) -> int:
        """Estimated playback position in milliseconds.

        Playing: ``anchor + (monotonic_now - anchor.mono_time) * 1000 * speed``.
        Paused: frozen at the anchor's progress.
        """
        anchor = self._anchor  # single read — everything below uses this snapshot
        if not anchor.playing:
            return anchor.progress_ms
        elapsed = time.monotonic() - anchor.mono_time
        return int(anchor.progress_ms + elapsed * 1000.0 * anchor.speed)

    @property
    def playing(self) -> bool:
        return self._anchor.playing
