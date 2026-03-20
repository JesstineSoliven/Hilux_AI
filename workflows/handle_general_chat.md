# Workflow: Handle General Chat

**Version:** 1.0
**Objective:** Handle knowledge queries, ideas, casual conversation, learning, and any unclassified intent.

---

## Inputs Required
- ANTHROPIC_API_KEY in `.env`
- User profile from `user_profile.json`
- Conversation history from `conversation_history.json`

## Intents That Trigger This Workflow
- `"general"` (fallback for all unmatched intents)

---

## Execution Sequence

```
1. Load last 10 conversation turns from memory_tool
2. Load user profile for context injection
3. Build system prompt via claude_tool.build_system_prompt():
   - Injects user name, city, goals, routines
   - Adds driving mode constraint if active
4. Determine max_tokens via driving_mode_tool.get_max_tokens()
   - Driving mode: 150 tokens (≈ 1-2 sentences)
   - Normal mode: 800 tokens (full response)
5. Call claude_tool.get_response(transcript, system, history, driving_mode)
6. tts_tool.speak() the response
7. Append both user and assistant turns to conversation history
```

---

## Expected Outputs
- Natural, context-aware conversational response
- Driving mode: 1-2 sentences maximum, no lists
- Normal mode: Full response with appropriate detail level

## Claude Behavior Rules
- Always maintain RoadMate persona (calm, friendly, safety-first)
- In driving mode: end with an offer to continue later if the topic is complex
  Example: "That's a big topic. Want me to go deeper when you're parked?"
- Never provide advice that could endanger driving safety
- Use the user's name occasionally for warmth

## Failure Handling
- Claude API error → speak "I'm having trouble connecting to AI right now. Try again shortly."
- Rate limit → brief pause + retry once, then announce issue
- Empty response → speak "I'm not sure about that. Ask me something else."

## Performance Constraints
- Response time target: < 3 seconds (varies with Claude API latency)
- Max conversation history: 20 turns (rolling window)
