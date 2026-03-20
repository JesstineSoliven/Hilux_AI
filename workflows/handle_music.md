# Workflow: Handle Music Playback

**Version:** 1.0
**Trigger Intent:** `music`

---

## Objective

Control Spotify music playback in response to voice commands — play tracks, pause, skip, adjust volume, and report what's currently playing.

---

## Required Configuration

`.env` keys that must be set before this workflow can function:

| Key | Source |
|-----|--------|
| `SPOTIFY_CLIENT_ID` | developer.spotify.com → Create App |
| `SPOTIFY_CLIENT_SECRET` | developer.spotify.com → Create App |
| `SPOTIFY_REDIRECT_URI` | Must match your Spotify app settings (default: `http://localhost:8888/callback`) |
| `SPOTIFY_DEVICE_ID` | Optional — auto-detected from active Spotify session |

**Spotify Premium is required for playback control.**

---

## First-Time Setup

1. Go to [developer.spotify.com](https://developer.spotify.com) and log in
2. Click **Create App**
3. Set Redirect URI to: `http://localhost:8888/callback`
4. Copy Client ID and Client Secret into `.env`
5. On first run, a browser window will open to authorize RoadMate
6. After approving, the token is cached at `.tmp/.spotify_cache` for future sessions

---

## Execution Sequence

### Play something
1. Parse query from transcript (strip "play", "put on", "play some", etc.)
2. If query is empty → ask the user what to play
3. Call `music_tool.play_query(query)` → searches tracks then playlists
4. Speak: "Now playing {result}."

### Pause / Stop
1. Call `music_tool.pause()`
2. Speak: "Music paused."

### Resume
1. Call `music_tool.resume()`
2. Speak: "Resuming."

### Skip to next
1. Call `music_tool.next_track()`
2. Speak: "Skipping."

### Go to previous
1. Call `music_tool.previous_track()`
2. Speak: "Going back."

### What's playing
1. Call `music_tool.get_current_track()`
2. Speak: "Playing: {name} by {artist}." or "Nothing is playing."

### Volume control
1. Parse number from transcript, or "up" / "down"
2. Call `music_tool.set_volume(percent)`
3. Speak: "Volume set to {n}." / "Volume up." / "Volume down."

---

## Failure Handling

| Error | Response |
|-------|----------|
| Spotify not configured | Tell user to add credentials to `.env` |
| No active device | Ask user to open Spotify on their device first |
| Spotify Premium required | Inform user Premium is needed |
| Track not found | Say couldn't find it, suggest trying a different search |
| General API error | "Couldn't control Spotify right now. Make sure Spotify is open." |

---

## Example Phrases

- "Play some music"
- "Play Taylor Swift"
- "Play the song Blinding Lights"
- "Play jazz"
- "Pause music"
- "Skip"
- "What's playing?"
- "Volume up"
- "Set volume to 60"
