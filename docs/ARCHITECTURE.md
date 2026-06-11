# Lyric Overlay 2.0 — BINDING INTEGRATION CONTRACT

This document pins every cross-module interface. **docs/SPEC.md** is authoritative for
*behavior, visuals, and motion numbers*; **this file wins for interfaces** (names,
signatures, signals, config keys). Implementation agents code against this contract —
other packages are being written concurrently, so never assume another package's file
exists yet; import it per this contract and do not execute cross-package imports.

## Ground rules (all modules)

- Qt binding: **PySide6 6.11** — `from PySide6.QtCore import Qt, QObject, Signal, Slot`,
  scoped enums (`Qt.WindowType.FramelessWindowHint`), `exec()` not `exec_()`.
- `lyrics_overlay/core/*` and `config/paths/models`: **zero Qt imports** (pure, unit-testable).
- Full type hints. `logging.getLogger(__name__)`, never `print`.
- No module-level Qt object construction. No `setWindowFlags`/`setWindowOpacity` after
  `show()` anywhere except the creation block in `ui/overlay.py`.
- Every `win/*` function guards `sys.platform == "win32"` and no-ops elsewhere.
- Frozen dataclasses for all cross-thread signal payloads.
- File encoding utf-8; LF or CRLF both fine.

## Package layout & ownership

```
main.py  LyricOverlay.pyw                                  [integrator]
lyrics_overlay/__init__.py  paths.py  models.py            [integrator — ALREADY WRITTEN, do not modify]
lyrics_overlay/config.py  logsetup.py                      [agent A: foundation]
lyrics_overlay/core/{clock,springs,timeline}.py            [agent B: core-motion]
lyrics_overlay/core/{lrcparse,lyricsfile,wrap,palette}.py  [agent C: core-parse]
lyrics_overlay/lyrics/{lrclib,cache,service}.py            [agent D: lyrics]
lyrics_overlay/sources/{base,spotify_auth,spotify_source,demo_source}.py
assets/demo_track.json                                     [agent E: sources]
lyrics_overlay/ui/{overlay,render_loop,scene,line_cache,painters}.py  [agent F: render]
lyrics_overlay/ui/{tray,settings_dialog,onboarding,monitor_map}.py    [agent G: shell]
lyrics_overlay/win/{clickthrough,hotkeys,fullscreen,topmost,startup,instance,dwm}.py  [agent H: win]
lyrics_overlay/app.py                                      [integrator]
tests/test_*.py                                            [each agent, for its own modules]
```

Each subpackage needs an empty (or docstring-only) `__init__.py` — created by the
agent that owns the package's first listed module.

## models.py (written — reproduced for reference)

```python
INSTRUMENTAL = "__INSTRUMENTAL__"        # sentinel; compare with `is` or `==`
NOT_FOUND = None                          # alias for readability

@dataclass(frozen=True)
class TrackInfo:
    id: str                # spotify id/uri or "demo"
    name: str
    artist: str            # display string, comma-joined
    album: str
    duration_ms: int
    art_url_small: str | None = None     # ~300px
    art_url_large: str | None = None     # ~640px
    is_episode: bool = False

@dataclass(frozen=True)
class LyricWord:
    start_ms: int
    text: str              # carries its own spacing when source provides it

@dataclass(frozen=True)
class LyricLine:
    start_ms: int | None   # None => unsynced
    text: str
    words: tuple[LyricWord, ...] | None = None

@dataclass(frozen=True)
class LyricDoc:
    lines: tuple[LyricLine, ...]
    synced: bool

@dataclass(frozen=True)
class PlaybackAnchor:
    progress_ms: int
    mono_time: float       # time.monotonic() at anchor
    speed: float           # 0.8..1.2 drift-correction multiplier
    playing: bool

@dataclass(frozen=True)
class Palette:
    accent: str            # "#rrggbb"
    glow: str              # "#rrggbb"
    contrast: str          # "#ffffff" or "#101010" — readable on accent
DEFAULT_PALETTE = Palette(accent="#1DB954", glow="#3BE477", contrast="#ffffff")
```

