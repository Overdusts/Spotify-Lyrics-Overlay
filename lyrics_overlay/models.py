"""Cross-module data model. Pure module — no Qt. All payloads frozen."""

from __future__ import annotations

from dataclasses import dataclass

# Sentinel fetch results (see lyrics/service.py): a track either resolves to a
# LyricDoc, is known-instrumental, or has no lyrics anywhere.
INSTRUMENTAL = "__INSTRUMENTAL__"
NOT_FOUND = None


@dataclass(frozen=True)
class TrackInfo:
    id: str
    name: str
    artist: str
    album: str
    duration_ms: int
    art_url_small: str | None = None
    art_url_large: str | None = None
    is_episode: bool = False


@dataclass(frozen=True)
class LyricWord:
    start_ms: int
    text: str


@dataclass(frozen=True)
class LyricLine:
    start_ms: int | None
    text: str
    words: tuple[LyricWord, ...] | None = None


@dataclass(frozen=True)
class LyricDoc:
    lines: tuple[LyricLine, ...]
    synced: bool


@dataclass(frozen=True)
class PlaybackAnchor:
    progress_ms: int
    mono_time: float
    speed: float
    playing: bool


@dataclass(frozen=True)
class Palette:
    accent: str
    glow: str
    contrast: str


DEFAULT_PALETTE = Palette(accent="#1DB954", glow="#3BE477", contrast="#ffffff")
