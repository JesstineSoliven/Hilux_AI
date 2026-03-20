"""
stt_tool.py — Speech-to-text engine for RoadMate AI.

Offline mode: Vosk (fast, private, no internet needed).
Online mode: Google Speech Recognition via SpeechRecognition library.

Falls back gracefully: offline → online → error message.

Single responsibility: capture microphone audio and return transcript text.
"""

import os
import sys
import logging
import io
from pathlib import Path

logger = logging.getLogger(__name__)

VOSK_MODEL_PATH = os.environ.get(
    "VOSK_MODEL_PATH",
    str(Path(__file__).resolve().parent.parent / "models" / "vosk-model-small-en-us"),
)
PREFER_OFFLINE = os.environ.get("STT_PREFER_OFFLINE", "true").lower() == "true"
CAPTURE_DURATION = int(os.environ.get("STT_CAPTURE_DURATION", 8))   # Longer window catches full utterances
SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", 16000))
DEVICE_INDEX = int(os.environ.get("AUDIO_INPUT_DEVICE_INDEX", 0)) or None
STT_LANGUAGE = os.environ.get("STT_LANGUAGE", "en-AU")              # Set accent/language for Google STT
RECALIBRATE_EVERY = int(os.environ.get("STT_RECALIBRATE_EVERY", 15)) # Recalibrate mic every N captures

_vosk_model = None
_vosk_available = None

# Persistent recognizer — keeps calibration state across calls
_recognizer = None
_capture_count = 0


def _get_vosk_model():
    """Lazy-load and cache the Vosk model."""
    global _vosk_model, _vosk_available
    if _vosk_available is not None:
        return _vosk_model

    model_path = Path(VOSK_MODEL_PATH)
    if not model_path.exists():
        logger.warning(
            f"Vosk model not found at {model_path}. "
            "Download from https://alphacephei.com/vosk/models "
            "and extract to models/vosk-model-small-en-us/"
        )
        _vosk_available = False
        return None

    try:
        from vosk import Model
        _vosk_model = Model(str(model_path))
        _vosk_available = True
        logger.info("Vosk model loaded successfully.")
        return _vosk_model
    except ImportError:
        logger.warning("vosk package not installed. Run: pip install vosk")
        _vosk_available = False
        return None
    except Exception as e:
        logger.error(f"Failed to load Vosk model: {e}")
        _vosk_available = False
        return None


def _get_recognizer():
    """Return (or create) the module-level recognizer with good defaults."""
    global _recognizer
    if _recognizer is None:
        try:
            import speech_recognition as sr
        except ImportError:
            raise RuntimeError("SpeechRecognition not installed. Run: pip install SpeechRecognition")
        _recognizer = sr.Recognizer()
        _recognizer.pause_threshold = 1.8          # Wait longer — don't cut off mid-sentence
        _recognizer.non_speaking_duration = 0.5    # Slightly longer trailing silence tolerance
        _recognizer.dynamic_energy_threshold = True
        _recognizer.energy_threshold = 300         # Starting point; calibration will tune it
        _recognizer.dynamic_energy_adjustment_damping = 0.12  # Smoother adaptation
        _recognizer.dynamic_energy_ratio = 1.3     # More sensitive to quiet voices
    return _recognizer


def capture_audio(duration_seconds: int = None) -> bytes:
    """
    Capture audio from the microphone and return raw WAV bytes.

    Args:
        duration_seconds: Recording length. Defaults to STT_CAPTURE_DURATION env var.

    Returns:
        Raw audio bytes in WAV format.
    """
    global _capture_count
    duration = duration_seconds or CAPTURE_DURATION

    try:
        import speech_recognition as sr
    except ImportError:
        raise RuntimeError("SpeechRecognition not installed. Run: pip install SpeechRecognition")

    r = _get_recognizer()

    with sr.Microphone(device_index=DEVICE_INDEX, sample_rate=SAMPLE_RATE) as source:
        # Calibrate on first call and periodically to adapt to changing environments
        if _capture_count == 0 or _capture_count % RECALIBRATE_EVERY == 0:
            logger.debug("Calibrating for ambient noise (1.5s)...")
            r.adjust_for_ambient_noise(source, duration=1.5)
            logger.debug(f"Energy threshold after calibration: {r.energy_threshold:.0f}")
        _capture_count += 1

        logger.debug(f"Listening for up to {duration}s (threshold: {r.energy_threshold:.0f})...")
        try:
            # phrase_time_limit > duration so we never hard-cut a sentence
            audio = r.listen(source, timeout=duration, phrase_time_limit=duration + 3)
            return audio.get_wav_data()
        except sr.WaitTimeoutError:
            logger.debug("No speech detected within timeout.")
            return b""


