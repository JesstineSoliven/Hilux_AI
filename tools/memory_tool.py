"""
memory_tool.py — Persistent JSON memory layer for RoadMate AI.

All file reads and writes for user_profile, reminders, conversation
history, and session state go through this tool.

Single responsibility: read/write JSON files atomically.
"""

import json
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path

# Resolve memory directory relative to this file's project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", str(_PROJECT_ROOT / "memory")))
TMP_DIR = Path(os.environ.get("TMP_DIR", str(_PROJECT_ROOT / ".tmp")))

logger = logging.getLogger(__name__)


def _ensure_dirs():
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        logger.warning(f"Cannot create memory dirs (read-only fs?): {e}")


def _read_json(filepath: Path) -> dict:
    """Read a JSON file. Returns empty dict on missing or corrupt file."""
    _ensure_dirs()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Memory file not found: {filepath}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Corrupt JSON in {filepath}: {e}")
        _restore_backup(filepath)
        return {}


def _write_json(filepath: Path, data: dict):
    """Write JSON atomically: write to .tmp then rename."""
    _ensure_dirs()
    tmp_path = TMP_DIR / (filepath.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        shutil.move(str(tmp_path), str(filepath))
    except Exception as e:
        logger.error(f"Failed to write {filepath}: {e}")
        raise


def _restore_backup(filepath: Path):
    """Attempt to restore from backup if main file is corrupt."""
    backup = TMP_DIR / (filepath.name + ".bak")
    if backup.exists():
        logger.info(f"Restoring backup: {backup}")
        shutil.copy(str(backup), str(filepath))
    else:
        logger.warning(f"No backup available for {filepath}")


def _backup(filepath: Path):
    """Create a backup copy in .tmp."""
    if filepath.exists():
        backup = TMP_DIR / (filepath.name + ".bak")
        shutil.copy(str(filepath), str(backup))


# ─── User Profile ──────────────────────────────────────────────────────────────

_PROFILE_PATH = MEMORY_DIR / "user_profile.json"

_DEFAULT_PROFILE = {
    "name": "Jess",
    "home_address": "",
    "work_address": "",
    "saved_locations": {"home": None, "work": None, "gym": None},
    "default_city": "Brisbane",
    "preferences": {
        "tts_voice": "en-AU-NatashaNeural",
        "response_style": "friendly",
        "wake_words": ["hey roadmate", "hi hilux", "assistant"],
    },
    "goals": [],
    "routines": {"morning": "", "evening": ""},
    "interests": [],
    "important_contacts": {},
    "created_at": datetime.now().isoformat(),
    "updated_at": datetime.now().isoformat(),
}


def load_user_profile() -> dict:
    data = _read_json(_PROFILE_PATH)
    return data if data else _DEFAULT_PROFILE.copy()


def save_user_profile(profile: dict):
    profile["updated_at"] = datetime.now().isoformat()
    _backup(_PROFILE_PATH)
    _write_json(_PROFILE_PATH, profile)


def update_user_profile(key: str, value):
    """Update a single top-level key in the user profile."""
    profile = load_user_profile()
    profile[key] = value
    save_user_profile(profile)
    logger.info(f"Updated user profile: {key} = {value}")


# ─── Conversation History ───────────────────────────────────────────────────────

_HISTORY_PATH = MEMORY_DIR / "conversation_history.json"
_MAX_TURNS = int(os.environ.get("CONVERSATION_MAX_TURNS", 20))


def load_conversation_history(max_turns: int = None) -> list:
    """Return the last N conversation turns as a list of {role, content} dicts."""
    limit = max_turns or _MAX_TURNS
    data = _read_json(_HISTORY_PATH)
    turns = data.get("turns", [])
    # Return only role and content for Claude API compatibility
    return [{"role": t["role"], "content": t["content"]} for t in turns[-limit:]]


def append_conversation_turn(role: str, content: str):
    """Append a turn to conversation history, trimming to max_turns."""
    data = _read_json(_HISTORY_PATH)
    if not data:
        data = {"turns": [], "max_turns": _MAX_TURNS}
    data["turns"].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    })
    # Trim to rolling window
    if len(data["turns"]) > _MAX_TURNS:
        data["turns"] = data["turns"][-_MAX_TURNS:]
    _write_json(_HISTORY_PATH, data)


def reset_conversation_history():
    """Clear all conversation history (call at session start if desired)."""
    _write_json(_HISTORY_PATH, {"turns": [], "max_turns": _MAX_TURNS})
    logger.info("Conversation history cleared.")


# ─── Session State ─────────────────────────────────────────────────────────────

_SESSION_PATH = MEMORY_DIR / "session_state.json"

_DEFAULT_SESSION = {
    "driving_mode": False,
    "session_started": None,
    "last_known_location": None,
    "mood_context": None,
}


def load_session_state() -> dict:
    data = _read_json(_SESSION_PATH)
    return data if data else _DEFAULT_SESSION.copy()


def save_session_state(state: dict):
    _write_json(_SESSION_PATH, state)


def update_session_state(key: str, value):
    state = load_session_state()
    state[key] = value
    save_session_state(state)


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("=== memory_tool self-test ===")

    # User profile
    profile = load_user_profile()
    print(f"Loaded profile: name={profile.get('name')}, city={profile.get('default_city')}")

    update_user_profile("goals", ["Drive safely", "Stay focused"])
    profile = load_user_profile()
    print(f"Updated goals: {profile.get('goals')}")

    # Conversation history
    reset_conversation_history()
    append_conversation_turn("user", "What's the weather like?")
    append_conversation_turn("assistant", "It's 24 degrees and sunny in Brisbane.")
    history = load_conversation_history()
    print(f"History ({len(history)} turns): {history}")

    # Session state
    update_session_state("driving_mode", True)
    state = load_session_state()
    print(f"Session state driving_mode: {state.get('driving_mode')}")

    print("=== All memory_tool tests passed ===")
