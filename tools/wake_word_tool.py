"""
wake_word_tool.py — Wake word detection for RoadMate AI.

Runs a persistent background thread that keeps the microphone open,
records short audio chunks, and checks for wake phrases via Vosk.

Single responsibility: detect wake phrases and fire a callback.
"""

import os
import sys
import logging
import threading
import time
import io
import wave
import json

logger = logging.getLogger(__name__)

_WAKE_WORDS_ENV = os.environ.get("WAKE_WORDS", "hey roadmate,hi hilux,assistant")
DEFAULT_WAKE_WORDS = [w.strip().lower() for w in _WAKE_WORDS_ENV.split(",")]

_thread = None
_running = threading.Event()


def _contains_wake_word(transcript: str, wake_words: list) -> bool:
    norm = transcript.lower().strip()
    for phrase in wake_words:
        if phrase in norm:
            return True
    return False


def _fuzzy_wake_match(transcript: str) -> bool:
    """
    Catch common Vosk/STT mis-transcriptions of wake words.
    e.g. 'road mate', 'hi looks', 'road made', 'assist'
    """
    norm = transcript.lower().strip()
    fuzzy_triggers = [
        # RoadMate variants
        "road mate", "road made", "road may", "road mate", "roadmate",
        "hey road", "a road", "roads mate", "road match",
        # Hilux variants
        "hi looks", "hi lux", "hi luck", "hi locks", "high lux",
        "hey lux", "hey looks", "hey luck", "hilux", "hi luke",
        "hey luke", "high luck", "hi lucas",
        # Assistant variants
        "assist", "a system", "listen", "system",
        # Generic activators
        "okay", "ok computer", "ok mate", "hey mate",
        "wake up", "are you there",
    ]
    return any(t in norm for t in fuzzy_triggers)


def _listen_loop(wake_words: list, on_wake):
    """
    Persistent loop: keep microphone open across iterations for low-latency detection.
    Transcribes short chunks via Google STT (accurate), with Vosk as offline fallback.
    """
    import speech_recognition as sr
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools.stt_tool import _get_vosk_model

    stt_language = os.environ.get("STT_LANGUAGE", "en-AU")

    r = sr.Recognizer()
    r.dynamic_energy_threshold = True       # Adapt to changing ambient noise (e.g. engine on/off)
    r.dynamic_energy_ratio = 1.3            # More sensitive to quiet voices
    r.pause_threshold = 0.7                 # Short pause OK for wake words
    r.non_speaking_duration = 0.4

    device_index = None
    raw_idx = os.environ.get("AUDIO_INPUT_DEVICE_INDEX", "0")
    try:
        v = int(raw_idx)
        if v > 0:
            device_index = v
    except ValueError:
        pass

    logger.info(f"Wake word loop starting. Mic device: {device_index or 'default'}")
    logger.info(f"Listening for: {wake_words}")

    # Pre-load Vosk model before entering the hot loop
    model = _get_vosk_model()
    if model is None:
        logger.warning("Vosk unavailable — wake word will use Google STT only")

    print(f"[RoadMate] Listening for wake word... (say 'assistant' or 'hey roadmate')", flush=True)

    # Keep the microphone open for the entire session — avoids the latency
    # and missed-audio penalty of closing/reopening it every iteration.
    recalibrate_every = 60   # Re-calibrate every ~60 detections (adapts to environment)
    iteration = 0

    try:
        with sr.Microphone(device_index=device_index) as source:
            logger.info("Calibrating for ambient noise (2s)...")
            r.adjust_for_ambient_noise(source, duration=2.0)
            # Don't cap the threshold — noisy environments (car) need it higher
            logger.info(f"Calibration done. Energy threshold: {r.energy_threshold:.0f}")

            while _running.is_set():
                # Periodically recalibrate while mic is still open
                if iteration > 0 and iteration % recalibrate_every == 0:
                    logger.debug("Periodic recalibration...")
                    r.adjust_for_ambient_noise(source, duration=1.0)
                    logger.debug(f"Recalibrated. New threshold: {r.energy_threshold:.0f}")
                iteration += 1

                try:
                    audio = r.listen(source, timeout=4, phrase_time_limit=5)
                except sr.WaitTimeoutError:
                    continue  # Silence window — loop again immediately

                transcript = ""

                # Google STT first — more accurate, handles accents well
                try:
                    transcript = r.recognize_google(audio, language=stt_language)
                except sr.UnknownValueError:
                    pass  # Audio captured but not understood
                except sr.RequestError:
                    pass  # No internet — fall through to Vosk
                except Exception as e:
                    logger.debug(f"Google STT error: {e}")

                # Fallback to Vosk if Google got nothing
                if not transcript and model:
                    try:
                        from vosk import KaldiRecognizer
                        wav_data = audio.get_wav_data()
                        with io.BytesIO(wav_data) as buf:
                            with wave.open(buf, "rb") as wf:
                                rec = KaldiRecognizer(model, wf.getframerate())
                                rec.AcceptWaveform(wf.readframes(wf.getnframes()))
                                result = json.loads(rec.FinalResult())
                                transcript = result.get("text", "").strip()
                    except Exception as e:
                        logger.debug(f"Vosk error: {e}")

                if transcript:
                    print(f"[Wake listener heard]: '{transcript}'", flush=True)
                    logger.info(f"Wake listener transcript: '{transcript}'")

                    if _contains_wake_word(transcript, wake_words) or _fuzzy_wake_match(transcript):
                        logger.info(f"Wake word MATCHED in: '{transcript}'")
                        try:
                            on_wake()
                        except Exception as e:
                            logger.error(f"Wake callback error: {e}")

    except Exception as e:
        if _running.is_set():
            logger.error(f"Wake loop fatal error: {e}")
    finally:
        logger.info("Wake word loop exited.")


def start_listening_loop(callback_fn, wake_words: list = None):
    """Start the background wake word detection thread."""
    global _thread

    if _running.is_set():
        logger.warning("Wake word loop already running.")
        return

    phrases = wake_words or DEFAULT_WAKE_WORDS
    _running.set()

    _thread = threading.Thread(
        target=_listen_loop,
        args=(phrases, callback_fn),
        daemon=True,
        name="WakeWordListener",
    )
    _thread.start()
    logger.info("Wake word listener thread started.")


def stop():
    """Stop the wake word detection thread."""
    _running.clear()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    logger.info("Wake word listener stopped.")


def is_running() -> bool:
    return _running.is_set()


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.INFO)

    print("=== wake_word_tool self-test ===")
    print(f"Wake words: {DEFAULT_WAKE_WORDS}")
    print("Say a wake word. Test runs for 30 seconds.\n")

    count = [0]

    def on_wake():
        count[0] += 1
        print(f"\n*** WAKE WORD DETECTED #{count[0]} ***\n", flush=True)

    start_listening_loop(on_wake)

    try:
        time.sleep(30)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop()

    print(f"\nTotal detections: {count[0]}")
    print("=== self-test complete ===")
