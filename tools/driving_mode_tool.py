"""
driving_mode_tool.py — Driving mode state manager for RoadMate AI.

Driving mode shortens Claude responses (150 tokens max) and keeps
TTS cadence tight. State is persisted to session_state.json so it
survives restarts.

Single responsibility: manage and expose the driving mode flag.
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.memory_tool import load_session_state, update_session_state

logger = logging.getLogger(__name__)

# Token limits
MAX_TOKENS_DRIVING = int(os.environ.get("CLAUDE_MAX_TOKENS_DRIVING", 150))
MAX_TOKENS_NORMAL = int(os.environ.get("CLAUDE_MAX_TOKENS_NORMAL", 800))


def is_driving_mode_active() -> bool:
    """Return True if driving mode is currently enabled."""
    state = load_session_state()
    return bool(state.get("driving_mode", False))


def enable_driving_mode():
    """Activate driving mode — short responses, focused answers."""
    update_session_state("driving_mode", True)
    logger.info("Driving mode ENABLED.")


def disable_driving_mode():
    """Deactivate driving mode — full responses restored."""
    update_session_state("driving_mode", False)
    logger.info("Driving mode DISABLED.")


def toggle() -> bool:
    """Flip driving mode. Returns the new state (True = on)."""
    current = is_driving_mode_active()
    new_state = not current
    update_session_state("driving_mode", new_state)
    logger.info(f"Driving mode toggled to: {'ON' if new_state else 'OFF'}")
    return new_state


def get_max_tokens() -> int:
    """Return the appropriate Claude max_tokens for current mode."""
    return MAX_TOKENS_DRIVING if is_driving_mode_active() else MAX_TOKENS_NORMAL


def get_driving_mode_system_note() -> str:
    """
    Return a system prompt addition for Claude when driving mode is active.
    Empty string when not in driving mode.
    """
    if is_driving_mode_active():
        return (
            "\n\nDRIVING MODE ACTIVE: The user is currently driving. "
            "Keep ALL responses to 1-2 short sentences maximum. "
            "No lists, no long explanations. Speak naturally and directly. "
            "Prioritize safety — avoid anything that requires sustained attention."
        )
    return ""


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("=== driving_mode_tool self-test ===")

    disable_driving_mode()
    print(f"Active: {is_driving_mode_active()} (expected False)")
    print(f"Max tokens: {get_max_tokens()} (expected {MAX_TOKENS_NORMAL})")

    enable_driving_mode()
    print(f"Active: {is_driving_mode_active()} (expected True)")
    print(f"Max tokens: {get_max_tokens()} (expected {MAX_TOKENS_DRIVING})")
    print(f"System note: '{get_driving_mode_system_note()}'")

    result = toggle()
    print(f"After toggle: {result} (expected False)")

    print("=== All driving_mode_tool tests passed ===")