## paths.py (written — reference)

```python
CONFIG_DIR: Path          # %APPDATA%/SpotifyLyricsOverlay (fallback ~/.config/spotify-lyrics-overlay)
SETTINGS_PATH: Path       # CONFIG_DIR/settings.json
TOKEN_PATH: Path          # CONFIG_DIR/spotify_token.json
LYRICS_CACHE_DIR: Path    # CONFIG_DIR/lyrics_cache_v2
ART_CACHE_DIR: Path       # CONFIG_DIR/art_cache
LOG_DIR: Path             # CONFIG_DIR/logs
V1_TOKEN_PATH: Path       # CONFIG_DIR/.spotify_cache (legacy, deleted on migration)
def ensure_dirs() -> None # mkdir -p all of the above; called by app.run()
```

## Agent A — config.py, logsetup.py

```python
# config.py
DEFAULTS: dict = {
  "schema_version": 2,
  # spotify
  "spotify_client_id": "",
  "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
  "poll_interval_ms": 1000,            # clamp 1000..5000
  # appearance
  "style_preset": "panel",             # minimal|panel|cinema
  "font_family": "Segoe UI Variable Display",   # fallback handled at font resolve
  "font_size": 28,                     # px, 16..48
  "alignment": "left",                 # left|center
  "fill_mode": "white",                # white|accent|classic
  "word_motion": "subtle",             # subtle|bounce|off
  "accent_auto": True,
  "highlight_color": "#1DB954",        # manual accent when accent_auto false
  "bg_opacity": 0.35,                  # 0..1
  "legibility_mode": "shadow",         # shadow|outline|scrim
  "lines_visible": 5,                  # 3..7
  "width_percent": 56,                 # 30..90
  "max_line_width_percent": 92,        # 50..100
  "animation_budget": "full",          # full|reduced|minimal
  "show_dots": True,
  "show_track_info": True,             # toast on/off
  # position
  "position_preset": "top-center",     # top-center|bottom-center|custom
  "positions": {},                     # per QScreen.name(): {"preset": str, "x": int, "y": int}
  "monitor": "",                       # QScreen.name() or "" = primary
  "snap_enabled": True,
  "locked": True,
  # behavior
  "click_through": True,
  "fullscreen_hide": True,
  "show_over_games": False,
  "launch_at_startup": False,
  "fps_cap": 60,                       # 30|60|0 (0 = display rate)
  # sync
  "sync_offset_ms": 0,                 # positive = lyrics earlier; ±5000
  # hotkeys: empty string disables an action
  "hotkeys": {
    "toggle_visible": "Ctrl+Alt+F9",
    "toggle_clickthrough": "Ctrl+Alt+F10",
    "offset_minus": "Ctrl+Alt+Left",
    "offset_plus": "Ctrl+Alt+Right",
    "offset_reset": "Ctrl+Alt+0",
  },
}
def load_config() -> dict     # reads SETTINGS_PATH; merges over DEFAULTS (deep for "hotkeys");
                              # if schema_version < 2 -> migrate_v1(raw) first; clamps ranges; saves if migrated
def save_config(cfg: dict) -> None   # atomic: write tmp + os.replace
def migrate_v1(old: dict) -> dict
#   keep: spotify_client_id, spotify_redirect_uri, sync_offset_ms, click_through,
#         show_track_info, bg_opacity, highlight_color (and set accent_auto=False ONLY if
#         old highlight_color differs from "#1DB954"), width_percent (clamp 30..90),
#         lines_visible (clamp 3..7), poll_interval_ms (clamp >=1000)
#   drop: spotify_client_secret, font_size (v1 was pt, v2 is px), font_family (take default),
#         position_x/y (presets are better; default top-center), text_color, opacity, etc.
#   side effect handled by app.py, NOT here: deleting V1_TOKEN_PATH + one-time re-auth dialog
#   (config.py stays pure: no file deletion inside migrate_v1; it only maps dicts)

# logsetup.py
def guard_std_streams() -> None      # if sys.stdout/stderr is None (pythonw) replace with
                                     # open(os.devnull,"w") BEFORE any logging import use
def setup_logging(level: str = "INFO") -> None
                                     # RotatingFileHandler LOG_DIR/lyricoverlay.log 1MB x3;
                                     # StreamHandler only if sys.stderr is a real tty stream
```
Tests: `tests/test_config_migration.py` (v1 dict in → v2 out, clamps, secret dropped,
accent_auto logic, hotkeys deep-merge, atomic save via tmp_path).

