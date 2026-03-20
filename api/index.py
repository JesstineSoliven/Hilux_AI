"""
api/index.py — RoadMate AI serverless handler for Vercel.

Vercel routes /api/* here. Static frontend is served from /public.
"""

import sys
import os
import io
import base64
import asyncio
import random
from pathlib import Path
from datetime import datetime

# Make project root importable so tools/ resolves correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tools import memory_tool, driving_mode_tool, claude_tool, intent_tool
from tools import weather_tool, maps_tool, reminder_tool
from tools.intent_tool import extract_reminder_text, extract_destination

app = FastAPI(title="RoadMate AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-memory state ───────────────────────────────────────────────────────────
_profile  = memory_tool.load_user_profile()
_history: list = []
MAX_HISTORY = 12

_SAFETY_PHRASES = [
    "falling asleep", "can't keep my eyes open", "cant keep my eyes open",
    "about to pass out", "extremely exhausted",
]


class ChatRequest(BaseModel):
    message: str


async def _generate_audio(text: str) -> str:
    """Generate speech with edge-tts and return as base64 MP3."""
    try:
        import edge_tts
        voice = os.environ.get("TTS_VOICE", "en-AU-NatashaNeural")
        buf = io.BytesIO()
        communicate = edge_tts.Communicate(text, voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        raw = buf.read()
        return base64.b64encode(raw).decode("utf-8") if raw else ""
    except Exception:
        return ""


@app.post("/api/chat")
async def chat(req: ChatRequest):
    global _history

    transcript = req.message.strip()
    if not transcript:
        return {"response": "I didn't catch that. Try again.", "intent": "empty", "audio": ""}

    norm = transcript.lower()
    if any(p in norm for p in _SAFETY_PHRASES):
        msg = "Please pull over somewhere safe right now. Your safety matters more than arriving on time."
        audio = await _generate_audio(msg)
        return {"response": msg, "intent": "safety", "audio": audio}

    result = intent_tool.classify_intent(transcript)
    intent = result["intent"]

    try:
        response = _route(intent, transcript)
    except Exception as e:
        err = str(e).lower()
        if "credit" in err or "balance" in err:
            response = "My AI brain needs credits. Please top up the Anthropic API."
        else:
            response = "Something went wrong. Ask me again."

    audio = await _generate_audio(response)

    _history.append({"role": "user",      "content": transcript})
    _history.append({"role": "assistant", "content": response})
    _history = _history[-MAX_HISTORY:]

    music_query  = ""
    music_action = ""
    if intent == "music":
        norm = transcript.lower()
        if any(w in norm for w in ["pause", "stop music", "stop the music"]):
            music_action = "pause"
        elif any(w in norm for w in ["resume", "unpause", "continue music"]):
            music_action = "resume"
        elif any(w in norm for w in ["next song", "skip", "next track"]):
            music_action = "next"
        elif any(w in norm for w in ["previous", "last song", "go back"]):
            music_action = "previous"
        elif any(w in norm for w in ["volume up", "turn up music"]):
            music_action = "volume_up"
        elif any(w in norm for w in ["volume down", "turn down music"]):
            music_action = "volume_down"
        elif any(w in norm for w in ["what's playing", "whats playing", "currently playing", "what song"]):
            music_action = "current"
        else:
            music_query = _extract_music_query(transcript)

    return {"response": response, "intent": intent, "audio": audio, "music_query": music_query, "music_action": music_action}


@app.get("/api/status")
async def status():
    return {
        "status":            "online",
        "name":              _profile.get("name", "Jess"),
        "city":              _profile.get("default_city", "Manila"),
        "model":             os.environ.get("CLAUDE_MODEL", "unknown"),
        "driving_mode":      driving_mode_tool.is_driving_mode_active(),
        "spotify_client_id": os.environ.get("SPOTIFY_CLIENT_ID", ""),
    }


def _extract_music_query(transcript: str) -> str:
    """Pull the search term out of a music request."""
    norm = transcript.lower()
    for prefix in ["play some ", "play ", "put on ", "queue "]:
        if norm.startswith(prefix):
            return transcript[len(prefix):].strip()
    # Fallback: strip common control words
    for word in ["music", "song", "track", "playlist"]:
        norm = norm.replace(word, "").strip()
    return norm.strip() or "music"


def _handle_music(transcript: str, driving: bool) -> str:
    norm = transcript.lower()
    if any(w in norm for w in ["pause", "stop music", "stop the music"]):
        return "Pausing Spotify."
    if any(w in norm for w in ["resume", "unpause", "continue music"]):
        return "Resuming Spotify."
    if any(w in norm for w in ["next song", "skip", "next track"]):
        return "Skipping to next track."
    if any(w in norm for w in ["previous", "last song", "go back"]):
        return "Going to previous track."
    if any(w in norm for w in ["what's playing", "whats playing", "currently playing", "what song"]):
        return "Check the now playing bar."
    if any(w in norm for w in ["volume up", "turn up music"]):
        return "Turning volume up."
    if any(w in norm for w in ["volume down", "turn down music"]):
        return "Turning volume down."
    query = _extract_music_query(transcript)
    return f"Playing {query} on Spotify."


def _route(intent: str, transcript: str) -> str:
    driving = driving_mode_tool.is_driving_mode_active()
    history = _history[-MAX_HISTORY:]

    if intent == "weather":
        city   = _profile.get("default_city", "Manila")
        data   = weather_tool.get_current_weather(city)
        speech = weather_tool.format_for_speech(data, driving_mode=driving)
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving)
        return claude_tool.get_response(
            f"{transcript}. Weather info: {speech}", system, history, driving_mode=driving
        )

    elif intent == "navigation":
        saved  = _profile.get("saved_locations", {})
        dest   = extract_destination(transcript, saved) or transcript
        origin = _profile.get("default_city", "Manila")
        data   = maps_tool.get_travel_time(origin, dest)
        return maps_tool.format_for_speech(data, driving_mode=driving)

    elif intent == "reminder_set":
        text = extract_reminder_text(transcript)
        if not text or len(text) < 3:
            return "What should I remind you about?"
        reminder_tool.add_reminder(text)
        return f"Got it. I'll remind you to {text}."

    elif intent == "reminder_get":
        reminders = reminder_tool.get_reminders("today")
        return reminder_tool.format_for_speech(reminders, driving_mode=driving)

    elif intent == "music":
        return _handle_music(transcript, driving)

    elif intent == "driving_mode_on":
        driving_mode_tool.enable_driving_mode()
        return "Driving mode on. Short answers activated."

    elif intent == "driving_mode_off":
        driving_mode_tool.disable_driving_mode()
        return "Driving mode off. Full responses are back."

    elif intent == "time_date":
        now = datetime.now()
        return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}."

    elif intent == "joke":
        system = claude_tool.build_system_prompt(_profile) + (
            "\n\nJOKE MODE: Tell one genuinely funny original joke. "
            "Setup then punchline. No emojis. No lists. Just the joke."
        )
        return claude_tool.get_response("Tell me a great joke.", system, [], max_tokens=150)

    elif intent == "fun_fact":
        topics = [
            "the Toyota Hilux and why it's legendary",
            "the Philippines", "space and the universe",
            "human psychology", "bizarre world records",
            "cars and automotive history",
        ]
        topic  = random.choice(topics)
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nFUN FACT MODE: Share one truly surprising fact about {topic} "
            "in 2-3 sentences. No 'Did you know' intro. Just the fact."
        )
        return claude_tool.get_response(f"Give me a fact about {topic}.", system, [], max_tokens=150)

    elif intent == "trivia":
        cats   = ["cars and motorsport", "geography", "science", "movies", "history", "sports"]
        cat    = random.choice(cats)
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nTRIVIA MODE: Ask one {cat} trivia question. "
            "Question only, no answer. End with 'What's your answer?'"
        )
        return claude_tool.get_response(f"Give me a {cat} trivia question.", system, [], max_tokens=80)

    elif intent == "roast":
        vehicle = _profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car     = f"Toyota {vehicle.get('model', 'Hilux')}"
        name    = _profile.get("name", "Jess")
        city    = _profile.get("default_city", "Manila")
        system  = claude_tool.build_system_prompt(_profile) + (
            f"\n\nROAST MODE: Give {name} a short playful witty roast. "
            f"They drive a {car} in {city}. Clever not mean. 2-3 sentences."
        )
        return claude_tool.get_response(f"Roast {name} who drives a {car}.", system, [], max_tokens=120)

    elif intent == "rap":
        vehicle = _profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car     = f"Toyota {vehicle.get('model', 'Hilux')}"
        city    = _profile.get("default_city", "Manila")
        system  = claude_tool.build_system_prompt(_profile) + (
            f"\n\nRAP MODE: Write an original 8-12 line rap about {car} in {city}. "
            "Make it flow with rhymes. Keep it cool."
        )
        return claude_tool.get_response(f"Freestyle rap about my {car}.", system, [], max_tokens=250)

    elif intent == "riddle":
        system = claude_tool.build_system_prompt(_profile) + (
            "\n\nRIDDLE MODE: Give one clever riddle. "
            "Riddle only, no answer. End with 'What am I?'"
        )
        return claude_tool.get_response("Give me a riddle.", system, [], max_tokens=80)

    elif intent == "nearby":
        city   = _profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving) + (
            f"\n\nNEARBY MODE: User is near {city}. Give 2-3 specific suggestions. "
            f"Reference real areas in {city}."
        )
        return claude_tool.get_response(transcript, system, history[-4:], driving_mode=driving, max_tokens=180)

    else:
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving)
        return claude_tool.get_response(transcript, system, history, driving_mode=driving)
