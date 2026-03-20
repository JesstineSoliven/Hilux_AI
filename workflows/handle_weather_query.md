# Workflow: Handle Weather Query

**Version:** 1.0
**Objective:** Respond to weather-related questions with current or forecast data.

---

## Inputs Required
- OPENWEATHER_API_KEY in `.env`
- User's default city (from `user_profile.json` → `default_city`)
- Active internet connection

## Intents That Trigger This Workflow
- `"weather"` from intent_tool

---

## Execution Sequence

```
1. Extract location from transcript (or use profile default_city)
2. Call weather_tool.get_current_weather(location)
3. If API fails (ConnectionError / TimeoutError):
   → speak "I can't reach the weather service right now."
   → exit workflow
4. Call weather_tool.format_for_speech(data, driving_mode)
5. Build Claude system prompt (inject user profile + driving mode)
6. Load last 6 conversation turns for context
7. Call claude_tool.get_response() with weather data as context
8. tts_tool.speak() the Claude-generated response
9. Save conversation turn to history
```

---

## Expected Outputs
- Natural language weather summary spoken aloud
- Driving mode: 1 sentence (temp + condition + rain chance if > 50%)
- Normal mode: 2-3 sentences (temp, humidity, wind, rain chance)

## Failure Handling
- No API key → speak "Weather isn't configured yet. Add an OpenWeatherMap API key to the .env file."
- City not found → speak "I couldn't find weather for that city."
- Network timeout → speak "Weather timed out. Try again shortly."

## Performance Constraints
- API call timeout: 8 seconds
- Full response time target: < 4 seconds
