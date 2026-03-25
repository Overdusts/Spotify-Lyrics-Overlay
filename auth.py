import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from config import CONFIG_DIR

SCOPES = "user-read-currently-playing user-read-playback-state"


def get_spotify_client(client_id, client_secret, redirect_uri):
    cache_path = os.path.join(CONFIG_DIR, ".spotify_cache")
    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        cache_path=cache_path,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=sp_oauth)
