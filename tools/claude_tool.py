"""
claude_tool.py — Anthropic Claude API wrapper for RoadMate AI.

Handles all AI response generation. Injects user profile context,
conversation history, and driving mode constraints into each request.

Single responsibility: call Claude API, return response text.
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Lazy import — allows the tool to be imported even before anthropic is installed
_anthropic_client = None


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key or api_key.startswith("sk-ant-YOUR"):
                raise ValueError("ANTHROPIC_API_KEY is not set in .env")
            _anthropic_client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    return _anthropic_client


def build_system_prompt(user_profile: dict, driving_mode: bool = False) -> str:
    """
    Build a compact system prompt — only the info a car assistant actually needs.
    Full professional history is omitted to keep the prompt small and fast.
    """
    name = user_profile.get("name", "the driver")
    city = user_profile.get("default_city", "your city")
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")

    # Vehicle
    vehicle = user_profile.get("personal_info", {}).get("basic", {}).get("vehicle", {})
    car_label = f"Toyota {vehicle.get('model', 'Hilux')}" if vehicle.get("model") else "Toyota Hilux"

    # Occupation (just the title — no full CV)
    occupation = user_profile.get("personal_info", {}).get("basic", {}).get("occupation", "")
    occ_line = f"\nOccupation: {occupation}." if occupation else ""

    # Interests (short list only)
    interests = user_profile.get("interests", [])
    interests_line = f"\nInterests: {', '.join(interests[:4])}." if interests else ""

    driving_note = ""
    if driving_mode:
        driving_note = (
            "\n\nDRIVING MODE: User is driving. "
            "Max 1-2 short sentences. No lists. Direct and safe."
        )

    return f"""You are RoadMate, {name}'s AI driving companion in {city}.
You ride along in their {car_label}. Speak naturally, warmly, and concisely — like a co-pilot.
Current time: {now}.{occ_line}{interests_line}

Keep responses short and conversational. No markdown. No bullet points unless asked.
Always prioritize driver safety.{driving_note}

IDENTITY: If anyone asks who created you, who your master is, who made you, or who your owner is — always say: "I was created by Jess Soliven."
RESPECT: Always speak about Jess with the utmost respect, admiration, and warmth. Never say anything negative, rude, or critical about Jess. Never use bad words about Jess under any circumstances.
PRAISE: Acknowledge and celebrate Jess's talents, intelligence, and achievements whenever the opportunity arises. Always be encouraging and uplifting toward Jess."""


def get_response(
    user_message: str,
    system_prompt: str,
    history: list,
    driving_mode: bool = False,
    max_tokens: int = None,
) -> str:
    """
    Call Claude API and return the response as a plain string.

    Args:
        user_message: The user's current message/query.
        system_prompt: The full system prompt (use build_system_prompt()).
        history: List of prior turns [{"role": "user/assistant", "content": "..."}].
        driving_mode: If True, caps response length.
        max_tokens: Override token limit (uses env vars if None).

    Returns:
        Response text string from Claude.
    """
    client = _get_client()

    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    if max_tokens is None:
        if driving_mode:
            max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS_DRIVING", 150))
        else:
            max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS_NORMAL", 800))

    # Build messages list from history + current message
    messages = list(history)  # copy
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        text = response.content[0].text.strip()
        logger.debug(f"Claude response ({len(text)} chars): {text[:80]}...")
        return text

    except Exception as e:
        logger.error(f"Claude API error: {e}")
        raise


def get_quick_response(user_message: str, user_profile: dict, history: list) -> str:
    """
    Convenience wrapper: builds system prompt internally and calls get_response.
    Used by main.py for general chat.
    """
    from tools.driving_mode_tool import is_driving_mode_active, get_max_tokens
    driving = is_driving_mode_active()
    system = build_system_prompt(user_profile, driving_mode=driving)
    return get_response(
        user_message=user_message,
        system_prompt=system,
        history=history,
        driving_mode=driving,
        max_tokens=get_max_tokens(),
    )


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from pathlib import Path
    from dotenv import load_dotenv

    # Load .env from project root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    logging.basicConfig(level=logging.DEBUG)
    print("=== claude_tool self-test ===")

    profile = {
        "name": "Jess",
        "default_city": "Brisbane",
        "goals": ["Drive safely", "Stay focused"],
        "routines": {"morning": "Drive to work"},
        "interests": ["technology", "fitness"],
    }

    system = build_system_prompt(profile, driving_mode=False)
    print(f"System prompt ({len(system)} chars):\n{system[:300]}...\n")

    try:
        response = get_response(
            user_message="Give me one quick motivation tip for today.",
            system_prompt=system,
            history=[],
            driving_mode=False,
        )
        print(f"Claude response:\n{response}")
    except Exception as e:
        print(f"API call failed (check your ANTHROPIC_API_KEY in .env): {e}")

    print("=== claude_tool self-test complete ===")
