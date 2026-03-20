"""
tts_tool.py — Text-to-speech engine for RoadMate AI.

Primary: edge-tts (Microsoft Neural voices, free, requires internet).
Fallback: pyttsx3 (offline, robotic but functional).

Includes async and sync speak functions, plus stop/interrupt support.

Single responsibility: convert text to audible speech.
"""

import os
import sys
import asyncio
import logging
import threading
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "en-AU-NatashaNeural")
TTS_FALLBACK = os.environ.get("TTS_FALLBACK_ENGINE", "pyttsx3")

_speak_lock = threading.Lock()
_stop_flag = threading.Event()
_pyttsx3_engine = None


# ─── edge-tts (primary) ────────────────────────────────────────────────────────

async def _edge_tts_speak_async(text: str, voice: str):
    """Generate audio with edge-tts and play via pygame — fully in-memory (no temp file)."""
    try:
        import edge_tts
        import pygame
        import io
    except ImportError as e:
        raise RuntimeError(f"Missing dependency: {e}. Run: pip install edge-tts pygame")

    # Stream all audio chunks into a memory buffer — no disk I/O
    audio_buffer = io.BytesIO()
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.write(chunk["data"])

    audio_buffer.seek(0)
    if audio_buffer.getbuffer().nbytes == 0:
        return  # Nothing generated

    # Init pygame once and reuse
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=24000)

    pygame.mixer.music.load(audio_buffer)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        if _stop_flag.is_set():
            pygame.mixer.music.stop()
            break
        await asyncio.sleep(0.05)


def _speak_edge_tts(text: str):
    """Synchronously run edge-tts speech."""
    voice = TTS_VOICE
    try:
        asyncio.run(_edge_tts_speak_async(text, voice))
    except Exception as e:
        logger.error(f"edge-tts error: {e}")
        raise


# ─── pyttsx3 (fallback) ────────────────────────────────────────────────────────

def _get_pyttsx3_engine():
    global _pyttsx3_engine
    if _pyttsx3_engine is None:
        try:
            import pyttsx3
            _pyttsx3_engine = pyttsx3.init()
            _pyttsx3_engine.setProperty("rate", 165)  # Slightly slower for clarity
            _pyttsx3_engine.setProperty("volume", 1.0)
        except ImportError:
            raise RuntimeError("pyttsx3 not installed. Run: pip install pyttsx3")
    return _pyttsx3_engine


def _speak_pyttsx3(text: str):
    engine = _get_pyttsx3_engine()
    engine.say(text)
    engine.runAndWait()


# ─── Public API ────────────────────────────────────────────────────────────────

def speak(text: str):
    """
    Speak text synchronously. Blocks until speech is complete.
    Tries edge-tts first, falls back to pyttsx3.
    """
    if not text or not text.strip():
        return

    _stop_flag.clear()

    with _speak_lock:
        engine = TTS_ENGINE.lower()

        if engine == "edge-tts":
            try:
                _speak_edge_tts(text)
                return
            except Exception as e:
                logger.warning(f"edge-tts failed ({e}), falling back to pyttsx3")

        # Fallback / direct pyttsx3 use
        try:
            _speak_pyttsx3(text)
        except Exception as e:
            logger.error(f"pyttsx3 also failed: {e}")
            print(f"[RoadMate TTS]: {text}")  # Last resort: print to console


def speak_async(text: str):
    """
    Speak text in a background thread (non-blocking).
    Returns the thread object — call .join() if you need to wait.
    """
    t = threading.Thread(target=speak, args=(text,), daemon=True)
    t.start()
    return t


def stop_speaking():
    """
    Signal current speech to stop (barge-in / interrupt).
    Works with edge-tts pygame playback. pyttsx3 stop is best-effort.
    """
    _stop_flag.set()
    try:
        import pygame
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception:
        pass

    # pyttsx3 stop (best effort)
    global _pyttsx3_engine
    if _pyttsx3_engine:
        try:
            _pyttsx3_engine.stop()
        except Exception:
            pass

    logger.debug("Speech stopped.")


def list_voices():
    """List available pyttsx3 voices (useful for configuration)."""
    engine = _get_pyttsx3_engine()
    voices = engine.getProperty("voices")
    for v in voices:
        print(f"  ID: {v.id}\n  Name: {v.name}\n  Lang: {v.languages}\n")


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.DEBUG)

    print("=== tts_tool self-test ===")

    if "--list-voices" in sys.argv:
        print("Available pyttsx3 voices:")
        list_voices()
        sys.exit(0)

    test_text = (
        "Hey Jess, RoadMate is online and ready. "
        "Your driving companion is here to help."
    )
    print(f"Speaking: '{test_text}'")
    print(f"Engine: {TTS_ENGINE}, Voice: {TTS_VOICE}")

    speak(test_text)
    print("=== tts_tool self-test complete ===")
