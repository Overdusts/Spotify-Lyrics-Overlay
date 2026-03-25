import re
from lrclib import LrcLibAPI

_api = LrcLibAPI(user_agent="SpotifyLyricsOverlay/1.0")
_cache = {}


def parse_lrc(lrc_text):
    """Parse LRC formatted text into list of (ms, line_text)."""
    lines = []
    for raw in lrc_text.strip().splitlines():
        m = re.match(r"\[(\d+):(\d+)\.(\d+)\]\s*(.*)", raw)
        if m:
            mins, secs, centis, text = m.groups()
            ms = int(mins) * 60000 + int(secs) * 1000 + int(centis) * 10
            lines.append((ms, text.strip()))
    lines.sort(key=lambda x: x[0])
    return lines


def fetch_lyrics(track_name, artist_name, duration_s=None):
    """Fetch synced lyrics from LRCLIB. Returns list of (ms, text) or None."""
    key = (track_name.lower(), artist_name.lower())
    if key in _cache:
        return _cache[key]

    result = None
    try:
        kwargs = {"track_name": track_name, "artist_name": artist_name}
        if duration_s is not None:
            kwargs["duration"] = int(duration_s)
        results = _api.search_lyrics(**kwargs)
        if results:
            result = results[0]
    except Exception:
        pass

    if result is None:
        try:
            results = _api.search_lyrics(track_name=track_name)
            if results:
                artist_lower = artist_name.lower()
                for r in results:
                    if artist_lower in (r.artist_name or "").lower():
                        result = r
                        break
                if result is None:
                    result = results[0]
        except Exception:
            pass

    if result is None:
        _cache[key] = None
        return None

    if result.synced_lyrics:
        parsed = parse_lrc(result.synced_lyrics)
        if parsed:
            _cache[key] = parsed
            return parsed

    # Fall back to plain lyrics (no timing)
    if result.plain_lyrics:
        lines = [(None, l.strip()) for l in result.plain_lyrics.splitlines() if l.strip()]
        _cache[key] = lines
        return lines

    _cache[key] = None
    return None