## Agent B — core/clock.py, core/springs.py, core/timeline.py

```python
# clock.py
class PlaybackClock:
    def set_anchor(self, progress_ms: int, speed: float = 1.0, playing: bool = True,
                   mono_time: float | None = None) -> None    # swaps ONE frozen PlaybackAnchor ref
    def anchor(self) -> PlaybackAnchor
    def position_ms(self) -> int      # playing: anchor + (mono-now - mono_time)*1000*speed; else anchor
    @property
    def playing(self) -> bool

# springs.py  — closed-form damped harmonic oscillator (AMLL-style), NOT euler integration
class Spring:
    def __init__(self, mass: float, damping: float, stiffness: float, value: float = 0.0)
    def set_params(self, mass: float, damping: float, stiffness: float) -> None
    def set_target(self, target: float) -> None
    def snap(self, value: float) -> None          # value=target=value, velocity=0
    def update(self, dt: float) -> float          # dt seconds (clamp internally to <=0.05); returns value
    @property
    def value(self) -> float
    @property
    def target(self) -> float
    @property
    def settled(self) -> bool                     # |value-target|<0.01 and |velocity|<0.01 (then snapped)

# timeline.py
class LyricTimeline:
    def __init__(self, doc: LyricDoc)
    @property
    def doc(self) -> LyricDoc
    @property
    def synced(self) -> bool
    def index_at(self, pos_ms: int) -> int                      # bisect; -1 before first stamped line
    def line_bounds(self, idx: int) -> tuple[int, int] | None   # end = next start_ms or start+4000
    def line_progress(self, idx: int, pos_ms: int) -> float     # 0..1 within bounds
    def word_durations_ms(self, idx: int, word_widths: list[float]) -> list[float]
        # exact when doc has word times; else width-weighted share of line duration with
        # 120ms-per-word floor, renormalized to line duration
    def word_fills(self, idx: int, pos_ms: int, word_widths: list[float]) -> list[float]
        # per-word 0..1 using word_durations_ms
    def interlude(self, pos_ms: int) -> tuple[bool, float]
        # True during gaps > 4000ms between stamped lines AND before first line (if first
        # line starts > 4000ms); progress 0..1 through the gap. Synced docs only; else (False, 0.0)
```
Tests for all three (pure pytest, no Qt).

## Agent C — core/lrcparse.py, core/lyricsfile.py, core/wrap.py, core/palette.py

