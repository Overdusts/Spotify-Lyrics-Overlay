# Spotify Lyrics Overlay

A transparent, always-on-top desktop overlay that displays synced lyrics from Spotify with smooth word-by-word pop animations. Sits quietly at the top of your screen so you can read lyrics while you work — no window switching needed.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15+-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)

## Features

- **Word-by-word animation** — words pop in with bounce easing and a green glow as the song plays
- **Fully transparent** — no background, just floating text with a subtle outline for readability
- **Click-through** — clicks pass right through the overlay to whatever's behind it
- **Synced lyrics** — fetches timed lyrics from [LRCLIB](https://lrclib.net) (free, no API key needed)
- **Spotify integration** — polls your current playback via Spotify Web API with interpolated timing
- **Customizable** — font, size, colors, opacity, position, width — all from a settings dialog
- **System tray** — runs in the background with a tray icon for quick access to settings

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

On first launch, a settings dialog will ask for your Spotify credentials. After saving, your browser will open for Spotify authorization. Once approved, the lyrics overlay appears on screen.

## Configuration

Right-click the system tray icon → **Settings** to customize:

| Setting | Description |
|---|---|
| Font & Size | Any system font, 10-60px |
| Highlight Color | Color for the active word (default: Spotify green) |
| Text Color | Color for upcoming/past words |
| Background Opacity | 0% (invisible) to 100% |
| Width | Overlay width as % of screen |
| Visible Lines | Number of lyric lines shown |
| Click-through | Toggle mouse passthrough |
| Bold | Bold the current line |

Settings are saved to `settings.json` (gitignored to protect credentials).

## How It Works

1. **Spotify Poller** — polls the Spotify Web API every 3s for current track and playback position, interpolates between polls for smooth timing
2. **Lyrics Fetcher** — queries LRCLIB by track name, artist, and duration for synced LRC lyrics
3. **Sync Engine** — binary searches timed lyrics to find the current line based on playback position
4. **Overlay** — renders words with QPainterPath, applies scale transforms with `ease_out_back` for the pop effect, adds glow strokes on the active word

## Requirements

- Python 3.10+
- Windows (uses PyQt5 window flags for transparency and always-on-top)
- Spotify Premium (required for the Web API playback endpoint)

## License

MIT
