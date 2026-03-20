"""
main.py — RoadMate AI Agent Orchestrator

The intelligent coordinator for the Hilux Driving Companion AI.
Follows the WAT framework: this file owns reasoning and routing;
tools own execution.

Usage:
    python main.py           # Full voice mode (microphone + TTS)
    python main.py --text    # Text-only mode (keyboard input, no mic/TTS)

Wake words: "Hey RoadMate", "Hi Hilux", "Assistant"
"""

import os
import sys
import time
import logging
import argparse
import threading
import re
import random

# Force UTF-8 output on Windows to handle emojis in Claude responses
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

# ─── Load environment ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    print("[WARNING] python-dotenv not installed. Load .env manually or set env vars.")

# ─── Configure logging ─────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = os.environ.get("LOG_FILE", ".tmp/roadmate.log")
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("RoadMate")

# ─── Import tools ──────────────────────────────────────────────────────────────
from tools import memory_tool, driving_mode_tool, claude_tool, intent_tool
from tools import tts_tool, stt_tool, wake_word_tool
from tools import weather_tool, maps_tool, reminder_tool, music_tool
from tools.intent_tool import extract_reminder_text, extract_destination

# Safety phrases that always trigger immediate pull-over advice
_SAFETY_PHRASES = [
    "falling asleep", "can't keep my eyes open", "cant keep my eyes open",
    "can't see straight", "about to pass out", "extremely exhausted",
]


