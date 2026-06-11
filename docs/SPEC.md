# Final Architecture Decision — Lyrics Overlay 2.0

Ground truth verified against v1 source at `F:\TOOLS\Spotify_addon` (`config.py`, `auth.py`, `hotkeys.py`, `spotify_poller.py`, `lyrics_fetcher.py`, `overlay_window.py`): v1 redirect URI is `http://127.0.0.1:8888/callback`, config lives in `%APPDATA%\SpotifyLyricsOverlay\settings.json`, hotkeys are Ctrl+Alt+F9/F10/←/→/0 via a 50 ms PeekMessage spin thread, drift math is anchor+speed-nudge 0.8–1.2 with 1500 ms hard re-anchor, cache dir `lyrics_cache` with 7-day negative TTL, positive `sync_offset_ms` = lyrics earlier.

## Part A — Proposal scoring

| | Visuals/Motion | Engineering | Product/UX | Accuracy vs ground truth | Overall |
|---|---|---|---|---|---|
| **P1 visual-first ("Lumen")** | **9.5** — most precise motion numbers (toast choreography, glow envelope, fractional blur via tier mixing, 1200 ms loading-label delay, panel+shadow-margin window sizing) | 7 — hotkey worker thread is more machinery than needed; otherwise solid | 6 — no onboarding; settings-first | Uses 8898 redirect (breaks v1 dashboard apps) | **8.0** |
| **P2 engineering-first ("Lyra")** | 7.5 — sound but coarser (blur cap 5 too expensive, opacity tiers less tuned) | **9.5** — best threading (atomic anchor swap, exactly-2-threads+pool), main-thread hotkeys via native event filter (deletes the WM_QUIT dance), failure matrix, raw-payload cache, test seams, CI grep ban on `setWindowFlags` | 6.5 — onboarding is a settings page | Most faithful to v1 source; also uses 8898 | **8.2** |
| **P3 product-first ("Lyric Overlay")** | 8 — good numbers, correct call that Apple fills **white** not accent | 7.5 — `threading.Thread` hotkeys + WM_APP rebind protocol is workable but heavier than P2's filter; lock on anchor (worse than P2) | **9.5** — demo-first wizard, keeps v1's 8888 URI (zero dashboard edits), error→fix mapping, tap-to-sync, "Re-sync lyrics", unsynced auto-paging | Correctly preserved 8888 | **8.4** |

**Synthesis rule applied:** P2's skeleton (threading, module split, failure handling, testability) + P1's visual/motion numbers (with three corrections) + P3's product layer (wizard, URI continuity, fill-color default, resilience UX).

