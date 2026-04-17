# Spotify Lyrics Overlay

A transparent, always-on-top desktop overlay that displays synced lyrics from Spotify with karaoke-style progressive fill animations. Sits at the top of your screen so you can read lyrics while you work — no window switching needed.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15+-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)

## Features

- **Karaoke-style fill** — words fill left-to-right in green as they're sung, like Apple Music
- **Smooth scroll** — lines glide up with a spring-damper animation, not harsh jumps
- **Past/future context** — already-sung lines show in faded green, upcoming lines in dim white
- **Fully click-through** — transparent overlay lets mouse events pass through to whatever's behind
- **Global hotkeys** — toggle visibility, click-through, and sync offset from anywhere
- **Persistent cache** — lyrics saved to disk, instant reload for songs you've played before
- **Sync offset adjustment** — nudge timing by ±100ms in real time if your audio has latency
- **Word wrap** — long lyric lines wrap gracefully instead of overflowing the screen
- **Loading / instrumental / no-lyrics states** — clear visual feedback in every situation
- **Track info peek** — song name fades in briefly when the track changes
- **Adaptive polling** — smooth drift correction keeps timing accurate between API calls
- **Token recovery** — auto-refresh when Spotify token expires, no restart needed
- **Strict lyrics matching** — artist validation prevents showing lyrics for the wrong song

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Click **Create App**
3. Set **Redirect URI** to `http://127.0.0.1:8888/callback`
4. Select **Web API**
5. Save and copy your **Client ID** and **Client Secret**

### 3. Run

```bash
python main.py
```

On first launch, a settings dialog will ask for your Spotify credentials. After saving, your browser opens for Spotify authorization. Once approved, the overlay appears on screen.

## Global Hotkeys

| Shortcut | Action |
|---|---|
| `Ctrl+Alt+F9` | Show / Hide overlay |
| `Ctrl+Alt+F10` | Toggle click-through |
| `Ctrl+Alt+←` | Lyrics -100ms (appear later) |
| `Ctrl+Alt+→` | Lyrics +100ms (appear earlier) |
| `Ctrl+Alt+0` | Reset sync offset |

## Settings

Right-click the system tray icon → **Settings**. Four tabs:

- **Appearance** — font, size, colors, opacity, width, visible lines, wrap width, click-through
- **Sync** — sync offset, poll interval
- **Spotify** — credentials
- **Shortcuts** — hotkey reference

Settings live in `%APPDATA%\SpotifyLyricsOverlay\settings.json` (Windows) or `~/.config/spotify-lyrics-overlay/` (elsewhere). Lyrics cached per-track in the same folder.

## How It Works

1. **Spotify Poller** (background thread) — polls Web API every 1s for track + position, interpolates between polls with drift correction (playback speed nudged 0.8x–1.2x to converge smoothly instead of jumping)
2. **Lyrics Fetcher** (background thread) — queries LRCLIB with exact `get_lyrics` first, falls back to search with artist validation. Persists results to disk; negative results expire after 7 days in case lyrics get added later.
3. **Sync Engine** — binary-search indexes current line by playback position
4. **Overlay** — conditional repaint (skip when hidden/unchanged), word-wrapped layout, karaoke fill via clipped highlight, spring-damper scroll

## Requirements

- Python 3.10+
- Windows (global hotkeys use Windows `RegisterHotKey` API; the overlay itself is cross-platform)
- Spotify Premium (required for the Web API playback endpoint)

## License

MIT
