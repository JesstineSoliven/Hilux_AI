"""
intent_tool.py — Rule-based intent classifier for RoadMate AI.

Classifies user utterances into one of 9 intent categories using
keyword matching. Runs in < 1ms — no API call needed for routing.

Single responsibility: classify intent from transcript text.
"""

import re
import logging

logger = logging.getLogger(__name__)

# ─── Intent Definitions ────────────────────────────────────────────────────────

INTENT_RULES = [
    {
        "intent": "driving_mode_on",
        "keywords": [
            "driving mode on", "short answers", "i'm driving", "im driving",
            "start driving mode", "enable driving mode", "activate driving mode",
            "i am driving", "keep it short",
        ],
    },
    {
        "intent": "driving_mode_off",
        "keywords": [
            "driving mode off", "normal mode", "i've parked", "ive parked",
            "i have parked", "disable driving mode", "full answers", "long answers",
            "i stopped driving", "parked now",
        ],
    },
    {
        "intent": "weather",
        "keywords": [
            "weather", "rain", "raining", "temperature", "forecast", "hot today",
            "cold today", "sunny", "cloudy", "storm", "wind", "humidity",
            "will it rain", "how hot", "how cold", "what's the weather",
        ],
    },
    {
        "intent": "navigation",
        "keywords": [
            "traffic", "how long to", "how long will it take", "eta",
            "directions", "route", "navigate", "how far", "get to",
            "drive to", "travel time", "heavy traffic", "congestion",
            "roadworks", "accident on", "how long to reach",
        ],
    },
    {
        "intent": "reminder_set",
        "keywords": [
            "remind me", "set a reminder", "set reminder", "add reminder",
            "don't let me forget", "dont let me forget", "remember to",
            "add to my list", "add task", "create reminder", "note that",
        ],
    },
    {
        "intent": "reminder_get",
        "keywords": [
            "my reminders", "what are my reminders", "what do i have",
            "any reminders", "my tasks", "my to-do", "my todo",
            "what should i do today", "read my reminders", "list reminders",
            "what's on my list",
        ],
    },
    {
        "intent": "emotional",
        "keywords": [
            "i'm stressed", "im stressed", "i am stressed",
            "i'm anxious", "im anxious", "feeling anxious",
            "i'm tired", "im tired", "i am tired", "feeling tired",
            "i'm exhausted", "im exhausted", "so exhausted",
            "falling asleep", "can't keep my eyes open",
            "cant keep my eyes open", "motivate me", "i need motivation",
            "i'm struggling", "im struggling", "feeling down",
            "keep me awake", "talk to me", "tell me something inspiring",
            "i feel", "cheer me up", "i'm bored", "im bored",
        ],
    },
    {
        "intent": "time_date",
        "keywords": [
            "what time is it", "what's the time", "current time",
            "what time", "what day is it", "what's today", "today's date",
            "what is the date", "what year", "what day", "what date",
            "tell me the time", "the time",
        ],
    },
    {
        "intent": "joke",
        "keywords": [
            "tell me a joke", "say something funny", "make me laugh",
            "tell a joke", "give me a joke", "humor me", "tell me something funny",
            "crack a joke", "cheer me up with a joke",
        ],
    },
    {
        "intent": "fun_fact",
        "keywords": [
            "fun fact", "random fact", "tell me something interesting",
            "did you know", "interesting fact", "teach me something",
            "something cool", "something crazy", "blow my mind",
            "tell me a fact", "give me a fact", "random trivia fact",
        ],
    },
    {
        "intent": "trivia",
        "keywords": [
            "trivia", "quiz me", "ask me a question", "test me",
            "trivia question", "quiz question", "give me a trivia",
            "challenge me", "pub quiz", "ask me something",
        ],
    },
    {
        "intent": "roast",
        "keywords": [
            "roast me", "make fun of me", "give me a roast",
            "clown me", "burn me", "insult me", "talk trash",
        ],
    },
    {
        "intent": "rap",
        "keywords": [
            "rap for me", "freestyle", "spit some bars", "rap about",
            "drop a verse", "make a rap", "write a rap",
            "rap about my car", "rap about my hilux", "give me a rap",
        ],
    },
    {
        "intent": "riddle",
        "keywords": [
            "riddle", "give me a riddle", "brain teaser",
            "stump me", "challenge my brain", "guess this",
            "puzzle me", "give me a puzzle",
        ],
    },
    {
        "intent": "timer",
        "keywords": [
            "set a timer", "timer for", "start a timer", "countdown",
            "alert me in", "wake me in", "ping me in",
            "tell me in", "remind me in",
        ],
    },
    {
        "intent": "nearby",
        "keywords": [
            "what's nearby", "nearest", "closest", "near me",
            "find a restaurant", "find a gas station", "find a petrol",
            "coffee shop nearby", "fast food near", "where can i eat",
            "gas station near", "petrol station near", "find food",
            "any place nearby", "places near",
        ],
    },
    {
        "intent": "music",
        "keywords": [
            "play music", "play some music", "put on music", "play a song",
            "play some", "play rock", "play pop", "play jazz", "play hip hop",
            "play rnb", "play classical", "play opm", "play my playlist",
            "play artist", "play by", "play the song", "queue song",
            "pause music", "stop music", "stop the music",
            "resume music", "unpause music", "continue music",
            "next song", "skip song", "skip track", "next track",
            "previous song", "last song", "go back song",
            "what's playing", "whats playing", "currently playing", "what song is this",
            "volume up", "volume down", "set volume", "turn up music", "turn down music",
            "shuffle music", "shuffle playlist",
        ],
    },
    {
        "intent": "general",
        "keywords": [],  # Fallback — matches everything not caught above
    },
]