**Key conflict resolutions (rationale):**
1. **Redirect URI = `http://127.0.0.1:8888/callback`** (P3). v1 ships 8888; existing users' dashboard apps migrate with zero edits. Loopback literal is compliant with post-Nov-2025 rules. P1/P2's 8898 buys nothing.
2. **Hotkeys on the main thread** via `RegisterHotKey(hWnd=NULL)` + `QAbstractNativeEventFilter` (P2). Deletes the queue-priming/PostThreadMessage/WM_QUIT dance and makes P3's rebinding trivial (plain unregister/re-register on main thread). Qt's dispatcher delivers `WM_HOTKEY`; worst-case latency = main-loop lag, irrelevant here.
3. **Karaoke fill default = white** ("Ink" theme, P3) — Apple Music fills white; accent drives glow/dots/pill/tray/toast. "Accent" and "Classic" (#1DB954) modes preserved. Unsung ink **28 %** (P3 — between AMLL's 20 % and P1's 32 %).
4. **Blur tiers 0 / 1.5 / 3 px, cap 3** (P1+P3 majority; P2's 5 px tier blows the raster budget). Fractional blur = alpha-mix of adjacent cached tiers (P1).
5. **Opacity tiers** = P3's (1.00/0.72/0.50/0.34/0.24) — P1's floor 0.14 is illegible, P2's 0.85 near-tier kills the active-line pop.
6. **Position anchor = lock-free atomic reference swap** of a frozen dataclass (P2), not P3's lock.
7. **Onboarding wizard ships** (P3); first run never dead-ends (v1 exited code 1 without credentials).
8. **Poll floor raised to 1000 ms** (P2; v1 floor 300 ms is rate-limit-hostile and the API has ~1 s granularity anyway).
9. **Panel radius 16 px** (P2+P3 majority), with P1's glass strokes and painted shadow kept.
10. **Cache stores raw API payloads** (P2) so parser upgrades re-apply offline; new dir `lyrics_cache_v2`, v1 cache untouched.
11. **Display name "Lyric Overlay"** (P3, trademark hygiene); package `lyrics_overlay`; config dir **stays** `%APPDATA%\SpotifyLyricsOverlay` (P2 — zero-friction migration).
12. `docs\ARCHITECTURE.md` (PyQt6 draft) is superseded by this spec; v1 top-level modules deleted at integration.

---

# Part B — THE FINAL SPECIFICATION

## 1. File / module layout

```
main.py                       # console entry: sys.exit(lyrics_overlay.app.run(sys.argv))
LyricOverlay.pyw              # windowed entry (Run key / double-click), imports main
lyrics_overlay/
  __init__.py                 # __version__="2.0.0"; USER_AGENT="LyricOverlay/2.0.0 (+https://github.com/overdusts/Spotify_addon)"
  app.py                      # composition root: argparse(--demo,--fps-log,--log-level,--reset-config),
                              #   single-instance gate, config load/migrate, onboarding gate,
                              #   source select (Spotify|Demo), wiring, deterministic shutdown
  config.py                   # DEFAULTS (schema_version=2), atomic load/save (tmp+os.replace), migrate_v1()
  paths.py                    # %APPDATA%\SpotifyLyricsOverlay: settings.json, spotify_token.json,
                              #   lyrics_cache_v2/, art_cache/, logs/
  logsetup.py                 # pythonw guard: if sys.stderr is None -> replace BEFORE anything else
                              #   (cpython #122633/#107792); RotatingFileHandler 1MB x3; no StreamHandler under pythonw
  models.py                   # frozen dataclasses: TrackInfo, LyricWord, LyricLine, LyricDoc,
                              #   PlaybackAnchor, Palette; sentinels INSTRUMENTAL, NOT_FOUND
  core/                       # ---- pure logic, ZERO Qt imports, 100% unit-tested ----
    clock.py                  # PlaybackClock: holds one _anchor: PlaybackAnchor(progress_ms, mono_time,
                              #   speed, playing); whole-object reference swap = atomic read/write
    springs.py                # closed-form damped-harmonic solver (AMLL port): under/overdamped branches,
                              #   arrival |x|<0.01 and |v|<0.01 -> snap+sleep; dt clamped <=50ms
    timeline.py               # bisect index_at(ms), line_bounds (next-start or +4000ms), line_progress,
                              #   word_fills (width-weighted estimate w/ 120ms-per-word floor, renormalized;
                              #   exact when word times exist), interlude(pos) for gaps>4000ms
    lrcparse.py               # LRC: \[(\d+):(\d{2})(?:[.:](\d{2,3}))?\] line tags, stacked tags,
                              #   [offset:±ms] (positive=earlier, added to every stamp), A2 <..> word tags
    lyricsfile.py             # Lyricsfile YAML v1.0 -> LyricDoc; ENTIRE parse in try/except -> None
                              #   (format reserves breaking changes); word text carries own spacing
    wrap.py                   # greedy word-wrap; measure fn INJECTED (QFontMetricsF prod, dict in tests)
    palette.py                # accent: 48x48 RGB ints -> OKLab k-means(k=5, 12 iters) ->
                              #   score = chroma * pop^0.5 * w(L) peaked L∈[0.40,0.75];
                              #   OKLCh clamp L∈[0.74,0.88], C<=0.17; raise L until contrast>=4.5:1;
                              #   derive glow(L+0.06), dim(45% alpha), contrast(white|near-black);
                              #   OKLab lerp helper for crossfades. Pure ints, no numpy (<8ms / 2304 px)
  sources/
    base.py                   # PlaybackSource contract: signals track_changed(TrackInfo),
                              #   playback_state(bool), connection_state(kind,msg); position_ms(); start()/stop()
    spotify_auth.py           # SpotifyPKCE builder (client_id only), cache_path=paths.spotify_token,
                              #   typed AuthRequired/AuthFailed; corrupt-cache trap -> delete -> re-auth route
    spotify_source.py         # SpotifyPoller(QThread): 1s current_playback(additional_types="episode");
                              #   drift correction (v1 math verbatim, below); 204/ad/episode/429/401/network matrix;
                              #   sleeps in 250ms slices checking stop flag
    demo_source.py            # DemoSource(QObject+QTimer on main thread): identical contract; spec section 8
  lyrics/
    lrclib.py                 # LrclibClient (~80 lines on requests.Session, injectable for tests):
                              #   GET /api/get(track,artist,album,duration_s rounded) -> /api/get sans album
                              #   -> /api/search + v1 word-boundary artist matcher -> track-name-only search;
                              #   UA header; name=="TrackNotFound" -> NOT_FOUND; 10s timeout, 2 retries;
                              #   network errors raise (never negative-cached)
    cache.py                  # memory dict + disk JSON: key=sha1("name|artist|album|dur_s")[:16];
                              #   stores RAW syncedLyrics+lyricsfile+instrumental+status+ts;
                              #   positive permanent, not_found/instrumental TTL 7 days; atomic writes
    service.py                # LyricsService(QObject): QThreadPool(max 2) fetch; monotonic generation
                              #   token — only newest request may emit lyrics_ready(track_id, result)
  ui/
    overlay.py                # OverlayWindow(QWidget): flags/attrs at creation, state machine, drag+snap
                              #   (snap to h-center + 24px edges, Alt suppresses), per-monitor geometry,
                              #   config apply/diff. HARD RULE: never setWindowFlags/setWindowOpacity after show()
    render_loop.py            # requestUpdate() chain (QEvent.UpdateRequest -> tick -> paint -> request);
                              #   QElapsedTimer dt; PreciseTimer fallback at round(1000/refreshRate);
                              #   fps cap 30|60|display; FULLY STOPS when scene settled & no transients
    scene.py                  # LyricScene: per-line springs, cascade stagger, toast/dots/pill/state
                              #   timelines, dirty-rect computation; consumes position from clock pull
    line_cache.py             # per-line strips: QImage ARGB32_Premultiplied at devicePixelRatio,
                              #   tiers sharp/blur1.5/blur3 (box-blur x3); built lazily visible±2 only;
                              #   invalidate on font/width/DPR/track change (screenChanged hook)
    painters.py               # stateless paint fns: feathered karaoke fill, context line, dots,
                              #   toast card, status pill, shadow|outline|scrim text protection
    artwork.py                # ArtworkLoader(QObject): QNetworkAccessManager (async, main thread);
                              #   fetch 300px (palette) + 640px (cinema); LRU(16); emits art_ready(track_id,QImage)
                              #   then computes palette (main thread, <8ms) -> palette_ready(track_id,Palette)
    tray.py                   # accent-tinted runtime note icon; tooltip "Track — Artist"; menu:
                              #   Show/Hide(hotkey label), Lock/Unlock position, Move to monitor ▸,
                              #   Re-sync lyrics (cache-bust current), Demo mode, Settings, Quit; dbl-click toggles
    settings_dialog.py        # framed OPAQUE dark window, Mica+dark titlebar (sec.6); live preview strip;
                              #   live-apply debounced 150ms; Cancel restores entry snapshot; spec section below
    onboarding.py             # 4-page QWizard (spec below)
    monitor_map.py            # shared widget: monitor rectangles + preset dots + drag ghost
  win/                        # every fn guards sys.platform=="win32"; no-op elsewhere
    clickthrough.py           # SetWindowLongPtrW/SetWindowPos pattern + assert_styles() watchdog helper
    hotkeys.py                # HotkeyManager (MAIN thread): RegisterHotKey(None,...) + QAbstractNativeEventFilter
                              #   on b"windows_generic_MSG"; per-key result+GetLastError; rebind = unregister/register
    fullscreen.py             # FullscreenWatcher(QTimer 1.5s): SHQueryUserNotificationState ∈{1,2,3,4,7}
                              #   OR foreground rect ⊇ overlay's monitor rect (skip Progman/WorkerW/own hwnd,
                              #   use DWMWA_EXTENDED_FRAME_BOUNDS); emits fullscreen_changed(bool)
    topmost.py                # opt-in QTimer 1.5s: SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE)
    startup.py                # HKCU\Software\Microsoft\Windows\CurrentVersion\Run value "LyricOverlay" =
                              #   "<venv>\Scripts\pythonw.exe" "<abs>\LyricOverlay.pyw" via winreg;
                              #   NEVER touches StartupApproved
    instance.py               # CreateMutexW("Local\\LyricOverlay_SingleInstance") detection +
                              #   QLocalServer "show" activation (removeServer before listen)
    dwm.py                    # DWMWA_SYSTEMBACKDROP_TYPE=38(val 2 Mica), DWMWA_USE_IMMERSIVE_DARK_MODE=20,
                              #   DWMWA_WINDOW_CORNER_PREFERENCE=33 — DIALOGS ONLY, never the overlay
assets/
  demo_track.json             # original 60s demo lyric (section 8)
  icon.svg / icon.ico
tests/                        # pytest, no QApplication needed for core/:
  test_springs.py test_timeline.py test_lrcparse.py test_lyricsfile.py test_wrap.py
  test_palette.py test_clock.py test_cache.py test_lrclib.py (recorded fixtures) test_config_migration.py
  test_scene_states.py        # pytest-qt offscreen: DemoSource drives full state machine
```

## 2. Feature checklist & behavior specs

### Preserved from v1 (all must pass acceptance)
1. **Transparent frameless always-on-top overlay** — creation-time `FramelessWindowHint|WindowStaysOnTopHint|Tool|WindowDoesNotAcceptFocus` + `WA_TranslucentBackground` + `WA_ShowWithoutActivating`; ctypes belt-and-suspenders `WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW` at show. Window = panel + 40 px shadow margin, never screen-sized (layered-window upload cost).
2. **Click-through toggle** — pure Win32 ex-style flip (sec. 6), no recreation, no blink. Unlocked: dashed 1 px border + "Unlocked — drag to move" pill.
3. **LRCLIB line-synced lyrics** — fallback chain per `lyrics/lrclib.py` above; plain-lyrics-only result → unsynced view (auto-paged by `progress/duration`, "unsynced" badge).
4. **Karaoke per-word fill (estimated)** — line duration ∝ rendered pixel width per word, 120 ms/word floor, renormalized; continuous sweep across wrapped rows; transparently exact when A2 word tags or Lyricsfile present.
5. **Spring smooth scroll** — closed-form AMLL springs (sec. 3); settles exactly, sleeps.
6. **Context dimming** — opacity tiers + distance blur (sec. 3).
7. **Cache** — semantics identical to v1 (positive permanent, negative/instrumental 7-day); new dir `lyrics_cache_v2`, raw payloads stored; v1 cache untouched.
8. **Polling + drift correction (v1 math verbatim)** — anchor `(progress_ms, time.monotonic())` at receipt (never the response `timestamp`); render reads `anchor + elapsed×speed`; `|drift|>1500 ms` → hard re-anchor + scene re-snap with gentle spring; else `speed=clamp((window+drift)/window, 0.8, 1.2)` and re-anchor. Pause freezes at anchor; resume re-anchors. One API call/tick.
9. **Global hotkeys** — Ctrl+Alt+F9 show/hide, Ctrl+Alt+F10 click-through, Ctrl+Alt+← −100 ms, Ctrl+Alt+→ +100 ms, Ctrl+Alt+0 reset; all `MOD_NOREPEAT`; per-key failure surfaced (sec. 6); every action also reachable from tray.
10. **Sync offset** — ±5000 ms persisted, **positive = lyrics earlier**, applied at position read (`pos + offset`); pill confirms ("Sync +200 ms").
11. **Tray icon + menu** — per `ui/tray.py` above; icon tinted with live accent.
12. **Settings dialog** — all v1 controls survive minus client secret (sec. 4).
13. **Track toast** — album-art card, 4.0 s lifecycle (sec. 3.7).
14. **Loading/instrumental/no-lyrics states** — redesigned (sec. 3.8) + new states.
15. **Word wrap** — greedy on `QFontMetricsF.horizontalAdvance` at `max_line_width_percent`; cached per (line, font, width); karaoke sweep spans rows.
16. **Drag-to-reposition** (when unlocked) with snap; persisted per monitor.
17. **Token recovery** — spotipy auto-refresh + rotation persistence; persistent 401 → AUTH_REQUIRED + tray balloon + one-click reconnect.

### New in v2
18. **PKCE auth (no secret)** — sec. 7. Migration deletes `spotify_client_secret`, forces one re-auth with a one-time explanation dialog (confidential refresh tokens can't refresh without the secret).
19. **`--demo` mode** — sec. 8.
20. **Onboarding wizard** — page 1 Welcome ["Try it now (demo)" starts the real overlay behind the wizard | "Connect Spotify"]; page 2 dashboard checklist with copy buttons (Premium note, exact URI `http://127.0.0.1:8888/callback`, Client ID field live-validated as 32 lowercase hex); page 3 Authorize (spinner → "Connected", error map: `INVALID_CLIENT: Invalid redirect URI` → "URI must be exactly …", 403 → "Add your account under Users and Access (max 5)"); page 4 Place & style (monitor map + presets Minimal/Panel/Cinema, live). Re-runnable from Settings. Overlay starts unlocked with a one-time hint chip; auto-locks after first manual lock or 60 s.
21. **Album art + adaptive accent** — `core/palette.py` pipeline; accent drives glow, dots, pill, tray, toast; 600 ms OKLab crossfade on track change; `accent_auto=false` → manual `highlight_color`.
22. **Interlude dots** — sec. 3.6.
23. **Fullscreen auto-hide (default ON)** — fade out 200 ms on fullscreen app on the overlay's monitor; restore fade 300 ms. Opt-in "Show over fullscreen games" → topmost re-assert 1.5 s + latency note (Composed-Flip cost).
24. **Launch at startup** — HKCU Run toggle.
25. **Single instance + activation** — mutex + QLocalServer "show".
26. **Hotkey rebinding** — key-capture widgets, live re-register, inline "In use by another app" on `GetLastError()==1409`; rejected: F12, Win-combos, F23/Copilot, bare Ctrl+Shift / Alt+Shift.
27. **Legibility modes** — shadow (default: offset (0,2), blur 6 px, black 60 %) | outline (1.5 px `QPainterPathStroker`, black 85 % — v1 look) | per-line scrim (black 45 %, radius 8, padding 0.3 em).
28. **Animation budget** — Full / Reduced (no blur, no per-word motion, active line only animates) / Minimal (no springs, instant snap, karaoke still fills); **auto-drop one tier when frame-time p95 > 12 ms over 5 s** (logged).
29. **Resilience** — failure matrix sec. 5; 429 honors `Retry-After`+1 s with pill; network backoff 2→4→8→…30 s in CONNECTING; lyrics network failures never negative-cached.
30. **Position presets + multi-monitor** — presets top-center (default) / bottom-center / custom per `QScreen.name()`; unplugged monitor → migrate to primary, restore on return; caches invalidated on `screenChanged`.
31. **Word-level ingestion** — Enhanced-LRC `<mm:ss.xx>` + Lyricsfile YAML → exact fills; fail-soft, never gated on it.
32. **Unsynced fallback view** (above), **pythonw-safe logging**, **"Open log folder"/"Clear cache (size shown)"/"Re-sync current track"** actions.
33. **Tap-to-sync** — Settings Sync page: button highlights the upcoming line; user taps when they hear it; offset = computed delta; repeated taps use median of last 3.

## 3. Visual & motion spec (exact numbers)

**Canvas.** Panel width 56 % of work area (clamp 480–1200 logical px); height = `lines_visible` (default **5**, range 3–7) × line slot + 32 px padding; default position top-center, y = 64. Window = panel + 40 px margin for painted shadow.

**3.1 Panel.** Rounded rect r=**16 px**; fill `#000000` at `bg_opacity` **0.35** (0 = naked text + protection mode), tinted 8 % toward accent. Glass: 1 px top inner stroke white 8 %; 1 px bottom inner stroke black 20 %. Shadow: pre-blurred nine-patch, blur 32 px, black 50 %, offset (0,+8). Vertical edge fade: 28 px alpha ramp top/bottom. **Cinema preset** (opt-in): album art →16 px →Gaussian →upscale, saturation 1.15, dark scrim 55 %, +1 % monochrome noise dither (banding), static, 600 ms crossfade per track.

**3.2 Typography.** Segoe UI Variable Display (fallback Segoe UI). Active line: weight **700**, **28 px** default (16–48), letter spacing `PercentageSpacing 98.5`. Context lines: weight 600, **same point size** (differentiation via scale/alpha/blur only). Row height 1.26 × font px; inter-line-block gap 0.6 em. Alignment: **left ragged-right default**, center option (v1 parity); scale origin left-center (center-center when centered). Reserved sub-line slot per line: 0.6 × size, 60 % alpha, 0.15 em below (future translation/romanization; unused in 2.0).

**3.3 Springs** (closed-form; arrival |Δx|<0.01 ∧ |v|<0.01 → snap+sleep; dt from QElapsedTimer clamped 50 ms):

| Spring | mass | damping | stiffness |
|---|---|---|---|
| Line posY base / seek / interlude | 0.9 | 15 | 90 |
| Line posY playback (tempo-adaptive) | 1.0 | 2.2·√(k·m) | k = lerp 170→220 from inter-line interval clamped 800→100 ms |
| Active-line scale | 2.0 | 25 | 100 |

**Cascade:** on advance, line *i* below target starts posY spring after `50 ms × distance`, each successive delay ÷1.05; lines above move immediately.

**3.4 Line presentation.** Scale active **1.00** / inactive **0.97**. Opacity by distance d: **1.00 / 0.72 / 0.50 / 0.34 / 0.24 (d≥4)**; past lines ×0.85; with Accent fill mode, past lines tinted accent at 45 % saturation (v1 continuity). Blur: target `min(1.5·d, 3)` px from cached tiers **0 / 1.5 / 3 px** (box-blur ×3); fractional = alpha-mix of adjacent tiers.

**3.5 Karaoke fill.** Per active line, cached strips at DPR: (a) **ink pass** white at **28 %** alpha; (b) **lit pass** in fill color (default **white**; modes Accent / Classic #1DB954), clipped by horizontal `QLinearGradient` alpha mask composited `CompositionMode_DestinationIn`: opaque at fillX−0.375 em → transparent at fillX+0.375 em (**0.75 em feather**); (c) **glow pass** — lit strip blurred 0.3 em drawn beneath for words held ≥900 ms: alpha eases 0→**0.55** over first 40 % of word (ease-out-quad), holds, decays over final 25 %. Word micro-motion: **Subtle** (default) scale 0.985→1.000 + translateY −1.5→0 px over word duration, ease-out-cubic; **Bounce** 0.92→1.0 easeOutBack(s=1.70158) — v1 nostalgia; **Off**.

**3.6 Interlude dots.** Trigger: gap >4000 ms (evaluated 250 ms early) + pre-first-line. 3 dots, ⌀0.42 em, gap 0.5 em, accent-colored. Entrance: invisible 0–500 ms, linear fade 500–1000 ms. Dot k activates at k/3 of gap; per-dot alpha 0.25→0.75. Breathing: scale 1±0.05·sin, cycle 1500 ms, base 0.7. Exit: final 750 ms scale→0 easeInOutBack, alpha fade over last 375 ms.

**3.7 Track-change choreography.** t=0: current lines exit — alpha→0, translateY −14 px, 320 ms ease-in-cubic, 24 ms stagger top-down. Accent + cinema backdrop crossfade 600 ms (OKLab); tray re-tints. Toast: card r=14, bg black 72 %, art 56×56 r=10, title 15 px w600 white, artist 12.5 px white 65 %; in 280 ms translateY −12→0 + fade, cubic-bezier(0.16,1,0.3,1); hold 3.3 s; out 420 ms fade + translateY −8 ease-in-cubic (4.0 s total ≈ v1). Lyrics arrival: lines cascade in from +18 px with the 50 ms stagger.

**3.8 States.** LOADING: dots breathing; "Finding lyrics…" 14 px white 55 % appears only after **1200 ms** (no flash on cache hits). INSTRUMENTAL: dots all track + "Instrumental" 16 px accent 80 %. NO_LYRICS: title 22 px white 85 % / artist 15 px white 55 % / "No lyrics found" 13 px white 40 %; panel auto-fades after 6 s (doesn't nag). PAUSED: panel →0.72 opacity over 400 ms, springs frozen; resume →1.0 in 250 ms. IDLE (204/nothing): 10 s grace → 600 ms fade-out; tray stays. AD: "Ad break" pill, lyrics suppressed. EPISODE: "Podcast playing" pill, auto-fade 4 s. RATE_LIMITED/CONNECTING: "Reconnecting…" pill. AUTH_REQUIRED: pill + tray balloon. **Status pill**: capsule 13 px, bg black 65 %, accent text; in 120 ms fade + scale 0.92→1 ease-out-quad; hold 1.4 s; out 300 ms.

**3.9 Render loop & budgets.** `requestUpdate()` chain; runs only while springs unsettled / karaoke advancing / transient alive; otherwise fully stopped (0 % CPU idle). FPS cap setting 30 / **60 (default)** / display-rate; refresh re-read on `screenChanged`. Budget: full panel repaint <3 ms; steady-state dirty rect = active line + one neighbor; zero per-frame text shaping (all strips cached). `--fps-log` flag writes frame-time histogram.

## 4. Settings dialog
Framed **opaque** window 720×560 (translucent+framed = black box on Qt6), Mica (`DWMWA_SYSTEMBACKDROP_TYPE=2`) + dark titlebar + rounded corners, fallback `#1e1e1e` pre-22H2. **Top: full-width 132 px live preview** — the real `painters.py`/`scene.py` running the demo timeline; all changes live-apply to preview + real overlay, debounced 150 ms; **Cancel restores entry snapshot (incl. position), OK persists atomically**; per-page Reset. Single `config_changed(dict)` signal; overlay diffs keys to invalidate only affected caches. Left icon-rail pages:
- **Appearance**: style presets (Minimal/Panel/Cinema cards), font, size 16–48, alignment, fill mode White/Accent/Classic, word motion Subtle/Bounce/Off, accent Auto + manual swatch, bg opacity 0–100, legibility mode (3 mini-preview cards), lines 3–7, width 30–90 %, wrap width 50–100 %, animation budget, dots toggle.
- **Position**: monitor_map widget, presets, snap toggle, "Unlock & drag".
- **Behavior**: click-through default, toast toggle, fullscreen auto-hide vs show-over-games (radio + latency note), start with Windows.
- **Sync**: offset spinbox ±5000 step 50 ("positive = earlier"), tap-to-sync calibrator, poll interval 1000–5000 ms.
- **Shortcuts**: 5 rows — action, key-capture, registered/failed status, enable checkbox, restore defaults.
- **Account**: connected card (masked Client ID, Reconnect, Disconnect=delete token cache), redirect URI + copy, "Run setup again", Premium/5-user note, "Run demo mode".
- **About/Diagnostics**: version, open log folder, clear cache (size), re-sync current track, LRCLIB credit.

## 5. Threading & data-flow

**Exactly 2 threads + pool.** Main thread: QApplication, OverlayWindow+RenderLoop+LyricScene, ArtworkLoader (QNAM async), palette computation (post-decode, <8 ms once/track), DemoSource, FullscreenWatcher, HotkeyManager (native event filter), tray, dialogs, QLocalServer. **SpotifyPoller (QThread)**: exclusively owns the spotipy client (Session not thread-safe); blocking loop; stop-flag checked in 250 ms slices. **QThreadPool (max 2)**: lyrics fetch QRunnables (pure `lrclib.py`+`cache.py`).

**Position is a pull, not a push**: render tick calls `source.position_ms()` → `PlaybackClock` reads its single `_anchor` frozen-dataclass reference (writer swaps the whole object; CPython reference assignment is atomic — no lock, no torn read). Lyric time advances at render rate, not poll rate.

**Signals (all cross-thread = auto-queued; payloads frozen dataclasses/str):**
```
poller.track_changed(TrackInfo)        -> scene.begin_track (LOADING+toast), service.request (gen+=1), artwork.fetch
poller.playback_state(bool)            -> scene freeze/resume, tray tooltip
poller.connection_state(kind,msg)      -> pill (CONNECTING/RATE_LIMITED/AUTH_REQUIRED/OK), tray balloon on auth
service.lyrics_ready(track_id,result)  -> drop if track_id != current; else LYRICS/INSTRUMENTAL/NO_LYRICS
artwork.art_ready / palette_ready      -> toast art, 600ms accent crossfade, tray tint (track_id-guarded)
hotkeys.{toggle_visible,toggle_clickthrough,offset_delta(int)} -> app handlers (already main thread)
fullscreen.fullscreen_changed(bool)    -> overlay visibility (respecting user-hidden state)
settings.config_changed(dict)         -> overlay.apply, poller.set_poll_interval, hotkeys re-register, startup
```

**Poller failure matrix (per tick):** 204/None → IDLE, keep polling • `currently_playing_type=="ad"|"unknown"` → AD, lyrics suppressed • episode → EPISODE (track fields still emitted) • 429 → suspend `Retry-After`+1 s, RATE_LIMITED • 401 → spotipy auto-refresh; 2nd consecutive failure → AUTH_REQUIRED, polling suspended until reconnect • ConnectionError/timeout → CONNECTING, backoff 2,4,8…30 s, auto-recover. Lyrics network failure ≠ NOT_FOUND (never negative-cached).

**Staleness:** every async product carries `track_id`; LyricsService additionally uses a monotonic generation token. **Shutdown order (app.py):** hotkeys unregister → render loop stop → fullscreen/topmost timers stop → `poller.stop(); wait(3000)` → `threadpool.waitForDone(2000)` → config save → tray hide → process exit releases mutex. **Hard rules:** no Qt widget/pixmap off main thread; no module-level Qt objects; CI grep bans `setWindowFlags(`/`setWindowOpacity(` outside `overlay.py` creation block.

## 6. Windows integration
- **Click-through (no recreation):** `SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT|WS_EX_LAYERED)` (clear `WS_EX_TRANSPARENT` to disable) + `SetWindowPos(0,0,0,0,0, NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED)`; 64-bit-correct argtypes, W functions. **Watchdog:** `assert_styles()` compares `GetWindowLongPtrW` to desired mask and re-applies — invoked after `screenChanged`, every visibility change, every config apply, and on a 2 s timer (Qt clobbers manual ex-styles when it re-applies flags). Never call `SetLayeredWindowAttributes` (breaks Qt's `UpdateLayeredWindow`).
- **Hotkeys:** main thread; `RegisterHotKey(None, id 1–5, MOD_CONTROL|MOD_ALT|MOD_NOREPEAT, vk)`; `WM_HOTKEY (0x0312)` caught in `QAbstractNativeEventFilter(b"windows_generic_MSG")`. Per-key result + `GetLastError` captured (1409 = taken) → Settings status + one-time tray balloon. Rebind = unregister/re-register inline. `UnregisterHotKey` ×5 at shutdown. Forbidden: F12, Win-mods, F23, bare Ctrl+Shift/Alt+Shift.
- **Fullscreen auto-hide:** `FullscreenWatcher` 1.5 s QTimer → `SHQueryUserNotificationState` ∈ {1,2,3,4,7} OR foreground-window rect (via `DWMWA_EXTENDED_FRAME_BOUNDS`) ⊇ overlay's monitor `rcMonitor` (`MonitorFromWindow`), excluding `Progman`/`WorkerW`/own hwnd. Hide = 200 ms fade; restore = 300 ms. No undocumented shellhook 53/54.
- **Show-over-games (opt-in):** disables auto-hide; 1.5 s `SetWindowPos(HWND_TOPMOST, …NOACTIVATE)` re-assert; settings note about composition-frame latency. Exclusive-fullscreen (QUNS=3) always hides regardless.
- **Single instance:** `CreateMutexW(None, False, "Local\\LyricOverlay_SingleInstance")`; `ERROR_ALREADY_EXISTS` → connect QLocalSocket "LyricOverlay", send `"show"`, exit 0; first instance raises overlay on `newConnection`. `QLocalServer.removeServer` before `listen`. `--demo` skips all of this.
- **Startup:** HKCU Run value `LyricOverlay` = `"<venv>\Scripts\pythonw.exe" "<abs>\LyricOverlay.pyw"` via `winreg`; remove on toggle-off; StartupApproved untouched.
- **DWM polish (dialogs only):** Mica backdrop, immersive dark mode, round corners. The overlay itself gets **no** DWM backdrop (fragile with per-pixel-alpha layered windows) — frosted look is painted.
- **pythonw safety:** first statements of `main.py` replace `None` std streams before any import that might print.

## 7. PKCE auth flow (step-by-step)
1. User supplies **Client ID only** (wizard/Settings; validated `^[0-9a-f]{32}$`). Redirect URI fixed: **`http://127.0.0.1:8888/callback`** (v1 continuity; loopback-literal compliant; `localhost` banned since Nov 2025).
2. Build `spotipy.oauth2.SpotifyPKCE(client_id, redirect_uri, scope="user-read-playback-state user-read-currently-playing", cache_handler=CacheFileHandler(cache_path=%APPDATA%\SpotifyLyricsOverlay\spotify_token.json), open_browser=True)`.
3. "Connect" → spotipy generates `code_verifier` (43–128 chars) + `code_challenge=base64url(sha256(verifier))`, opens browser to `https://accounts.spotify.com/authorize?client_id&response_type=code&redirect_uri&code_challenge_method=S256&code_challenge&scope&state`, and runs a loopback HTTP listener on 8888 to capture `?code=`.
4. Token exchange `POST https://accounts.spotify.com/api/token` with `grant_type=authorization_code, code, redirect_uri, client_id, code_verifier` — **no secret, no Basic header**. Access token TTL 3600 s.
5. spotipy auto-refreshes per request (`grant_type=refresh_token` + `client_id`) and **persists rotated refresh tokens** to the cache file. Corrupt cache JSON at startup → trap, delete file, route to Connect (never crash).
6. Persistent refresh failure (2 consecutive 401) → AUTH_REQUIRED state, poll suspended, tray balloon → one-click re-auth.
7. Error mapping (wizard + settings): `INVALID_CLIENT: Invalid redirect URI` → exact-URI fix text + dashboard link; 403 → "Add your account under Users and Access (5-user cap)"; general → "Premium required for dev-mode apps since Feb 2026".
8. Migration from v1: keep `spotify_client_id` + `spotify_redirect_uri`; delete `spotify_client_secret`; delete v1 `.spotify_cache`; one-time dialog explains the forced re-auth.
9. README/onboarding state: Premium required, own Dashboard app, 5 users max, 1 dev-mode Client ID per developer.

## 8. Demo mode (`--demo`)
- `DemoSource(QObject)` on main thread, QTimer 33 ms tick; implements the **identical** `PlaybackSource` contract — overlay cannot distinguish it (the contract is the test seam).
- Bundled **original** (written by us, no copyrighted text) `assets/demo_track.json`: 60 s, loops; line + word timings; required content: ≥6 s instrumental gap (exercises dots), a fast line burst (<400 ms inter-line — exercises tempo-adaptive stiffness), one >1.2 s held word (glow), one long wrapping line (wrap+sweep across rows), scripted **seek at t=45 s** (re-anchor spring), scripted **pause 3 s at t=20 s** (PAUSED dim).
- Skips: auth, single-instance, Spotify polling, network (lyrics served from the JSON via the normal `lyrics_ready` path; art = bundled gradient image so palette path runs).
- Reachable via `--demo` flag, tray "Demo mode", onboarding page 1, Settings Account page. Combined with `--fps-log` it is the perf-acceptance harness; with pytest-qt (offscreen) it drives the state-machine integration tests.

## 9. Dependencies (pinned)
| Package | Pin | Notes |
|---|---|---|
| Python | 3.13 | target |
| PySide6 | `>=6.8,<6.12` (dev 6.11.1) | Qt 6.11; refresh-aware requestUpdate; PMv2 DPI |
| spotipy | `>=2.26.0` | SpotifyPKCE; Feb-2026 API surface; rotation persistence |
| requests | `>=2.32` | LRCLIB REST (lrclibapi **dropped**: frozen 2023, dead `/get-cached`, drops `lyricsfile`) |
| PyYAML | `>=6.0.2` | `safe_load` only, Lyricsfile |
| dev | pytest>=8, pytest-qt>=4.4, ruff>=0.6 | |

Stdlib only beyond: `ctypes`, `winreg`, `json`, `bisect`, `hashlib`, `logging`. **No** Pillow, numpy, pywin32, keyring, lrclibapi.

## 10. Implementation order & risk mitigations
**Phases (each independently runnable/testable):**
1. **Skeleton + pure core** — package, `paths/config(+migrate_v1)/logsetup/models`; `core/springs|lrcparse|timeline|wrap|palette|clock` with full pytest suite. *Exit: tests green, no Qt.*
2. **Demo-driven visuals** — `demo_source`, `overlay` shell (flags, drag), `render_loop`, `scene` springs + cascade. *Exit: `--demo` shows scrolling lines with correct motion.*
3. **Renderer completion** — `line_cache` (DPR strips + blur tiers), karaoke feathered fill + glow, dots, toast, all states, legibility modes, edge fades. *Exit: demo is screenshot-grade; `--fps-log` <3 ms repaint.*
4. **Windows layer** — clickthrough+watchdog, hotkeys (native filter), single instance, fullscreen watcher, topmost, tray. *Exit: all hotkeys work, no blink, auto-hide verified.*
5. **Lyrics pipeline** — `lrclib` client (recorded-fixture tests), `cache`, `service`, Enhanced-LRC + Lyricsfile ingestion, unsynced fallback.
6. **Spotify** — PKCE auth, poller + clock wiring, failure matrix; live end-to-end.
7. **Artwork + accent** — fetch, palette, crossfades, cinema preset, tray tint.
8. **Settings + onboarding** — dialog with live preview, monitor map, rebinding, startup toggle, wizard, migration dialog.
9. **Hardening** — auto budget-drop, watchdog soak test, README (Premium/Client-ID/URI), delete v1 modules + `docs/ARCHITECTURE.md` supersession note.

**Risks → mitigations:**
1. *Qt strips manual `WS_EX_TRANSPARENT`* → all ex-style writes centralized in `win/clickthrough.py`; CI grep ban on `setWindowFlags`/`setWindowOpacity` post-show; 2 s + event-driven watchdog self-heals.
2. *Spotify policy churn (Premium, 5-user, possible endpoint cuts)* → single endpoint, two scopes, real Retry-After backoff, 1 s floor, PKCE + loopback literal; demo mode keeps dev/screenshots offline; `PlaybackSource` protocol reserves a 2.1 SMTC (Windows media session) source as Spotify-free fallback.
3. *Layered-window upload + blur perf* → panel-sized window, pre-baked blur tiers (visible±2 only), dirty rects, loop sleeps at idle, budget setting + auto-drop, `--demo --fps-log` acceptance gate.
4. *LRCLIB volatility (lyricsfile breaking changes, slow first-miss, removed endpoints)* → own REST client, fail-soft lyricsfile→LRC→estimated chain, raw payloads cached for retroactive re-parse, 10 s timeout, 1200 ms label delay, 7-day negative cache, recorded-fixture contract tests.
5. *Hotkey collisions (Ctrl+Alt+arrows = Intel display rotation, etc.)* → per-key registration results surfaced, rebinding shipped, all actions tray-reachable, MOD_NOREPEAT everywhere.
6. *Estimated word timing wrong on fast tracks* → 120 ms/word floor + 0.75 em feather (errors read soft), glow only ≥900 ms, exact timings adopted when available, white-fill default de-emphasizes the sweep.
7. *Onboarding abandonment* → demo-first wizard, copy-button URI identical to v1 (8888), Client-ID format validation before network, every auth error mapped to a one-line fix.
