# Workflow: Wake and Listen

**Version:** 1.0
**Objective:** Complete one full interaction cycle from wake word detection to spoken response.

---

## Inputs Required
- Active microphone
- Configured wake words (from `.env` WAKE_WORDS)
- STT engine (Vosk offline or Google online)
- TTS engine (edge-tts or pyttsx3)

## Context Assumptions
- Agent is in passive listening state (background thread running)
- User is in or near the vehicle
- Session state is loaded

---

## Execution Sequence

```
1. wake_word_tool background thread detects wake phrase
2. Callback fires → _on_wake() sets wake_event flag
3. Agent wakes up → speaks "Yes?" acknowledgment
4. stt_tool.capture_audio() records 6-second window
5. stt_tool.transcribe() returns text (offline first, online fallback)
6. If transcript is empty → speak "I didn't catch that" → return to step 1
7. Check for safety override phrases → handle immediately if found
8. intent_tool.classify_intent() classifies the transcript
9. Agent routes to the appropriate handler:
   - weather → _handle_weather()
   - navigation → _handle_navigation()
   - reminder_set → _handle_reminder_set()
   - reminder_get → _handle_reminder_get()
   - driving_mode_on/off → _handle_driving_mode()
   - emotional → _handle_emotional()
   - time_date → _handle_time_date()
   - general → _handle_general()
10. Handler executes, generates response text
11. tts_tool.speak() outputs response
12. Conversation turn appended to conversation_history.json
13. Agent returns to passive listening (step 1)
```

---

## Expected Outputs
- Spoken response delivered within 2-3 seconds of wake word
- Conversation turn saved to memory

## Failure Handling
- Audio capture fails → "Something went wrong, please try again"
- STT both engines fail → "I'm having trouble hearing you. Check the microphone."
- Handler throws exception → "Something went wrong. Ask me something else."
- 3 consecutive errors → log to `.tmp/roadmate.log`, announce issue

## Performance Constraints
- Wake word detection target: < 500ms
- Full response delivery target: < 3 seconds (API-dependent)
- Driving mode responses must be ≤ 2 sentences
