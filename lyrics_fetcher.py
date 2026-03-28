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


def _normalize(s):
    """Lowercase and strip extra whitespace for comparison."""
    return " ".join(s.lower().split())


def _artist_match(api_artist, target_artist):
    """Check if any of the target artists appear in the API result artist."""
    api_norm = _normalize(api_artist or "")
    target_norm = _normalize(target_artist or "")
    if not api_norm or not target_norm:
        return False
    # Exact match
    if api_norm == target_norm:
        return True
    # Check if any individual artist from Spotify is in the result
    for part in target_norm.split(","):
        part = part.strip()
        if part and part in api_norm:
            return True
    return False


def _extract_synced(result):
    """Try to extract synced lyrics from a result, fall back to plain."""
    if result.synced_lyrics:
        parsed = parse_lrc(result.synced_lyrics)
        if parsed:
            return parsed
    if result.plain_lyrics:
        return [(None, l.strip()) for l in result.plain_lyrics.splitlines() if l.strip()]
    return None


def fetch_lyrics(track_name, artist_name, duration_s=None, album_name=None):
    """Fetch synced lyrics from LRCLIB. Returns list of (ms, text) or None."""
    key = (track_name.lower(), artist_name.lower())
    if key in _cache:
        return _cache[key]

    # 1) Try exact get_lyrics (most accurate — matches by name+artist+album+duration)
    if duration_s is not None:
        try:
            result = _api.get_lyrics(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name or "",
                duration=int(duration_s),
            )
            if result and (result.synced_lyrics or result.plain_lyrics):
                lyrics = _extract_synced(result)
                if lyrics:
                    _cache[key] = lyrics
                    return lyrics
        except Exception:
            pass

    # 2) Search with all available info, pick best match by artist
    try:
        kwargs = {"track_name": track_name, "artist_name": artist_name}
        if duration_s is not None:
            kwargs["duration"] = int(duration_s)
        results = _api.search_lyrics(**kwargs)
        if results:
            # Prefer results where artist actually matches
            for r in results:
                if _artist_match(r.artist_name, artist_name):
                    lyrics = _extract_synced(r)
                    if lyrics:
                        _cache[key] = lyrics
                        return lyrics
    except Exception:
        pass

    # 3) Broader search by track name only — but ONLY accept if artist matches
    try:
        results = _api.search_lyrics(track_name=track_name)
        if results:
            for r in results:
                if _artist_match(r.artist_name, artist_name):
                    lyrics = _extract_synced(r)
                    if lyrics:
                        _cache[key] = lyrics
                        return lyrics
    except Exception:
        pass

    _cache[key] = None
    return None