# Safety-critical phrases that bypass all routing (handled directly in main.py)
SAFETY_OVERRIDE_PHRASES = [
    "falling asleep",
    "can't keep my eyes open",
    "cant keep my eyes open",
    "can't see straight",
    "about to pass out",
    "extremely exhausted",
    "falling asleep at the wheel",
]


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation for reliable matching."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


def classify_intent(transcript: str) -> dict:
    """
    Classify the user's utterance into an intent.

    Returns:
        dict with keys:
            "intent"  — intent name string
            "raw"     — original transcript
            "safety"  — True if safety override phrase detected
    """
    if not transcript:
        return {"intent": "general", "raw": "", "safety": False}

    norm = _normalize(transcript)

    # Check safety override first
    safety = any(phrase in norm for phrase in SAFETY_OVERRIDE_PHRASES)

    # Match intents in priority order
    for rule in INTENT_RULES:
        intent_name = rule["intent"]
        keywords = rule["keywords"]

        if not keywords:
            # Fallback
            matched_intent = intent_name
            break

        for kw in keywords:
            if kw in norm:
                logger.debug(f"Intent '{intent_name}' matched keyword: '{kw}'")
                return {
                    "intent": intent_name,
                    "raw": transcript,
                    "safety": safety,
                }

    return {
        "intent": "general",
        "raw": transcript,
        "safety": safety,
    }


def extract_reminder_text(transcript: str) -> str:
    """
    Extract the reminder content from a transcript like:
    'Remind me to call the mechanic at 3pm'
    → 'call the mechanic at 3pm'
    """
    norm = transcript.lower()
    trigger_phrases = [
        "remind me to", "remind me about", "remind me ",
        "set a reminder to", "set a reminder for",
        "don't let me forget to", "dont let me forget to",
        "remember to", "add task ",
    ]
    for phrase in trigger_phrases:
        if phrase in norm:
            idx = norm.index(phrase) + len(phrase)
            return transcript[idx:].strip()
    return transcript.strip()


def extract_destination(transcript: str, saved_locations: dict = None) -> str:
    """
    Extract a destination from a navigation query.
    Falls back to checking saved_locations dict for keywords like 'home', 'work'.
    """
    norm = transcript.lower()
    saved_locations = saved_locations or {}

    # Check saved location shortcuts
    for label, address in saved_locations.items():
        if label in norm and address:
            return address

    # Try to extract after common navigation phrases
    nav_phrases = [
        "how long to ", "how long to reach ", "drive to ", "get to ",
        "navigate to ", "directions to ", "route to ",
    ]
    for phrase in nav_phrases:
        if phrase in norm:
            idx = norm.index(phrase) + len(phrase)
            return transcript[idx:].strip()

    return ""


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("=== intent_tool self-test ===")

    test_cases = [
        ("What's the weather today?", "weather"),
        ("How long to reach the office?", "navigation"),
        ("Remind me to call the mechanic", "reminder_set"),
        ("What are my reminders for today?", "reminder_get"),
        ("I'm feeling stressed", "emotional"),
        ("Driving mode on", "driving_mode_on"),
        ("Normal mode please", "driving_mode_off"),
        ("What time is it?", "time_date"),
        ("Tell me about black holes", "general"),
        ("I'm falling asleep", "emotional"),  # + safety
    ]

    all_passed = True
    for transcript, expected in test_cases:
        result = classify_intent(transcript)
        status = "✓" if result["intent"] == expected else "✗"
        if result["intent"] != expected:
            all_passed = False
        print(f"  {status} '{transcript}' → {result['intent']} (expected: {expected})")

    print()
    # Test extraction helpers
    r = extract_reminder_text("Remind me to buy groceries after work")
    print(f"Reminder text: '{r}' (expected: 'buy groceries after work')")

    d = extract_destination("How long to reach the airport?")
    print(f"Destination: '{d}' (expected: 'the airport')")

    print(f"\n=== {'All tests passed' if all_passed else 'SOME TESTS FAILED'} ===")