```python
# lrcparse.py
def parse_lrc(text: str) -> LyricDoc | None
#   line tags [m:ss], [mm:ss.xx], [mm:ss.xxx], [mm:ss:xx]; stacked tags ([a][b]text);
#   [offset:±ms] global tag (positive shifts stamps EARLIER: stamp - offset… follow LRC spec:
#   offset:+500 means lyrics display 500ms earlier => subtract); A2 word tags <mm:ss.xx>word;
#   sort by start; drop unparseable lines; None if zero stamped lines
def parse_plain(text: str) -> LyricDoc | None    # unsynced doc, one LyricLine(start_ms=None) per
                                                 # non-empty line; None if no content

# lyricsfile.py
def parse_lyricsfile(text: str) -> LyricDoc | None   # LRCLIB "lyricsfile" YAML v1.0 (word-level);
                                                     # yaml.safe_load; ENTIRE body in try/except -> None

# wrap.py
def wrap_words(words: list[str], measure: Callable[[str], float],
               space_w: float, max_width: float) -> list[list[int]]
#   greedy; returns rows of indices into `words`; single overlong word gets its own row

# palette.py
def extract_palette(pixels: list[tuple[int, int, int]]) -> Palette
#   k-means k=5, 12 iters in OKLab; score = chroma * sqrt(pop) * weight(L) peaked in L 0.40..0.75;
#   clamp OKLCh L to 0.74..0.88 and C <= 0.17; raise L until WCAG contrast vs #000 >= 4.5;
#   glow = accent with L+0.06; contrast = white or near-black by accent luminance. Pure ints/floats.
def lerp_palette(a: Palette, b: Palette, t: float) -> Palette   # OKLab interpolation per field
```
Tests for all four (palette: synthetic single/dual-color images; lrcparse: every tag form,
offset sign, A2 words; wrap: injected dict measure).

## Agent D — lyrics/lrclib.py, lyrics/cache.py, lyrics/service.py

```python
# lrclib.py
class LyricsNetworkError(Exception): ...
class LrclibClient:
    BASE = "https://lrclib.net"
    def __init__(self, session: requests.Session | None = None)   # sets User-Agent from lyrics_overlay.USER_AGENT
    def fetch_payload(self, name: str, artist: str, album: str, duration_s: int) -> dict | None
#   chain: GET /api/get (track_name, artist_name, album_name, duration) ->
#          GET /api/get without album -> GET /api/search?track_name&artist_name ->
#          GET /api/search?q=track name only; search results filtered by the v1 word-boundary
#          artist matcher (port _artist_match verbatim from v1 lyrics_fetcher.py);
#   returns the raw LRCLIB record dict, or None when confidently NOT FOUND
#   (404 {"name":"TrackNotFound"} / no artist-validated search hit);
#   raises LyricsNetworkError on timeouts/conn errors/5xx after 2 retries (backoff 0.5,1.0); timeout 10s

# cache.py
class LyricsCache:
    def __init__(self, cache_dir: Path)
    @staticmethod
    def key_for(name: str, artist: str, album: str, duration_s: int) -> str   # sha1("n|a|al|d").hexdigest()[:16]
    def get(self, key: str) -> dict | None       # entry or None; not_found/instrumental expire after 7 days
    def put(self, key: str, entry: dict) -> None # atomic write
    def invalidate(self, key: str) -> None
    def size_bytes(self) -> int
    def clear(self) -> None
# entry := {"status": "found"|"not_found"|"instrumental", "payload": dict|None, "ts": float}

# service.py
def parse_payload(payload: dict) -> LyricDoc | str | None
#   order: payload.get("instrumental") truthy -> INSTRUMENTAL;
#   payload["lyricsfile"] -> core.lyricsfile.parse_lyricsfile;
#   payload["syncedLyrics"] -> core.lrcparse.parse_lrc;
#   payload["plainLyrics"] -> core.lrcparse.parse_plain;
#   all empty -> INSTRUMENTAL; unparseable -> None
class LyricsService(QObject):
    lyrics_ready = Signal(str, object)      # (track_id, LyricDoc | INSTRUMENTAL | None)
    def __init__(self, client: LrclibClient | None = None,
                 cache: LyricsCache | None = None, parent: QObject | None = None)
    def request(self, track: TrackInfo) -> None    # QThreadPool (private pool, maxThreadCount=2);
                                                   # monotonic generation token: only newest emits;
                                                   # LyricsNetworkError -> emit None but DO NOT negative-cache
    def resync(self, track: TrackInfo) -> None     # invalidate cache entry then request()
    def shutdown(self, timeout_ms: int = 2000) -> None
```
Tests: cache TTL/atomicity; lrclib chain with a stub Session; parse_payload precedence.

## Agent E — sources/*, assets/demo_track.json

