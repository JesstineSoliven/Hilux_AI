"""
weather_tool.py — OpenWeatherMap API wrapper for RoadMate AI.

Fetches current weather and short-term forecast. Returns structured
data dicts and pre-formatted natural language strings for TTS.

Single responsibility: fetch and format weather data.
"""

import os
import sys
import logging
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
DEFAULT_CITY = os.environ.get("OPENWEATHER_DEFAULT_CITY", "Manila")
UNITS = os.environ.get("OPENWEATHER_UNITS", "metric")

_BASE_URL = "https://api.openweathermap.org/data/2.5"
_REQUEST_TIMEOUT = 8  # seconds


def _unit_symbol() -> str:
    return "°C" if UNITS == "metric" else "°F"


def _check_api_key():
    if not OPENWEATHER_API_KEY or OPENWEATHER_API_KEY.startswith("YOUR_"):
        raise ValueError(
            "OPENWEATHER_API_KEY not set. Add it to your .env file. "
            "Get a free key at openweathermap.org"
        )


def get_current_weather(location: str = None) -> dict:
    """
    Fetch current weather for a city.

    Args:
        location: City name (e.g. 'Brisbane'). Uses DEFAULT_CITY if not provided.

    Returns:
        Dict with keys: temp, feels_like, condition, description,
                        humidity, wind_speed, city, unit, icon
    """
    _check_api_key()
    city = location or DEFAULT_CITY

    try:
        response = requests.get(
            f"{_BASE_URL}/weather",
            params={
                "q": city,
                "appid": OPENWEATHER_API_KEY,
                "units": UNITS,
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        return {
            "city": data.get("name", city),
            "temp": round(data["main"]["temp"]),
            "feels_like": round(data["main"]["feels_like"]),
            "condition": data["weather"][0]["main"],
            "description": data["weather"][0]["description"].capitalize(),
            "humidity": data["main"]["humidity"],
            "wind_speed": round(data["wind"]["speed"]),
            "unit": _unit_symbol(),
            "icon": data["weather"][0]["icon"],
        }

    except requests.exceptions.ConnectionError:
        raise ConnectionError("No internet connection — weather unavailable.")
    except requests.exceptions.Timeout:
        raise TimeoutError("Weather API timed out. Try again shortly.")
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            raise ValueError("Invalid OpenWeatherMap API key. Check your .env file.")
        elif response.status_code == 404:
            raise ValueError(f"City '{city}' not found. Try a different city name.")
        raise RuntimeError(f"Weather API error: {e}")


def get_forecast(location: str = None, hours_ahead: int = 3) -> dict:
    """
    Fetch the nearest forecast entry for the given number of hours ahead.

    Args:
        location: City name. Uses DEFAULT_CITY if not provided.
        hours_ahead: How many hours into the future to look (3, 6, 9...).

    Returns:
        Dict similar to get_current_weather plus a 'time' key.
    """
    _check_api_key()
    city = location or DEFAULT_CITY

    try:
        response = requests.get(
            f"{_BASE_URL}/forecast",
            params={
                "q": city,
                "appid": OPENWEATHER_API_KEY,
                "units": UNITS,
                "cnt": max(1, hours_ahead // 3 + 1),  # API returns 3-hour intervals
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        # Pick the entry closest to hours_ahead from now
        entry = data["list"][min(hours_ahead // 3, len(data["list"]) - 1)]
        dt = datetime.fromtimestamp(entry["dt"])

        return {
            "city": data["city"]["name"],
            "time": dt.strftime("%I:%M %p"),
            "temp": round(entry["main"]["temp"]),
            "feels_like": round(entry["main"]["feels_like"]),
            "condition": entry["weather"][0]["main"],
            "description": entry["weather"][0]["description"].capitalize(),
            "humidity": entry["main"]["humidity"],
            "wind_speed": round(entry["wind"]["speed"]),
            "unit": _unit_symbol(),
            "pop": round(entry.get("pop", 0) * 100),  # Probability of precipitation %
        }

    except requests.exceptions.ConnectionError:
        raise ConnectionError("No internet connection — forecast unavailable.")
    except requests.exceptions.Timeout:
        raise TimeoutError("Forecast API timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Forecast API error: {e}")


def format_for_speech(weather_dict: dict, driving_mode: bool = False) -> str:
    """
    Convert a weather dict to a natural language string suitable for TTS.

    Driving mode: very short (1 sentence).
    Normal mode: 2-3 sentences with more detail.
    """
    if not weather_dict:
        return "I couldn't get the weather right now."

    city = weather_dict.get("city", "your area")
    temp = weather_dict.get("temp", "?")
    unit = weather_dict.get("unit", "°C")
    condition = weather_dict.get("condition", "Unknown")
    description = weather_dict.get("description", "")
    humidity = weather_dict.get("humidity")
    wind = weather_dict.get("wind_speed")
    pop = weather_dict.get("pop")  # Only in forecast

    if driving_mode:
        text = f"It's {temp}{unit} in {city}, {description}."
        if pop and pop > 50:
            text += f" Chance of rain: {pop}%."
        return text

    # Normal mode — more detail
    text = f"Right now in {city} it's {temp}{unit}, {description}."
    if humidity:
        text += f" Humidity is {humidity}%."
    if wind:
        text += f" Wind speed is {wind} kilometres per hour."
    if pop is not None:
        text += f" There's a {pop}% chance of rain."

    return text


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.DEBUG)

    print("=== weather_tool self-test ===")
    city = DEFAULT_CITY
    print(f"Fetching weather for: {city}\n")

    try:
        current = get_current_weather(city)
        print(f"Current weather data: {current}")
        print(f"\nSpeech (driving): {format_for_speech(current, driving_mode=True)}")
        print(f"Speech (normal):  {format_for_speech(current, driving_mode=False)}")

        print("\nFetching 3-hour forecast...")
        forecast = get_forecast(city, hours_ahead=3)
        print(f"Forecast data: {forecast}")
        print(f"Speech (driving): {format_for_speech(forecast, driving_mode=True)}")

    except Exception as e:
        print(f"Error: {e}")
        print("(Check OPENWEATHER_API_KEY in your .env file)")

    print("=== weather_tool self-test complete ===")
