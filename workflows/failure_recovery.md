# Workflow: Failure Recovery

**Version:** 1.0
**Objective:** Handle runtime errors gracefully so RoadMate never crashes silently or leaves the user without feedback.

---

## Principles
1. Always speak an error message — never fail silently
2. Offer alternatives when the primary path fails
3. Log all errors to `.tmp/roadmate.log` for debugging
4. Restart the listening loop rather than crashing

---

## Error Categories and Responses

### API Failures (Weather, Maps, Claude)
```
Trigger: requests.ConnectionError, requests.Timeout, anthropic.APIError
Response: Speak specific message per tool (see individual workflows)
Fallback:
  - Weather → "Weather unavailable. Check connection."
  - Maps → "Navigation unavailable. Check connection."
  - Claude → "AI unavailable. I can still help with reminders and time."
```

### Audio Device Failure
```
Trigger: OSError from pyaudio, sr.RequestError
Response: Speak "I can't hear you right now. Check that your microphone is connected."
Log: ERROR with device info
Action: Remain in listening loop with 3-second delay
```

### JSON File Corruption
```
Trigger: json.JSONDecodeError in memory_tool
Response: memory_tool attempts to restore from .tmp/*.bak backup
If backup exists → restore + log WARNING
If no backup → reinitialize with defaults + log ERROR
User notification: "I had a small memory issue but recovered it."
```

### STT Both Engines Fail
```
Trigger: Both vosk and Google STT return empty strings
Response: Speak "I didn't catch that. Try speaking more clearly."
Action: Return to listening (do not count as crash)
```

### Repeated Handler Failure (3x same error)
```
Trigger: Same exception type thrown 3 consecutive times
Response: Speak "I'm having repeated trouble. Please restart me if this continues."
Log: ERROR with full stack trace to .tmp/roadmate.log
Action: Continue listening (do not crash)
```

### Unexpected Exception in main loop
```
Trigger: Any unhandled exception in _handle_one_turn()
Response: Speak "Something went wrong. Ask me something else."
Log: ERROR with full stack trace
Action: Continue to next interaction cycle
```

---

## Recovery Hierarchy
```
1. Try primary path
2. On failure → try fallback (e.g. offline STT after online fails)
3. On second failure → speak graceful error message
4. Log all errors with timestamps to .tmp/roadmate.log
5. Never crash the main loop
6. After 3 consecutive failures → announce degraded state
```

---

## Log File Location
`.tmp/roadmate.log` — rotation not implemented in v1; manual deletion as needed.

## Updating This Workflow
When a new failure mode is discovered:
1. Add the error category above
2. Define the user-facing message
3. Define the fallback behavior
4. Update the relevant tool's try/except block