```python
# base.py — documentation Protocol (typing.Protocol) for the source contract:
#   signals: track_changed(object=TrackInfo), playback_state(bool),
#            connection_state(str, str)  # (kind, msg); kind in
#            {"OK","CONNECTING","RATE_LIMITED","AUTH_REQUIRED","AD","EPISODE","IDLE"}
#   methods: start() -> None; stop() -> None (blocking-join ok); position_ms() -> int
#   property: is_playing -> bool

# spotify_auth.py
class AuthRequired(Exception): ...
class AuthFailed(Exception):
    def __init__(self, user_message: str, *a): ...
def build_client(client_id: str, redirect_uri: str, open_browser: bool = True) -> spotipy.Spotify
#   SpotifyPKCE(client_id=, redirect_uri=, scope="user-read-playback-state user-read-currently-playing",
#   cache_handler=CacheFileHandler(cache_path=str(TOKEN_PATH)), open_browser=);
#   corrupt token-cache JSON -> delete file, retry once; map auth errors to AuthFailed(user_message)
#   with the SPEC §7 error mapping (INVALID_CLIENT redirect text, 403 users-and-access, Premium note)
def has_token_cache() -> bool
def delete_token_cache() -> None

# spotify_source.py
class SpotifyPoller(QThread):     # signals per base.py contract
    def __init__(self, sp: spotipy.Spotify, clock: PlaybackClock, poll_interval_ms: int = 1000)
    def set_poll_interval(self, ms: int) -> None       # clamp >= 1000
    def position_ms(self) -> int                       # delegates to clock
    is_playing: property                               # from clock.anchor().playing
    def stop(self) -> None                             # flag; run() sleeps in 250ms slices
#   run(): current_playback(additional_types="episode"); v1 drift math VERBATIM (SPEC §2.8);
#   failure matrix SPEC §5; emits track_changed once per new item id with art urls from
#   item.album.images (pick ~300 and ~640); episode items -> TrackInfo(is_episode=True)

# demo_source.py
class DemoSource(QObject):        # same contract; QTimer(33ms) on main thread; loops 60s track
    def __init__(self, clock: PlaybackClock | None = None)
    ... signals/methods per base.py
def load_demo_track() -> tuple[TrackInfo, LyricDoc]    # from assets/demo_track.json
def demo_art_image():             # -> QImage 640x640 programmatic gradient (two-stop diagonal,
                                  # musical note glyph), import QtGui lazily inside the function
```
`assets/demo_track.json`: ORIGINAL lyrics written by you (no copyrighted text!), 60s loop,
line+word timings, and the SPEC §8 required content: ≥6s instrumental gap, a <400ms
inter-line burst, one ≥1.2s held word, one long wrapping line, scripted pause at t=20s
(3s) and seek at t=45s. Schema:
`{"title","artist","album","duration_ms","lines":[{"start_ms","text","words":[{"start_ms","text"}]}],
"events":[{"at_ms":20000,"type":"pause","duration_ms":3000},{"at_ms":45000,"type":"seek","to_ms":52000}]}`
DemoSource emits track_changed + playback_state and serves lyrics via `load_demo_track()`
(app.py feeds them through the normal `lyrics_ready` path — DemoSource itself does NOT
touch LyricsService). Tests: demo json loads, event scripting advances clock correctly.

## Agent F — ui/overlay.py, render_loop.py, scene.py, line_cache.py, painters.py  (RENDER STACK)

This is the visual heart — implement SPEC §3 exactly (panel, typography, springs table,
cascade, opacity/blur tiers, karaoke feathered fill + glow, dots, toast, states, pill).