def transcribe_offline(audio_bytes: bytes) -> str:
    """
    Transcribe audio using Vosk (offline).

    Returns:
        Transcript string, or empty string on failure.
    """
    if not audio_bytes:
        return ""

    model = _get_vosk_model()
    if model is None:
        return ""

    try:
        import json
        import wave
        from vosk import KaldiRecognizer

        # Vosk needs raw 16-bit PCM — parse the WAV
        with io.BytesIO(audio_bytes) as wav_io:
            with wave.open(wav_io, "rb") as wf:
                sample_rate = wf.getframerate()
                rec = KaldiRecognizer(model, sample_rate)
                rec.SetWords(False)

                data = wf.readframes(wf.getnframes())
                rec.AcceptWaveform(data)
                result = json.loads(rec.FinalResult())
                transcript = result.get("text", "").strip()
                logger.debug(f"Vosk transcript: '{transcript}'")
                return transcript

    except Exception as e:
        logger.error(f"Vosk transcription error: {e}")
        return ""


def transcribe_online(audio_bytes: bytes) -> str:
    """
    Transcribe audio using Google Speech Recognition (requires internet).

    Returns:
        Transcript string, or empty string on failure.
    """
    if not audio_bytes:
        return ""

    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        audio = sr.AudioData(audio_bytes, SAMPLE_RATE, 2)
        # Language hint improves accuracy for regional accents
        transcript = r.recognize_google(audio, language=STT_LANGUAGE)
        logger.debug(f"Google STT transcript: '{transcript}'")
        return transcript
    except Exception as e:
        logger.warning(f"Google STT failed: {e}")
        return ""


def transcribe(audio_bytes: bytes, prefer_offline: bool = None) -> str:
    """
    Transcribe audio using the preferred engine, with automatic fallback.

    Args:
        audio_bytes: Raw WAV audio bytes.
        prefer_offline: Override for PREFER_OFFLINE env setting.

    Returns:
        Transcript string, or empty string if both engines fail.
    """
    if not audio_bytes:
        return ""

    use_offline = prefer_offline if prefer_offline is not None else PREFER_OFFLINE

    if use_offline:
        result = transcribe_offline(audio_bytes)
        if result:
            return result
        logger.info("Offline STT returned empty result, trying online...")
        return transcribe_online(audio_bytes)
    else:
        result = transcribe_online(audio_bytes)
        if result:
            return result
        logger.info("Online STT failed, trying offline...")
        return transcribe_offline(audio_bytes)


def list_microphones():
    """Print available audio input devices (useful for AUDIO_INPUT_DEVICE_INDEX config)."""
    try:
        import speech_recognition as sr
        for i, name in enumerate(sr.Microphone.list_microphone_names()):
            print(f"  [{i}] {name}")
    except ImportError:
        print("SpeechRecognition not installed.")


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.DEBUG)

    if "--list-devices" in sys.argv:
        print("Available microphones:")
        list_microphones()
        sys.exit(0)

    print("=== stt_tool self-test ===")
    print(f"Vosk model path: {VOSK_MODEL_PATH}")
    print(f"Prefer offline: {PREFER_OFFLINE}")
    print(f"Capture duration: {CAPTURE_DURATION}s")
    print()
    print("Speak something into your microphone now...")

    audio = capture_audio(duration_seconds=6)
    if not audio:
        print("No audio captured.")
    else:
        print(f"Captured {len(audio)} bytes of audio.")
        text = transcribe(audio)
        print(f"\nTranscript: '{text}'")

    print("=== stt_tool self-test complete ===")