class RoadMateAgent:
    """
    The RoadMate agent orchestrates all tools and manages the
    full interaction lifecycle: wake → listen → intent → execute → speak.
    """

    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode
        self._wake_event = threading.Event()
        self._shutdown = threading.Event()

        logger.info("Initializing RoadMate agent...")
        self.profile = memory_tool.load_user_profile()
        self.name = self.profile.get("name", "Jess")

        logger.info(f"Loaded profile for: {self.name}")
        logger.info(f"City: {self.profile.get('default_city', 'unknown')}")

    # ─── Startup ────────────────────────────────────────────────────────────────

    def _startup_banner(self):
        print("\n" + "=" * 60)
        print("  RoadMate AI -- Hilux Driving Companion")
        print("  Version 2.0 | WAT Framework")
        print("=" * 60)
        driving = driving_mode_tool.is_driving_mode_active()
        mode_label = "DRIVING MODE" if driving else "Normal Mode"
        print(f"  Mode: {mode_label}")
        if self.text_mode:
            print("  Input: Keyboard (text mode)")
        else:
            print(f"  Wake words: {', '.join(self.profile.get('preferences', {}).get('wake_words', ['hey roadmate']))}")
        print("=" * 60 + "\n")

    def _announce_startup(self):
        """Greet the user and announce any due reminders."""
        greeting = f"Hey {self.name}, RoadMate is online and ready to go."
        self._speak(greeting)

        # Check for due reminders
        due = reminder_tool.check_due_reminders()
        if due:
            count = len(due)
            if count == 1:
                self._speak(f"You have a reminder: {due[0]['text']}.")
            else:
                self._speak(f"You have {count} reminders due. First one: {due[0]['text']}.")

    # ─── Core I/O ───────────────────────────────────────────────────────────────

    def _speak(self, text: str):
        """Speak or print text depending on mode."""
        if not text:
            return
        # Strip markdown formatting (bold, italic, headers, bullets)
        clean = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)   # **bold**, *italic*, ***both***
        clean = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', clean)     # _italic_, __bold__
        clean = re.sub(r'^#{1,6}\s*', '', clean, flags=re.MULTILINE)  # # headers
        clean = re.sub(r'^[-*]\s+', '', clean, flags=re.MULTILINE)    # bullet points
        # Strip emojis for TTS and safe console output
        clean = re.sub(r'[^\x00-\x7F\u00C0-\u024F\u1E00-\u1EFF]+', '', clean).strip()
        print(f"\n[RoadMate]: {clean}")
        if not self.text_mode:
            tts_tool.speak(clean)

    def _listen(self) -> str:
        """Capture and transcribe one user utterance."""
        if self.text_mode:
            try:
                transcript = input(f"\n[{self.name}]: ").strip()
                return transcript
            except (EOFError, KeyboardInterrupt):
                return "exit"

        print("[Listening...]")
        audio = stt_tool.capture_audio()
        if not audio:
            logger.debug("No audio captured.")
            return ""
        transcript = stt_tool.transcribe(audio)
        if transcript:
            print(f"[{self.name}]: {transcript}")
        return transcript

    # ─── Wake word callback (voice mode only) ───────────────────────────────────

    def _on_wake(self):
        """Called by wake_word_tool when a wake phrase is detected."""
        logger.info("Wake word triggered — clearing conversation history for fresh session.")
        memory_tool.reset_conversation_history()
        self._wake_event.set()

    def _wait_for_wake(self):
        """Block until wake word is detected."""
        self._wake_event.clear()
        self._wake_event.wait()

    # ─── Main interaction cycle ─────────────────────────────────────────────────

    def _handle_one_turn(self):
        """
        Process one complete interaction: listen → classify → route → respond.
        """
        if not self.text_mode:
            # Signal readiness
            print("[RoadMate is listening...]")
            self._speak("Yes?")

        transcript = self._listen()

        if not transcript:
            self._speak("I didn't catch that. Try again.")
            return

        # Check exit commands
        if transcript.lower() in ("exit", "quit", "goodbye", "bye", "shut down"):
            self._speak(f"Goodbye {self.name}. Drive safe!")
            self._shutdown.set()
            return

        # Safety override check — bypass all routing
        norm = transcript.lower()
        if any(phrase in norm for phrase in _SAFETY_PHRASES):
            self._speak(
                "Please pull over somewhere safe right now. "
                "Your safety matters more than arriving on time. "
                "Take a break — I'll be here when you're ready."
            )
            return

        # Classify intent
        result = intent_tool.classify_intent(transcript)
        intent = result["intent"]
        logger.info(f"Intent: {intent} | Input: '{transcript}'")

        # Route to handler
        try:
            if intent == "weather":
                self._handle_weather(transcript)
            elif intent == "navigation":
                self._handle_navigation(transcript)
            elif intent == "reminder_set":
                self._handle_reminder_set(transcript)
            elif intent == "reminder_get":
                self._handle_reminder_get()
            elif intent == "driving_mode_on":
                self._handle_driving_mode(enable=True)
            elif intent == "driving_mode_off":
                self._handle_driving_mode(enable=False)
            elif intent == "emotional":
                self._handle_emotional(transcript)
            elif intent == "time_date":
                self._handle_time_date()
            elif intent == "joke":
                self._handle_joke()
            elif intent == "fun_fact":
                self._handle_fun_fact()
            elif intent == "trivia":
                self._handle_trivia()
            elif intent == "roast":
                self._handle_roast()
            elif intent == "rap":
                self._handle_rap(transcript)
            elif intent == "riddle":
                self._handle_riddle()
            elif intent == "timer":
                self._handle_timer(transcript)
            elif intent == "nearby":
                self._handle_nearby(transcript)
            elif intent == "music":
                self._handle_music(transcript)
            else:
                self._handle_general(transcript)
        except Exception as e:
            err_str = str(e).lower()
            if "credit balance" in err_str or "credit" in err_str:
                self._speak(
                    "My AI brain needs credits to answer that. "
                    "Please top up the Anthropic API at console.anthropic.com. "
                    "I can still tell you the time, manage reminders, and toggle driving mode offline."
                )
            else:
                logger.error(f"Handler error for intent '{intent}': {e}", exc_info=True)
                self._speak("Something went wrong. Ask me another question.")

    # ─── Intent Handlers ────────────────────────────────────────────────────────

    def _handle_weather(self, transcript: str):
        """Follows handle_weather_query.md workflow."""
        driving = driving_mode_tool.is_driving_mode_active()
        city = self.profile.get("default_city", "Brisbane")

        try:
            data = weather_tool.get_current_weather(city)
            speech = weather_tool.format_for_speech(data, driving_mode=driving)

            # Let Claude add a natural response around the data
            system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
            history = memory_tool.load_conversation_history(max_turns=6)
            context = f"Current weather data: {speech}"
            response = claude_tool.get_response(
                user_message=f"{transcript}. Weather info: {context}",
                system_prompt=system,
                history=history,
                driving_mode=driving,
            )
            self._speak(response)
            self._save_turn(transcript, response)

        except (ConnectionError, TimeoutError):
            self._speak("I can't reach the weather service right now. Check your connection and try again.")
        except ValueError as e:
            self._speak(str(e))

    def _handle_navigation(self, transcript: str):
        """Follows handle_navigation.md workflow."""
        driving = driving_mode_tool.is_driving_mode_active()
        saved = self.profile.get("saved_locations", {})

        destination = extract_destination(transcript, saved)
        if not destination:
            self._speak("Where are you heading? Tell me the destination.")
            dest_response = self._listen()
            destination = extract_destination(dest_response, saved) or dest_response

        origin = self.profile.get("default_city", "Brisbane")

        try:
            data = maps_tool.get_travel_time(origin, destination)
            speech = maps_tool.format_for_speech(data, driving_mode=driving)
            self._speak(speech)

        except (ConnectionError, TimeoutError):
            self._speak("I can't reach maps right now. Check your connection.")
        except ValueError as e:
            self._speak(f"I couldn't find that route. {e}")

    def _handle_reminder_set(self, transcript: str):
        """Follows handle_reminder.md (set) workflow."""
        reminder_text = extract_reminder_text(transcript)
        if not reminder_text or len(reminder_text) < 3:
            self._speak("What would you like me to remind you about?")
            reminder_text = self._listen()

        reminder_tool.add_reminder(reminder_text)
        self._speak(f"Got it. I'll remind you to {reminder_text}.")

    def _handle_reminder_get(self):
        """Follows handle_reminder.md (get) workflow."""
        driving = driving_mode_tool.is_driving_mode_active()
        reminders = reminder_tool.get_reminders("today")
        speech = reminder_tool.format_for_speech(reminders, driving_mode=driving)
        self._speak(speech)

    def _handle_driving_mode(self, enable: bool):
        """Follows driving_mode_management.md workflow."""
        if enable:
            driving_mode_tool.enable_driving_mode()
            self._speak("Driving mode on. I'll keep my answers short and focused.")
        else:
            driving_mode_tool.disable_driving_mode()
            self._speak("Driving mode off. Full responses are back.")

    def _handle_emotional(self, transcript: str):
        """Follows handle_emotional_support.md workflow."""
        driving = driving_mode_tool.is_driving_mode_active()

        empathy_system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        empathy_system += (
            "\n\nEMOTIONAL SUPPORT MODE: The user is experiencing emotional difficulty "
            "while driving. Be warm, calm, and very brief. Acknowledge their feeling in one "
            "sentence, then offer one supportive thought or action. Never be dismissive. "
            "If they mention extreme fatigue or danger, prioritize their safety above all else."
        )

        history = memory_tool.load_conversation_history(max_turns=4)
        response = claude_tool.get_response(
            user_message=transcript,
            system_prompt=empathy_system,
            history=history,
            driving_mode=True,  # Always short in emotional mode
            max_tokens=120,
        )
        self._speak(response)
        self._save_turn(transcript, response)

    def _handle_time_date(self):
        """Return current time and date — fully offline."""
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%A, %B %d, %Y")
        self._speak(f"It's {time_str} on {date_str}.")

    def _handle_general(self, transcript: str):
        """Follows handle_general_chat.md workflow — Claude AI conversation."""
        driving = driving_mode_tool.is_driving_mode_active()
        history = memory_tool.load_conversation_history(max_turns=6)
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        max_tokens = driving_mode_tool.get_max_tokens()

        response = claude_tool.get_response(
            user_message=transcript,
            system_prompt=system,
            history=history,
            driving_mode=driving,
            max_tokens=max_tokens,
        )
        self._speak(response)
        self._save_turn(transcript, response)

    # ─── Fun & Impressive Features ──────────────────────────────────────────────

    def _handle_joke(self):
        """Tell a genuinely funny, clean joke."""
        driving = driving_mode_tool.is_driving_mode_active()
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            "\n\nJOKE MODE: Tell one genuinely funny, original joke. "
            "Deliver the setup and punchline naturally as if speaking. "
            "Keep it clean and clever — not cheesy unless intentionally self-aware about it. "
            "No emojis, no lists, just the joke."
        )
        response = claude_tool.get_response(
            user_message="Tell me a great joke right now.",
            system_prompt=system,
            history=[],
            driving_mode=driving,
            max_tokens=150,
        )
        self._speak(response)
        self._save_turn("tell me a joke", response)

    def _handle_fun_fact(self):
        """Share a mind-blowing, conversation-worthy fact."""
        driving = driving_mode_tool.is_driving_mode_active()
        city = self.profile.get("default_city", "Manila")
        topics = [
            "cars and automotive history",
            "the Toyota Hilux and why it's legendary",
            "the Philippines",
            "space and the universe",
            "human psychology",
            "bizarre world records",
            "animals doing surprising things",
            "technology that sounds like science fiction",
        ]
        topic = random.choice(topics)
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            f"\n\nFUN FACT MODE: Share one truly surprising, mind-blowing fact about: {topic}. "
            "Start with the fact itself — no 'Did you know...' intro. "
            "Deliver it in 2-3 sentences max, conversationally. Make it genuinely interesting."
        )
        response = claude_tool.get_response(
            user_message=f"Give me a fascinating fun fact about {topic}.",
            system_prompt=system,
            history=[],
            driving_mode=driving,
            max_tokens=150,
        )
        self._speak(response)
        self._save_turn("give me a fun fact", response)

    def _handle_trivia(self):
        """
        Ask a trivia question, listen for the answer, then reveal if correct.
        This is a 2-turn interaction — ask → listen → judge.
        """
        driving = driving_mode_tool.is_driving_mode_active()
        categories = [
            "cars and motorsport",
            "geography",
            "science",
            "movies and pop culture",
            "history",
            "sports",
            "food",
        ]
        category = random.choice(categories)

        # Step 1: Get a trivia question from Claude
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            f"\n\nTRIVIA MODE: Ask one trivia question from the category: {category}. "
            "Ask only the question — do NOT reveal the answer yet. "
            "Keep it short and clear. End with 'What's your answer?'"
        )
        question_response = claude_tool.get_response(
            user_message=f"Give me a {category} trivia question.",
            system_prompt=system,
            history=[],
            driving_mode=driving,
            max_tokens=80,
        )
        self._speak(question_response)

        # Step 2: Listen for the user's answer
        user_answer = self._listen()
        if not user_answer:
            self._speak("No answer? I'll let that one slide.")
            return

        # Step 3: Judge the answer and reveal
        judge_system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        judge_system += (
            "\n\nTRIVIA JUDGE MODE: You asked a trivia question and received an answer. "
            "Judge if the answer is correct (even if phrased differently or partially right). "
            "If correct: celebrate briefly and confirm the answer. "
            "If wrong: be playful about it, then reveal the correct answer. "
            "Keep it to 2 sentences max."
        )
        judge_response = claude_tool.get_response(
            user_message=f"The trivia question was: {question_response}\nThe user answered: {user_answer}",
            system_prompt=judge_system,
            history=[],
            driving_mode=driving,
            max_tokens=100,
        )
        self._speak(judge_response)
        self._save_turn(f"trivia: {user_answer}", judge_response)

    def _handle_roast(self):
        """Deliver a playful, witty roast — nothing mean-spirited."""
        driving = driving_mode_tool.is_driving_mode_active()
        name = self.name
        vehicle = self.profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car = f"Toyota {vehicle.get('model', 'Hilux')}"
        city = self.profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            f"\n\nROAST MODE: Give {name} a short, playful, witty roast. "
            f"You can reference the fact they drive a {car} in {city}, or just keep it general. "
            "Be clever and funny, not mean or offensive. End on a warm note. "
            "2-3 sentences max. Speak directly to them."
        )
        response = claude_tool.get_response(
            user_message=f"Roast me, my name is {name} and I drive a {car}.",
            system_prompt=system,
            history=[],
            driving_mode=driving,
            max_tokens=120,
        )
        self._speak(response)
        self._save_turn("roast me", response)

    def _handle_rap(self, transcript: str):
        """Drop an original rap verse — about the car, the user, or the road."""
        driving = driving_mode_tool.is_driving_mode_active()
        name = self.name
        vehicle = self.profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
        car = f"Toyota {vehicle.get('model', 'Hilux')}"
        city = self.profile.get("default_city", "Manila")
        # Let the user's words guide the subject
        subject = transcript.lower()
        if "hilux" in subject or "car" in subject or "truck" in subject:
            topic = f"the {car}"
        elif "road" in subject or "drive" in subject or "driving" in subject:
            topic = "driving on the open road"
        else:
            topic = f"{name} and their legendary {car}"

        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            f"\n\nRAP MODE: Write and deliver an original, catchy rap verse (8-12 lines) about: {topic}. "
            f"Reference {city} if it fits naturally. Make it flow, use rhymes, "
            "make it feel real and cool — not corny. Deliver it as spoken word, naturally."
        )
        response = claude_tool.get_response(
            user_message=f"Freestyle rap about {topic}.",
            system_prompt=system,
            history=[],
            driving_mode=False,  # Always full response for rap
            max_tokens=250,
        )
        self._speak(response)
        self._save_turn(transcript, response)

    def _handle_riddle(self):
        """
        Pose a riddle and reveal the answer after the user guesses.
        2-turn interaction: riddle → listen → reveal.
        """
        driving = driving_mode_tool.is_driving_mode_active()
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            "\n\nRIDDLE MODE: Give one clever riddle. "
            "State only the riddle — do NOT give the answer yet. "
            "End with 'What am I?' or 'What is it?'"
        )
        riddle_response = claude_tool.get_response(
            user_message="Give me a riddle.",
            system_prompt=system,
            history=[],
            driving_mode=driving,
            max_tokens=80,
        )
        self._speak(riddle_response)

        # Listen for their guess
        guess = self._listen()
        if not guess:
            self._speak("Give up? I'll reveal it next time you ask.")
            return

        # Reveal and judge
        reveal_system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        reveal_system += (
            "\n\nRIDDLE REVEAL: You gave a riddle and the user guessed. "
            "Tell them if they got it right or wrong, then reveal the answer in a satisfying way. "
            "Keep it fun and 2 sentences max."
        )
        reveal_response = claude_tool.get_response(
            user_message=f"The riddle was: {riddle_response}\nThe user guessed: {guess}",
            system_prompt=reveal_system,
            history=[],
            driving_mode=driving,
            max_tokens=80,
        )
        self._speak(reveal_response)
        self._save_turn(f"riddle guess: {guess}", reveal_response)

    def _handle_timer(self, transcript: str):
        """
        Set a spoken countdown timer. Speaks an alert when time is up.
        Parses duration from natural language: 'set a timer for 5 minutes'.
        """
        import re as _re
        norm = transcript.lower()
        seconds = 0

        # Parse hours
        m = _re.search(r'(\d+)\s*(?:hour|hours|hr|hrs)', norm)
        if m:
            seconds += int(m.group(1)) * 3600

        # Parse minutes
        m = _re.search(r'(\d+)\s*(?:minute|minutes|min|mins)', norm)
        if m:
            seconds += int(m.group(1)) * 60

        # Parse seconds (only if no minutes/hours found, or explicitly said)
        m = _re.search(r'(\d+)\s*(?:second|seconds|sec|secs)', norm)
        if m and seconds == 0:
            seconds += int(m.group(1))

        if seconds == 0:
            # Ask the user how long
            self._speak("How long should I set the timer for?")
            answer = self._listen()
            return self._handle_timer(answer) if answer else None

        # Format a human-readable label
        parts = []
        if seconds >= 3600:
            h = seconds // 3600
            parts.append(f"{h} hour{'s' if h > 1 else ''}")
            seconds %= 3600
        if seconds >= 60:
            m_val = seconds // 60
            parts.append(f"{m_val} minute{'s' if m_val > 1 else ''}")
            seconds_rem = seconds % 60
        else:
            seconds_rem = seconds
        if seconds_rem:
            parts.append(f"{seconds_rem} second{'s' if seconds_rem > 1 else ''}")

        label = " and ".join(parts)
        total = sum([
            (int(p.split()[0]) * 3600 if "hour" in p else 0) +
            (int(p.split()[0]) * 60 if "minute" in p else 0) +
            (int(p.split()[0]) if "second" in p else 0)
            for p in parts
        ])

        self._speak(f"Timer set for {label}. I'll let you know when it's up.")
        logger.info(f"Timer started: {label} ({total}s)")

        def _timer_done():
            time.sleep(total)
            self._speak(f"Hey {self.name}! Your {label} timer is done.")

        t = threading.Thread(target=_timer_done, daemon=True, name="TimerThread")
        t.start()

    def _handle_nearby(self, transcript: str):
        """Suggest nearby places based on user query and known city."""
        driving = driving_mode_tool.is_driving_mode_active()
        city = self.profile.get("default_city", "Manila")
        system = claude_tool.build_system_prompt(self.profile, driving_mode=driving)
        system += (
            f"\n\nNEARBY PLACES MODE: The user is in or around {city} and wants to find somewhere nearby. "
            "Give 2-3 practical, specific suggestions (real place types or well-known areas in that city). "
            "Be helpful and conversational. If driving, keep it to one suggestion. "
            "You don't have real-time GPS but give genuinely useful local knowledge."
        )
        response = claude_tool.get_response(
            user_message=transcript,
            system_prompt=system,
            history=memory_tool.load_conversation_history(max_turns=4),
            driving_mode=driving,
            max_tokens=180,
        )
        self._speak(response)
        self._save_turn(transcript, response)

    def _handle_music(self, transcript: str):
        """Follows handle_music.md workflow — Spotify music control."""
        norm = transcript.lower()

        try:
            # Pause / stop
            if any(w in norm for w in ["pause", "stop music", "stop the music"]):
                ok = music_tool.pause()
                self._speak("Music paused." if ok else "Couldn't pause music right now.")

            # Resume
            elif any(w in norm for w in ["resume", "unpause", "continue music"]):
                ok = music_tool.resume()
                self._speak("Resuming." if ok else "Nothing is paused to resume.")

            # Skip / next
            elif any(w in norm for w in ["next", "skip"]):
                ok = music_tool.next_track()
                self._speak("Skipping." if ok else "Couldn't skip right now.")

            # Previous
            elif any(w in norm for w in ["previous", "go back", "last song"]):
                ok = music_tool.previous_track()
                self._speak("Going back." if ok else "Couldn't go back.")

            # What's playing
            elif any(w in norm for w in ["what's playing", "whats playing", "currently playing", "what song"]):
                info = music_tool.get_current_track()
                if info:
                    status = "Playing" if info["is_playing"] else "Paused on"
                    self._speak(f"{status}: {info['name']} by {info['artist']}.")
                else:
                    self._speak("Nothing is playing right now.")

            # Volume
            elif "volume" in norm or "turn up" in norm or "turn down" in norm:
                m = re.search(r'(\d+)', norm)
                if m:
                    ok = music_tool.set_volume(int(m.group(1)))
                    self._speak(f"Volume set to {m.group(1)}." if ok else "Couldn't adjust volume.")
                elif "up" in norm:
                    music_tool.set_volume(80)
                    self._speak("Volume up.")
                elif "down" in norm:
                    music_tool.set_volume(30)
                    self._speak("Volume down.")

            # Play something
            else:
                query = norm
                for prefix in ["play some music", "play some", "play music", "put on music", "play"]:
                    if query.startswith(prefix):
                        query = query[len(prefix):].strip()
                        break

                if not query or query in ["music", "a song", "something", ""]:
                    self._speak("What would you like to play? Say an artist, song, or genre.")
                    query = self._listen()
                    if not query:
                        return

                playing = music_tool.play_query(query)
                if playing:
                    self._speak(f"Now playing {playing}.")
                else:
                    self._speak(f"Couldn't find anything for '{query}' on Spotify. Try a different search.")

            self._save_turn(transcript, "")

        except (ValueError, RuntimeError) as e:
            err = str(e)
            if "not configured" in err.lower() or "SPOTIFY_CLIENT" in err:
                self._speak(
                    "Spotify isn't set up yet. "
                    "Add your Spotify client ID and secret to the dot env file. "
                    "Get credentials at developer dot spotify dot com."
                )
            elif "No active Spotify device" in err:
                self._speak(
                    "No active Spotify device found. "
                    "Open Spotify on your phone or computer first, then try again."
                )
            else:
                self._speak(err)
        except Exception as e:
            err = str(e).lower()
            if "premium" in err:
                self._speak("Spotify music control requires a Premium account.")
            elif "device" in err:
                self._speak("Open Spotify on your phone or computer first, then try again.")
            else:
                logger.error(f"Music handler error: {e}", exc_info=True)
                self._speak("I couldn't control Spotify right now. Make sure Spotify is open.")

    # ─── Helpers ────────────────────────────────────────────────────────────────

    def _save_turn(self, user_text: str, assistant_text: str):
        memory_tool.append_conversation_turn("user", user_text)
        memory_tool.append_conversation_turn("assistant", assistant_text)

    # ─── Run loop ───────────────────────────────────────────────────────────────

    def run(self):
        """Main entry point — start RoadMate."""
        self._startup_banner()
        self._announce_startup()

        if self.text_mode:
            print("\nText mode active. Type your message and press Enter.")
            print("Type 'exit' or 'quit' to stop.\n")
            while not self._shutdown.is_set():
                try:
                    self._handle_one_turn()
                except KeyboardInterrupt:
                    self._speak(f"Goodbye {self.name}. Drive safe!")
                    break
        else:
            # Start wake word listener
            print("\nSay 'Hey RoadMate', 'Hi Hilux', or 'Assistant' to wake me up.")
            print("Press Ctrl+C to exit.\n")
            wake_word_tool.start_listening_loop(callback_fn=self._on_wake)

            try:
                while not self._shutdown.is_set():
                    self._wait_for_wake()
                    if not self._shutdown.is_set():
                        self._handle_one_turn()
            except KeyboardInterrupt:
                self._speak(f"Goodbye {self.name}. Drive safe!")
            finally:
                wake_word_tool.stop()

        logger.info("RoadMate agent shut down.")


# ─── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RoadMate AI — Hilux Driving Companion"
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="Run in text-only mode (keyboard input, no microphone or TTS).",
    )
    args = parser.parse_args()

    agent = RoadMateAgent(text_mode=args.text)
    agent.run()


if __name__ == "__main__":
    main()