```python
# scene.py
SHADOW_MARGIN = 40   # px, window = panel + this margin on all sides
class LyricScene:     # plain object (no QWidget); ALL Qt painting via QPainter passed in
    def __init__(self, cfg: dict, palette: Palette = DEFAULT_PALETTE)
    # inputs (called on main thread):
    def begin_track(self, track: TrackInfo) -> None        # LOADING + toast choreography
    def set_lyrics(self, result: object) -> None           # LyricDoc | INSTRUMENTAL | None
    def set_playing(self, playing: bool) -> None
    def set_connection(self, kind: str, msg: str) -> None  # kinds per sources/base.py
    def set_palette(self, palette: Palette) -> None        # 600ms OKLab crossfade (uses core.palette.lerp_palette)
    def set_art(self, image) -> None                       # QImage | None (toast + cinema)
    def show_pill(self, text: str) -> None
    def set_visible_hint(self, visible: bool) -> None
    def apply_config(self, cfg: dict) -> None              # diff keys, invalidate only affected caches
    # frame:
    def advance(self, dt: float, pos_ms: int) -> bool      # update springs/timelines; True = still animating
    def paint(self, painter, rect) -> None                 # rect = full window QRectF incl. margins
    def desired_size(self, screen_geometry) -> "QSize"     # panel+margins from cfg (width %, lines, font)

# render_loop.py
class RenderLoop(QObject):
    def __init__(self, widget, scene: LyricScene, position_ms: Callable[[], int], fps_cap: int = 60)
    def kick(self) -> None            # schedule next frame if not already running
    def set_fps_cap(self, cap: int) -> None   # 30|60|0=display rate
    def stop(self) -> None
#   QEvent.UpdateRequest chain w/ QElapsedTimer dt; fully stops when scene.advance() returns False;
#   anything that changes scene state must call kick()

# overlay.py
class OverlayWindow(QWidget):
    def __init__(self, cfg: dict, position_ms: Callable[[], int])
        # creates LyricScene + RenderLoop internally; exposes:
    scene: LyricScene
    def kick(self) -> None
    # slots (wired by app.py):
    def on_track_changed(self, track) -> None
    def on_lyrics_ready(self, track_id: str, result: object) -> None
    def on_playback_state(self, playing: bool) -> None
    def on_connection_state(self, kind: str, msg: str) -> None
    def on_art_ready(self, track_id: str, image) -> None
    def on_palette_ready(self, track_id: str, palette) -> None
    def show_pill(self, text: str) -> None
    def toggle_visible(self) -> None
    def set_click_through(self, enabled: bool) -> None     # delegates win.clickthrough; updates cfg["click_through"]
    def set_locked(self, locked: bool) -> None             # unlocked: dashed border + drag pill, drag+snap enabled
    def apply_config(self, cfg: dict) -> None              # geometry, scene, fps cap, click-through assert
    def move_to_screen(self, screen_name: str) -> None
    current_track_id: str | None                            # guard property for staleness checks
```
Window flags at creation ONLY: Frameless|StaysOnTop|Tool|DoesNotAcceptFocus +
WA_TranslucentBackground + WA_ShowWithoutActivating. Geometry per cfg positions/preset,
per-monitor (QScreen.name()), `screenChanged` → invalidate line_cache DPR strips +
win.clickthrough.assert_styles. Drag (unlocked): snap to h-center and 24px edges, Alt
suppresses snap; on release write cfg["positions"][screen] and `config.save_config`.
line_cache.py + painters.py internals are yours (per SPEC §3.4–3.5: ARGB32_Premultiplied
strips at DPR, blur tiers 0/1.5/3 box-blur ×3, feathered gradient karaoke mask via
CompositionMode_DestinationIn, glow pass, legibility modes shadow|outline|scrim).
Animation budget modes + auto-drop (frame p95 > 12ms over 5s → drop one tier, log it).
Test: `tests/test_scene_states.py` with pytest-qt offscreen (QT_QPA_PLATFORM=offscreen):
drive LyricScene through IDLE→LOADING→LYRICS→PAUSED→INSTRUMENTAL→NO_LYRICS with a fake
clock; assert state transitions + advance() settling (no paint-pixel assertions needed).

## Agent G — ui/tray.py, settings_dialog.py, onboarding.py, monitor_map.py

