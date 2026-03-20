"""
music_tool.py — Spotify music control for RoadMate AI.

Handles music playback, pause, skip, and volume via the Spotify Web API.
Requires Spotify Premium for playback control.

Required .env keys:
    SPOTIFY_CLIENT_ID      — from developer.spotify.com
    SPOTIFY_CLIENT_SECRET  — from developer.spotify.com
    SPOTIFY_REDIRECT_URI   — default: http://localhost:8888/callback
    SPOTIFY_DEVICE_ID      — optional, auto-detected if blank
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_spotify_client = None


def _get_client():
    global _spotify_client
    if _spotify_client is None:
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
        except ImportError:
            raise RuntimeError("spotipy not installed. Run: pip install spotipy")

        client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

        if not client_id or client_id.startswith("YOUR_"):
            raise ValueError(
                "SPOTIFY_CLIENT_ID is not configured. "
                "Add it to .env — get credentials at developer.spotify.com"
            )
        if not client_secret or client_secret.startswith("YOUR_"):
            raise ValueError(
                "SPOTIFY_CLIENT_SECRET is not configured. "
                "Add it to .env — get credentials at developer.spotify.com"
            )

        scope = (
            "user-modify-playback-state "
            "user-read-playback-state "
            "user-read-currently-playing"
        )

        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=".tmp/.spotify_cache",
            open_browser=True,
        )
        _spotify_client = spotipy.Spotify(auth_manager=auth_manager)

    return _spotify_client


def _get_device_id() -> Optional[str]:
    """Return device ID from env or first available Spotify device."""
    fixed = os.environ.get("SPOTIFY_DEVICE_ID", "")
    if fixed:
        return fixed

    sp = _get_client()
    data = sp.devices()
    devices = data.get("devices", [])
    if not devices:
        raise RuntimeError(
            "No active Spotify device found. "
            "Open Spotify on your phone or computer first, then try again."
        )
    for d in devices:
        if d.get("is_active"):
            return d["id"]
    return devices[0]["id"]


def play_query(query: str) -> str:
    """
    Search Spotify and play the best match (track, then playlist).
    Returns a human-readable description of what started playing.
    Raises RuntimeError on device or auth issues.
    """
    sp = _get_client()
    device_id = _get_device_id()

    results = sp.search(q=query, limit=3, type="track,playlist")

    # Prefer a matching track
    tracks = results.get("tracks", {}).get("items", [])
    if tracks:
        track = tracks[0]
        sp.start_playback(device_id=device_id, uris=[track["uri"]])
        artist = track["artists"][0]["name"]
        return f"{track['name']} by {artist}"

    # Fall back to playlist
    playlists = results.get("playlists", {}).get("items", [])
    if playlists:
        pl = playlists[0]
        sp.start_playback(device_id=device_id, context_uri=pl["uri"])
        return f"{pl['name']} playlist"

    return ""


def play_artist(artist: str) -> str:
    """
    Find an artist on Spotify and start playing their discography.
    Returns the matched artist name or empty string if not found.
    """
    sp = _get_client()
    device_id = _get_device_id()

    results = sp.search(q=f"artist:{artist}", limit=1, type="artist")
    items = results.get("artists", {}).get("items", [])
    if not items:
        return ""

    found = items[0]
    sp.start_playback(device_id=device_id, context_uri=found["uri"])
    return found["name"]


def pause() -> bool:
    """Pause current playback. Returns True on success."""
    try:
        _get_client().pause_playback()
        return True
    except Exception as e:
        logger.warning(f"Pause failed: {e}")
        return False


def resume() -> bool:
    """Resume paused playback. Returns True on success."""
    try:
        device_id = _get_device_id()
        _get_client().start_playback(device_id=device_id)
        return True
    except Exception as e:
        logger.warning(f"Resume failed: {e}")
        return False


def next_track() -> bool:
    """Skip to next track. Returns True on success."""
    try:
        device_id = _get_device_id()
        _get_client().next_track(device_id=device_id)
        return True
    except Exception as e:
        logger.warning(f"Next track failed: {e}")
        return False


def previous_track() -> bool:
    """Go back to previous track. Returns True on success."""
    try:
        device_id = _get_device_id()
        _get_client().previous_track(device_id=device_id)
        return True
    except Exception as e:
        logger.warning(f"Previous track failed: {e}")
        return False


def get_current_track() -> Optional[dict]:
    """
    Return info about the currently playing track.
    Returns dict with 'name', 'artist', 'is_playing', or None if nothing is playing.
    """
    try:
        current = _get_client().currently_playing()
        if not current or not current.get("item"):
            return None
        item = current["item"]
        return {
            "name": item["name"],
            "artist": item["artists"][0]["name"],
            "is_playing": current.get("is_playing", False),
        }
    except Exception as e:
        logger.warning(f"Get current track failed: {e}")
        return None


def set_volume(percent: int) -> bool:
    """
    Set Spotify playback volume (0–100).
    Returns True on success.
    """
    try:
        percent = max(0, min(100, int(percent)))
        device_id = _get_device_id()
        _get_client().volume(percent, device_id=device_id)
        return True
    except Exception as e:
        logger.warning(f"Set volume failed: {e}")
        return False
