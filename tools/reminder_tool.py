"""
reminder_tool.py — Reminder and task CRUD for RoadMate AI.

All reminders are stored in memory/reminders.json.
Fully offline — no API required.

Single responsibility: create, read, update, and delete reminders.
"""

import os
import sys
import uuid
import logging
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.memory_tool import _read_json, _write_json, MEMORY_DIR

logger = logging.getLogger(__name__)

_REMINDERS_PATH = MEMORY_DIR / "reminders.json"


def _load() -> list:
    """Load reminders list from JSON."""
    data = _read_json(_REMINDERS_PATH)
    return data.get("reminders", [])


def _save(reminders: list):
    """Write reminders list to JSON."""
    _write_json(_REMINDERS_PATH, {"reminders": reminders})


def add_reminder(text: str, due_time: str = None) -> dict:
    """
    Create a new reminder.

    Args:
        text: The reminder content (e.g. 'Call the mechanic').
        due_time: ISO format datetime string (e.g. '2026-03-17T14:00:00').
                  If None, the reminder has no specific due time.

    Returns:
        The newly created reminder dict.
    """
    reminder = {
        "id": str(uuid.uuid4())[:8],
        "text": text.strip(),
        "created_at": datetime.now().isoformat(),
        "due_at": due_time,
        "completed": False,
    }
    reminders = _load()
    reminders.append(reminder)
    _save(reminders)
    logger.info(f"Added reminder: '{text}' (id: {reminder['id']})")
    return reminder


def get_reminders(filter_by: str = "all") -> list:
    """
    Retrieve reminders.

    Args:
        filter_by: 'today', 'upcoming', 'all', or 'pending'

    Returns:
        Filtered list of reminder dicts.
    """
    all_reminders = _load()
    today_str = date.today().isoformat()

    if filter_by == "pending":
        return [r for r in all_reminders if not r.get("completed")]

    if filter_by == "today":
        result = []
        for r in all_reminders:
            if r.get("completed"):
                continue
            due = r.get("due_at")
            if due is None:
                result.append(r)  # No due time → always relevant
            elif due.startswith(today_str):
                result.append(r)
        return result

    if filter_by == "upcoming":
        now = datetime.now().isoformat()
        result = []
        for r in all_reminders:
            if r.get("completed"):
                continue
            due = r.get("due_at")
            if due and due >= now:
                result.append(r)
        return sorted(result, key=lambda r: r.get("due_at", ""))

    # 'all' — return everything not completed
    return [r for r in all_reminders if not r.get("completed")]


def check_due_reminders() -> list:
    """
    Return reminders that are due now (within the last 30 minutes).
    Used for startup notification.
    """
    now = datetime.now()
    result = []
    for r in _load():
        if r.get("completed"):
            continue
        due_str = r.get("due_at")
        if not due_str:
            continue
        try:
            due_dt = datetime.fromisoformat(due_str)
            diff_minutes = (now - due_dt).total_seconds() / 60
            if -5 <= diff_minutes <= 30:  # Due in next 5 min or past 30 min
                result.append(r)
        except ValueError:
            continue
    return result


def complete_reminder(reminder_id: str) -> bool:
    """
    Mark a reminder as completed by ID.

    Returns:
        True if found and marked, False if not found.
    """
    reminders = _load()
    for r in reminders:
        if r["id"] == reminder_id:
            r["completed"] = True
            r["completed_at"] = datetime.now().isoformat()
            _save(reminders)
            logger.info(f"Reminder completed: {reminder_id}")
            return True
    logger.warning(f"Reminder not found: {reminder_id}")
    return False


def delete_reminder(reminder_id: str) -> bool:
    """
    Permanently delete a reminder by ID.

    Returns:
        True if deleted, False if not found.
    """
    reminders = _load()
    new_list = [r for r in reminders if r["id"] != reminder_id]
    if len(new_list) == len(reminders):
        return False
    _save(new_list)
    logger.info(f"Reminder deleted: {reminder_id}")
    return True


def format_for_speech(reminders: list, driving_mode: bool = False) -> str:
    """
    Format a list of reminders into a natural TTS string.

    Driving mode: count + first item only.
    Normal mode: full list read aloud.
    """
    if not reminders:
        return "You have no reminders right now."

    count = len(reminders)

    if driving_mode:
        first = reminders[0]["text"]
        if count == 1:
            return f"You have one reminder: {first}."
        return f"You have {count} reminders. First one: {first}."

    if count == 1:
        return f"You have one reminder: {reminders[0]['text']}."

    lines = [f"You have {count} reminders."]
    for i, r in enumerate(reminders, 1):
        due = ""
        if r.get("due_at"):
            try:
                dt = datetime.fromisoformat(r["due_at"])
                due = f" at {dt.strftime('%I:%M %p')}"
            except ValueError:
                pass
        lines.append(f"Number {i}: {r['text']}{due}.")

    return " ".join(lines)


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.DEBUG)

    print("=== reminder_tool self-test ===")

    # Add reminders
    r1 = add_reminder("Call the mechanic about the service")
    r2 = add_reminder("Pick up groceries", due_time=f"{date.today().isoformat()}T17:00:00")
    r3 = add_reminder("Email the project report", due_time=f"{date.today().isoformat()}T09:00:00")

    print(f"Added: {r1['id']}, {r2['id']}, {r3['id']}")

    # Get today's reminders
    today = get_reminders("today")
    print(f"\nToday's reminders ({len(today)}):")
    for r in today:
        print(f"  - [{r['id']}] {r['text']} (due: {r.get('due_at', 'anytime')})")

    # Speech formatting
    print(f"\nSpeech (driving): {format_for_speech(today, driving_mode=True)}")
    print(f"Speech (normal):  {format_for_speech(today, driving_mode=False)}")

    # Complete one
    complete_reminder(r1["id"])
    print(f"\nAfter completing {r1['id']}:")
    remaining = get_reminders("pending")
    print(f"Pending count: {len(remaining)}")

    # Clean up test data
    for rid in [r1["id"], r2["id"], r3["id"]]:
        delete_reminder(rid)
    print("\nCleaned up test reminders.")
    print("=== reminder_tool self-test complete ===")