```python
# tray.py
class TrayIcon(QSystemTrayIcon):
    show_hide = Signal(); toggle_clickthrough = Signal(); lock_toggled = Signal(bool)
    move_to_monitor = Signal(str)              # QScreen.name()
    resync = Signal(); open_settings = Signal(); quit_app = Signal(); run_demo = Signal()
    def __init__(self, cfg: dict, parent: QObject | None = None)
    def set_track(self, title: str, artist: str) -> None    # tooltip "Track — Artist"
    def set_palette(self, palette) -> None                  # re-tint runtime-painted note icon
    def show_balloon(self, title: str, msg: str) -> None
#   menu per SPEC: Show/Hide (hotkey label), Lock/Unlock position, Move to monitor ▸,
#   Re-sync lyrics, Demo mode, Settings, Quit; double-click toggles visibility

# settings_dialog.py
class SettingsDialog(QDialog):
    config_changed = Signal(dict)        # live-apply, debounced 150ms
    reconnect_requested = Signal(); disconnect_requested = Signal()
    run_wizard_requested = Signal(); demo_requested = Signal()
    resync_requested = Signal(); clear_cache_requested = Signal(); open_logs_requested = Signal()
    def __init__(self, cfg: dict, hotkey_statuses: dict[str, tuple[bool, int]] | None = None,
                 cache_size_bytes: int = 0, parent=None)
    def set_hotkey_statuses(self, statuses: dict[str, tuple[bool, int]]) -> None
#   OPAQUE framed window 720x560; call win.dwm.style_dialog(hwnd) after show; pages and the
#   132px live preview strip per SPEC §4. Preview embeds the REAL LyricScene
#   (from lyrics_overlay.ui.scene) + RenderLoop on demo data via
#   sources.demo_source.load_demo_track(); preview-local PlaybackClock loops the track.
#   Cancel restores the entry snapshot (deep copy) by emitting config_changed(snapshot) + reject().
#   OK persists via config.save_config and accept(). Key-capture widgets for the 5 hotkey rows.

# onboarding.py
class OnboardingWizard(QWizard):
    def __init__(self, cfg: dict,
                 authorize: Callable[[str, Callable[[bool, str], None]], None], parent=None)
    choice: str   # after exec(): "demo" | "connected" | "cancelled"
#   4 pages per SPEC §2.20; authorize(client_id, done_cb) is injected by app.py (runs auth
#   in a thread, calls done_cb(ok, err_user_message) on the main thread). Page 4 embeds
#   MonitorMapWidget + preset cards. Re-runnable. Dark-style via win.dwm.style_dialog.

# monitor_map.py
class MonitorMapWidget(QWidget):
    position_chosen = Signal(str, str, int, int)   # (screen_name, preset, x, y); x/y only for "custom"
    def __init__(self, cfg: dict, parent=None)
    def refresh(self) -> None                      # re-read QGuiApplication.screens()
```

## Agent H — win/* (7 modules)

Implement SPEC §6 exactly. Pinned signatures:

