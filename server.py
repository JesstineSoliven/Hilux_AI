"""
server.py — RoadMate AI Web Server

FastAPI backend that powers the mobile PWA.
Browser handles STT/TTS — backend handles AI, weather, maps, reminders.

Usage:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import io
import base64
import asyncio
import random
import logging
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Tools ─────────────────────────────────────────────────────────────────────
from tools import memory_tool, driving_mode_tool, claude_tool, intent_tool
from tools import weather_tool, maps_tool, reminder_tool
from tools.intent_tool import extract_reminder_text, extract_destination

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RoadMate.Server")

# ─── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="RoadMate AI", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Session store (single-user, in-memory) ────────────────────────────────────
_profile = memory_tool.load_user_profile()
_history: list = []
MAX_HISTORY = 12  # messages (6 turns)

_SAFETY_PHRASES = [
    "falling asleep", "can't keep my eyes open", "cant keep my eyes open",
    "about to pass out", "extremely exhausted", "falling asleep at the wheel",
]


# ─── Request model ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str


# ─── Audio generation (edge-tts → base64 MP3) ─────────────────────────────────
async def _generate_audio(text: str) -> str:
    """Generate speech with edge-tts and return as base64 MP3. Empty string on failure."""
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
        if not raw:
            return ""
        return base64.b64encode(raw).decode("utf-8")
    except Exception as e:
        logger.warning(f"edge-tts audio generation failed: {e}")
        return ""


# ─── Main chat endpoint ────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    global _history

    transcript = req.message.strip()
    if not transcript:
        return {"response": "I didn't catch that. Try again.", "intent": "empty", "audio": ""}

    logger.info(f"Input: '{transcript}'")

    # Safety override
    norm = transcript.lower()
    if any(p in norm for p in _SAFETY_PHRASES):
        msg = "Please pull over somewhere safe right now. Your safety matters more than arriving on time."
        audio = await _generate_audio(msg)
        return {"response": msg, "intent": "safety", "audio": audio}

    # Classify
    result = intent_tool.classify_intent(transcript)
    intent = result["intent"]
    logger.info(f"Intent: {intent}")

    try:
        response = _route(intent, transcript)
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        err = str(e).lower()
        if "credit" in err or "balance" in err:
            response = "My AI brain needs credits. Please top up the Anthropic API."
        else:
            response = "Something went wrong. Ask me again."

    audio = await _generate_audio(response)

    _history.append({"role": "user",      "content": transcript})
    _history.append({"role": "assistant", "content": response})
    _history = _history[-MAX_HISTORY:]

    return {"response": response, "intent": intent, "audio": audio}


# ─── Status ────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    return {
        "status": "online",
        "name": _profile.get("name", "Jess"),
        "city": _profile.get("default_city", "Manila"),
        "model": os.environ.get("CLAUDE_MODEL", "unknown"),
        "driving_mode": driving_mode_tool.is_driving_mode_active(),
    }


# ─── Intent router ─────────────────────────────────────────────────────────────
def _route(intent: str, transcript: str) -> str:
    driving = driving_mode_tool.is_driving_mode_active()
    history = _history[-MAX_HISTORY:]

    if intent == "weather":
        city = _profile.get("default_city", "Manila")
        data = weather_tool.get_current_weather(city)
        speech = weather_tool.format_for_speech(data, driving_mode=driving)
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving)
        return claude_tool.get_response(
            f"{transcript}. Weather info: {speech}", system, history, driving_mode=driving
        )

    elif intent == "navigation":
        saved = _profile.get("saved_locations", {})
        dest = extract_destination(transcript, saved) or transcript
        origin = _profile.get("default_city", "Manila")
        data = maps_tool.get_travel_time(origin, dest)
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
            "\n\nJOKE MODE: Tell one genuinely funny, original joke. "
            "Setup then punchline. No emojis. No lists. Just the joke."
        )
        return claude_tool.get_response("Tell me a great joke.", system, [], max_tokens=150)

    elif intent == "fun_fact":
        topics = [
            "the Toyota Hilux and why it's legendary",
            "the Philippines",
            "space and the universe",
            "human psychology",
            "bizarre world records",
            "cars and automotive history",
            "animals doing surprising things",
        ]
        topic = random.choice(topics)
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nFUN FACT MODE: Share one truly surprising fact about {topic} "
            "in 2-3 sentences. No 'Did you know' intro. Just the fact."
        )
        return claude_tool.get_response(f"Give me a fascinating fact about {topic}.", system, [], max_tokens=150)

    elif intent == "trivia":
        cats = ["cars and motorsport", "geography", "science", "movies and pop culture", "history", "sports"]
        cat = random.choice(cats)
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nTRIVIA MODE: Ask one {cat} trivia question. "
            "Question only — do NOT reveal the answer. End with 'What's your answer?'"
        )
        return claude_tool.get_response(f"Give me a {cat} trivia question.", system, [], max_tokens=80)

    elif intent == "roast":
        vehicle = _profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car = f"Toyota {vehicle.get('model', 'Hilux')}"
        name = _profile.get("name", "Jess")
        city = _profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nROAST MODE: Give {name} a short playful witty roast. "
            f"They drive a {car} in {city}. Clever and funny, not mean. 2-3 sentences max."
        )
        return claude_tool.get_response(f"Roast me, I'm {name} and I drive a {car}.", system, [], max_tokens=120)

    elif intent == "rap":
        vehicle = _profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car = f"Toyota {vehicle.get('model', 'Hilux')}"
        city = _profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(_profile) + (
            f"\n\nRAP MODE: Write an original 8-12 line rap verse about {car} in {city}. "
            "Make it flow with rhymes. Keep it cool and real."
        )
        return claude_tool.get_response(f"Freestyle rap about my {car}.", system, [], max_tokens=250)

    elif intent == "riddle":
        system = claude_tool.build_system_prompt(_profile) + (
            "\n\nRIDDLE MODE: Give one clever riddle. State the riddle only — "
            "do NOT give the answer. End with 'What am I?' or 'What is it?'"
        )
        return claude_tool.get_response("Give me a riddle.", system, [], max_tokens=80)

    elif intent == "nearby":
        city = _profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving) + (
            f"\n\nNEARBY MODE: User is near {city}. Give 2-3 practical, specific suggestions. "
            f"Reference real areas or place types in {city}."
        )
        return claude_tool.get_response(transcript, system, history[-4:], driving_mode=driving, max_tokens=180)

    else:
        system = claude_tool.build_system_prompt(_profile, driving_mode=driving)
        return claude_tool.get_response(transcript, system, history, driving_mode=driving)


# ─── Serve frontend (must be last) ─────────────────────────────────────────────
# Prefer public/ (Vercel convention), fall back to frontend/
_frontend = Path(__file__).resolve().parent / "public"
if not _frontend.exists():
    _frontend = Path(__file__).resolve().parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


# ─── Dev runner ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting RoadMate server on port {port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
