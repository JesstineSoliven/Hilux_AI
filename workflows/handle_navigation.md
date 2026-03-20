# Workflow: Handle Navigation Query

**Version:** 1.0
**Objective:** Provide travel time, ETA, and traffic conditions for a route.

---

## Inputs Required
- GOOGLE_MAPS_API_KEY in `.env`
- User's saved_locations (from `user_profile.json`)
- Active internet connection

## Intents That Trigger This Workflow
- `"navigation"` from intent_tool

---

## Execution Sequence

```
1. Call intent_tool.extract_destination(transcript, saved_locations)
2. If destination is empty or vague:
   → speak "Where are you heading?"
   → capture follow-up utterance
   → re-run extract_destination
3. Resolve saved location shortcuts (e.g. "home", "work", "gym") to addresses
4. Set origin = user's default_city (or last known location if available)
5. Call maps_tool.get_travel_time(origin, destination)
6. If API fails → speak "I can't reach maps right now."
7. Call maps_tool.format_for_speech(data, driving_mode)
8. Speak the formatted response
   Driving mode: "About [ETA] to [destination]. Traffic is [level]."
   Normal mode: Full route + distance + delay info
```

---

## Expected Outputs
- ETA with current traffic conditions
- Traffic level: clear / light / moderate / heavy
- Distance in kilometres

## Failure Handling
- Route not found → "I couldn't find a route to that destination."
- No API key → "Maps navigation isn't configured yet."
- Unknown location shortcut → Ask follow-up for full address

## Performance Constraints
- API call timeout: 10 seconds
- Must not attempt navigation while driving_mode is active unless user explicitly asks
