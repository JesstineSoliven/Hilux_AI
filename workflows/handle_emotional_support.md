# Workflow: Handle Emotional Support

**Version:** 1.0
**Objective:** Respond to stress, fatigue, anxiety, or motivation requests with empathy and safety awareness.

---

## Inputs Required
- ANTHROPIC_API_KEY in `.env`
- User profile (name used for personalization)

## Intents That Trigger This Workflow
- `"emotional"` from intent_tool
- Triggered by keywords: stressed, tired, anxious, exhausted, motivate, struggling, bored, keep me awake

---

## Safety Override (Highest Priority)

Before routing to Claude, check for extreme fatigue phrases:
- "falling asleep", "can't keep my eyes open", "about to pass out"

If detected → BYPASS Claude entirely and speak immediately:
```
"Please pull over somewhere safe right now. Your safety matters
more than arriving on time. Take a break — I'll be here when you're ready."
```
No further processing. Return to listening.

---

## Execution Sequence (Non-safety)

```
1. Detect emotional keyword category from transcript:
   - Fatigue/tired → breathing + rest suggestion
   - Stressed/anxious → calming response
   - Motivation needed → encouraging message
   - Bored → engaging conversation prompt
2. Build empathy-enhanced system prompt:
   base = claude_tool.build_system_prompt(profile, driving_mode)
   + emotional support addendum (see below)
3. Load last 4 conversation turns (minimal history for speed)
4. Call claude_tool.get_response() with:
   - max_tokens = 120 (always short, even in normal mode)
   - driving_mode = True (enforce brevity for safety)
5. Speak the response
6. Save conversation turn
```

## Empathy System Prompt Addendum
```
EMOTIONAL SUPPORT MODE: The user is experiencing emotional difficulty
while driving. Be warm, calm, and very brief. Acknowledge their feeling
in one sentence, then offer one supportive thought or action.
Never be dismissive. Never use lists. Speak like a caring friend.
If they mention extreme fatigue or danger, tell them to pull over immediately.
```

---

## Expected Outputs
- Acknowledgment + one supportive action/thought (2 sentences max)
- Warm, human tone — not robotic or clinical
- No bullet lists, no long explanations

## Sample Responses
- Stressed: "Take a slow deep breath. You're handling things well — one step at a time."
- Tired: "You sound tired. If you can, find a safe spot to pull over and rest for a few minutes."
- Motivation: "You've got this, Jess. Every kilometre closer is progress."
- Bored: "Long drive? Tell me what's on your mind and we'll talk it through."

## Failure Handling
- Claude API error → speak pre-set motivational line from local fallback list
- Fallback lines: ["You're doing great.", "Stay focused, you've got this.", "Take it one turn at a time."]

## Performance Constraints
- Always max 120 tokens
- Response must be ≤ 2 sentences
- Safety override response must play within 500ms (no API call)