```python
# clickthrough.py
def set_click_through(hwnd: int, enabled: bool) -> None
def apply_overlay_exstyles(hwnd: int) -> None          # WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW (always)
def assert_styles(hwnd: int, click_through: bool) -> None   # compare & re-apply (watchdog body)
# SetWindowLongPtrW/GetWindowLongPtrW with 64-bit-correct argtypes/restype; after changes:
# SetWindowPos(hwnd,0,0,0,0,0, NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED). Never SetLayeredWindowAttributes.

# hotkeys.py — MAIN-THREAD manager, no QThread
ACTIONS = ("toggle_visible","toggle_clickthrough","offset_minus","offset_plus","offset_reset")
class HotkeyManager(QObject):                  # also QAbstractNativeEventFilter subclass or owns one
    toggle_visible = Signal(); toggle_clickthrough = Signal(); offset_delta = Signal(int)  # -100/+100/0=reset
    def __init__(self, parent: QObject | None = None)   # installs native filter on qApp
    def register_from_config(self, hotkeys_cfg: dict[str, str]) -> dict[str, tuple[bool, int]]
        # parses "Ctrl+Alt+F9" style strings -> (MOD_*, VK); RegisterHotKey(None, id, mods|MOD_NOREPEAT, vk);
        # returns {action: (ok, GetLastError-if-failed)}; "" -> skipped (ok=True)
    def unregister_all(self) -> None
    statuses: dict[str, tuple[bool, int]]
    @staticmethod
    def is_forbidden(seq: str) -> str | None   # returns reason for F12/Win/F23/bare Ctrl+Shift etc., else None

# fullscreen.py
class FullscreenWatcher(QObject):
    fullscreen_changed = Signal(bool)
    def __init__(self, overlay_widget, parent=None)    # 1.5s QTimer; SPEC §6 detection (QUNS + rect cover)
    def start(self) -> None;  def stop(self) -> None

# topmost.py
class TopmostReasserter(QObject):
    def __init__(self, widget, parent=None)            # 1.5s SetWindowPos HWND_TOPMOST ... NOACTIVATE
    def start(self) -> None;  def stop(self) -> None

# startup.py
APP_RUN_VALUE = "LyricOverlay"
def set_launch_at_startup(enabled: bool) -> None   # HKCU Run; pythonw.exe (sys.executable dir) + abs LyricOverlay.pyw
def is_launch_at_startup() -> bool

# instance.py
def acquire_single_instance(on_activate: Callable[[], None]) -> bool
#   CreateMutexW "Local\\LyricOverlay_SingleInstance"; if ERROR_ALREADY_EXISTS: QLocalSocket
#   connect "LyricOverlay", send b"show", return False (caller exits 0).
#   Else QLocalServer.removeServer + listen("LyricOverlay"); newConnection w/ b"show" -> on_activate(); True.

# dwm.py
def style_dialog(hwnd: int) -> None   # best-effort: DWMWA_USE_IMMERSIVE_DARK_MODE=20 (BOOL 1),
                                      # DWMWA_SYSTEMBACKDROP_TYPE=38 (=2 Mica), DWMWA_WINDOW_CORNER_PREFERENCE=33 (=2)
```

## Integrator (me) — app.py wiring summary (for reference)

argparse: `--demo`, `--fps-log`, `--log-level`, `--reset-config`. Order: guard_std_streams →
logging → ensure_dirs → single-instance (skipped in demo) → load_config (+v1 migration side
effects: delete V1_TOKEN_PATH, one-time dialog) → onboarding gate (no client_id and not demo)
→ build clock+source (SpotifyPoller | DemoSource) → LyricsService, ArtworkLoader, OverlayWindow
(position_ms = source.position_ms() + cfg sync_offset), TrayIcon, HotkeyManager,
FullscreenWatcher, TopmostReasserter → connect everything → start → shutdown order per SPEC §5.

## Agent F additionally owns: ui/artwork.py

```python
class ArtworkLoader(QObject):
    art_ready = Signal(str, object)         # (track_id, QImage ~300px)
    art_large_ready = Signal(str, object)   # (track_id, QImage ~640px) — only fetched when cinema preset active
    palette_ready = Signal(str, object)     # (track_id, Palette)
    def __init__(self, parent=None)
    def set_cinema(self, enabled: bool) -> None
    def fetch(self, track: TrackInfo) -> None
#   QNetworkAccessManager async on main thread; disk cache ART_CACHE_DIR (key = sha1(url)),
#   memory LRU 16; after small art decodes: scale to 48x48, build [(r,g,b)...], call
#   core.palette.extract_palette, emit palette_ready. All emissions track_id-guarded.
```

## Acceptance per agent

1. `python -m py_compile <each owned file>` passes.
2. Own tests pass when they don't depend on concurrent packages; otherwise write them
   and note "integration-run" in your report.
3. No interface drift from this contract — if you believe a pinned signature is wrong,
   implement the pin anyway and flag it in your report.
