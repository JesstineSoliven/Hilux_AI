# Workflow: Handle Reminder

**Version:** 1.0
**Objective:** Create or retrieve reminders via voice. Fully offline.

---

## Inputs Required
- `memory/reminders.json` (created automatically)
- No API key required

## Intents That Trigger This Workflow
- `"reminder_set"` — to create a new reminder
- `"reminder_get"` — to read existing reminders

---

## Execution Sequence: Set Reminder

```
1. Call intent_tool.extract_reminder_text(transcript)
2. If extracted text is too short (< 3 chars):
   → speak "What would you like me to remind you about?"
   → capture follow-up utterance
   → use follow-up as reminder text
3. Call reminder_tool.add_reminder(text, due_time=None)
4. Speak confirmation: "Got it. I'll remind you to [text]."
5. No conversation history save needed (transactional)
```

## Execution Sequence: Get Reminders

```
1. Call reminder_tool.get_reminders("today")
2. Call reminder_tool.format_for_speech(reminders, driving_mode)
   Driving mode: "You have N reminders. First one: [text]."
   Normal mode: Full numbered list read aloud
3. Speak the result
4. If no reminders: "You have no reminders right now."
```

---

## Expected Outputs
- Set: Verbal confirmation of the saved reminder
- Get: Spoken list of today's pending reminders

## Failure Handling
- JSON write failure → log error, speak "I couldn't save that reminder. Try again."
- Empty reminders file → "You have no reminders right now."

## Performance Constraints
- All operations are offline and should complete in < 100ms
- Driving mode read: maximum 2 sentences (count + first item only)
