import hashlib
import json
import os
import re
import time
from lrclib import LrcLibAPI

from config import CACHE_DIR

_api = LrcLibAPI(user_agent="SpotifyLyricsOverlay/1.0")
_memory_cache = {}


# Sentinel values stored in the cache so we can distinguish states
CACHE_INSTRUMENTAL = "__INSTRUMENTAL__"
CACHE_NOT_FOUND = "__NOT_FOUND__"


def _cache_key(track_name, artist_name):
    raw = f"{track_name.strip().lower()}||{artist_name.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")


def _load_from_disk(key):
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Refresh negative cache after 7 days (track might have lyrics now)
        if data.get("status") in ("not_found", "instrumental"):
            age = time.time() - data.get("ts", 0)
            if age > 7 * 86400:
                return None
        return data
    except Exception:
        return None


def _save_to_disk(key, payload):
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


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
    return " ".join(s.lower().split())


def _artist_match(api_artist, target_artist):
    """Check if artist names match, with word-boundary awareness."""
    api_norm = _normalize(api_artist or "")
    target_norm = _normalize(target_artist or "")
    if not api_norm or not target_norm:
        return False
    if api_norm == target_norm:
        return True
    # Check each individual artist from target (Spotify sends comma-separated)
    target_parts = [p.strip() for p in re.split(r"[,&]", target_norm) if p.strip()]
    api_parts = [p.strip() for p in re.split(r"[,&]", api_norm) if p.strip()]
    for t in target_parts:
        # Require word boundary matching to avoid "beat" matching "beats"
        # Use full-token match only
        if t in api_parts:
            return True
        # Also check if the full normalized target appears as a substring
        # bounded by word boundaries
        pattern = r"\b" + re.escape(t) + r"\b"
        if re.search(pattern, api_norm):
            return True
    return False


def _is_instrumental_result(result):
    """LRCLIB marks some tracks as instrumental."""
    try:
        if getattr(result, "instrumental", False):
            return True
    except Exception:
        pass
    # Heuristic: empty lyrics explicitly means instrumental
    if result and not result.synced_lyrics and not result.plain_lyrics:
        return True
    return False


def _extract_synced(result):
    if result.synced_lyrics:
        parsed = parse_lrc(result.synced_lyrics)
        if parsed:
            return parsed
    if result.plain_lyrics:
        return [(None, l.strip()) for l in result.plain_lyrics.splitlines() if l.strip()]
    return None


def _with_retry(fn, attempts=2, backoff=0.5):
    """Run an API call with limited retries on transient errors."""
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(backoff * (i + 1))
    raise last_exc if last_exc else Exception("fetch failed")


def fetch_lyrics(track_name, artist_name, duration_s=None, album_name=None):
    """Fetch synced lyrics. Returns:
       - list[(ms, text)] if found
       - 'INSTRUMENTAL' string if track is instrumental
       - None if no match found
    """
    key = _cache_key(track_name, artist_name)

    # 1) Memory cache
    if key in _memory_cache:
        return _memory_cache[key]

    # 2) Disk cache
    disk = _load_from_disk(key)
    if disk:
        status = disk.get("status")
        if status == "found":
            result = [(t[0], t[1]) for t in disk["lines"]]
            _memory_cache[key] = result
            return result
        elif status == "instrumental":
            _memory_cache[key] = CACHE_INSTRUMENTAL
            return CACHE_INSTRUMENTAL
        elif status == "not_found":
            _memory_cache[key] = None
            return None

    # 3) Try exact get_lyrics first (most accurate)
    result = None
    if duration_s is not None:
        try:
            result = _with_retry(lambda: _api.get_lyrics(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name or "",
                duration=int(duration_s),
            ))
        except Exception:
            result = None

        if result:
            if _is_instrumental_result(result):
                _memory_cache[key] = CACHE_INSTRUMENTAL
                _save_to_disk(key, {"status": "instrumental", "ts": time.time()})
                return CACHE_INSTRUMENTAL
            lyrics = _extract_synced(result)
            if lyrics:
                _memory_cache[key] = lyrics
                _save_to_disk(key, {"status": "found", "lines": lyrics, "ts": time.time()})
                return lyrics

    # 4) Search with full info, pick best artist match
    try:
        kwargs = {"track_name": track_name, "artist_name": artist_name}
        if duration_s is not None:
            kwargs["duration"] = int(duration_s)
        results = _with_retry(lambda: _api.search_lyrics(**kwargs)) or []
        for r in results:
            if _artist_match(r.artist_name, artist_name):
                if _is_instrumental_result(r):
                    _memory_cache[key] = CACHE_INSTRUMENTAL
                    _save_to_disk(key, {"status": "instrumental", "ts": time.time()})
                    return CACHE_INSTRUMENTAL
                lyrics = _extract_synced(r)
                if lyrics:
                    _memory_cache[key] = lyrics
                    _save_to_disk(key, {"status": "found", "lines": lyrics, "ts": time.time()})
                    return lyrics
    except Exception:
        pass

    # 5) Broader search by track name only, require artist match
    try:
        results = _with_retry(lambda: _api.search_lyrics(track_name=track_name)) or []
        for r in results:
            if _artist_match(r.artist_name, artist_name):
                if _is_instrumental_result(r):
                    _memory_cache[key] = CACHE_INSTRUMENTAL
                    _save_to_disk(key, {"status": "instrumental", "ts": time.time()})
                    return CACHE_INSTRUMENTAL
                lyrics = _extract_synced(r)
                if lyrics:
                    _memory_cache[key] = lyrics
                    _save_to_disk(key, {"status": "found", "lines": lyrics, "ts": time.time()})
                    return lyrics
    except Exception:
        pass

    # Not found
    _memory_cache[key] = None
    _save_to_disk(key, {"status": "not_found", "ts": time.time()})
    return None
