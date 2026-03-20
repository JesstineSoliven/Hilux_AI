"""
maps_tool.py — Google Maps API wrapper for RoadMate AI.

Provides travel time, traffic conditions, and ETA for navigation
queries. Resolves saved location shortcuts (home, work, gym).

Single responsibility: fetch and format travel/traffic data.
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
DEFAULT_CITY = os.environ.get("OPENWEATHER_DEFAULT_CITY", "Manila")

_gmaps_client = None


def _get_client():
    global _gmaps_client
    if _gmaps_client is None:
        if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY.startswith("YOUR_"):
            raise ValueError(
                "GOOGLE_MAPS_API_KEY not set. Add it to your .env file. "
                "Get a key at console.cloud.google.com"
            )
        try:
            import googlemaps
            _gmaps_client = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        except ImportError:
            raise RuntimeError("googlemaps not installed. Run: pip install googlemaps")
    return _gmaps_client


def resolve_location(label: str, saved_locations: dict) -> str:
    """
    Resolve a location label to an address.
    Checks saved_locations dict for shortcuts like 'home', 'work'.
    Returns the original label if no match found.
    """
    if not label:
        return ""
    label_lower = label.lower().strip()
    for key, address in (saved_locations or {}).items():
        if key.lower() == label_lower and address:
            logger.debug(f"Resolved '{label}' → '{address}'")
            return address
    return label


def get_travel_time(origin: str, destination: str) -> dict:
    """
    Get travel time with and without traffic for a route.

    Args:
        origin: Starting address or city.
        destination: Destination address or city.

    Returns:
        Dict with: duration_normal, duration_traffic, distance, traffic_level, origin, destination
    """
    client = _get_client()

    try:
        from datetime import datetime
        result = client.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            departure_time=datetime.now(),
            traffic_model="best_guess",
            units="metric",
        )

        element = result["rows"][0]["elements"][0]

        if element["status"] != "OK":
            raise ValueError(f"Route not found: {element['status']}")

        duration_normal_sec = element["duration"]["value"]
        duration_traffic_sec = element.get(
            "duration_in_traffic", element["duration"]
        )["value"]
        distance_m = element["distance"]["value"]

        # Determine traffic level
        delay = duration_traffic_sec - duration_normal_sec
        if delay < 60:
            traffic_level = "clear"
        elif delay < 300:
            traffic_level = "light"
        elif delay < 600:
            traffic_level = "moderate"
        else:
            traffic_level = "heavy"

        return {
            "origin": origin,
            "destination": destination,
            "duration_normal": _format_duration(duration_normal_sec),
            "duration_traffic": _format_duration(duration_traffic_sec),
            "duration_traffic_seconds": duration_traffic_sec,
            "distance": _format_distance(distance_m),
            "traffic_level": traffic_level,
            "delay_minutes": round(delay / 60),
        }

    except Exception as e:
        logger.error(f"Maps API error: {e}")
        raise


def get_traffic_conditions(location: str = None) -> str:
    """
    Return a plain-English traffic summary for a location area.
    Uses a short local loop route as a proxy for area traffic.
    """
    city = location or DEFAULT_CITY
    try:
        # Use city center to CBD as a proxy route
        data = get_travel_time(city, f"{city} CBD")
        level = data.get("traffic_level", "unknown")
        delay = data.get("delay_minutes", 0)

        if level == "clear":
            return f"Traffic around {city} is flowing well."
        elif level == "light":
            return f"Traffic around {city} is light, about {delay} minute delay."
        elif level == "moderate":
            return f"Moderate traffic around {city}, expect about {delay} minutes extra."
        else:
            return f"Heavy traffic near {city}, delays of {delay} minutes or more."

    except Exception as e:
        logger.error(f"Traffic conditions error: {e}")
        return "I couldn't get traffic info right now."


def _format_duration(seconds: int) -> str:
    """Convert seconds to human-readable duration string."""
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minute{'s' if mins != 1 else ''}"


def _format_distance(meters: int) -> str:
    """Convert meters to human-readable distance string."""
    if meters < 1000:
        return f"{meters} metres"
    km = meters / 1000
    return f"{km:.1f} kilometres"


def format_for_speech(travel_dict: dict, driving_mode: bool = False) -> str:
    """
    Convert travel data dict to natural language for TTS.

    Driving mode: ultra-short ETA only.
    Normal mode: ETA + traffic level + distance.
    """
    if not travel_dict:
        return "I couldn't get directions right now."

    dest = travel_dict.get("destination", "your destination")
    eta = travel_dict.get("duration_traffic", "unknown")
    traffic = travel_dict.get("traffic_level", "unknown")
    delay = travel_dict.get("delay_minutes", 0)
    distance = travel_dict.get("distance", "")

    if driving_mode:
        return f"About {eta} to {dest}. Traffic is {traffic}."

    text = f"It'll take about {eta} to reach {dest}, covering {distance}."
    if traffic == "clear":
        text += " Traffic is flowing well."
    elif traffic in ("moderate", "heavy"):
        text += f" There's {traffic} traffic — you're looking at about {delay} minutes extra."
    return text


# ─── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.DEBUG)

    print("=== maps_tool self-test ===")

    origin = DEFAULT_CITY
    destination = f"{DEFAULT_CITY} Airport"
    print(f"Route: {origin} → {destination}\n")

    try:
        data = get_travel_time(origin, destination)
        print(f"Travel data: {data}")
        print(f"\nSpeech (driving): {format_for_speech(data, driving_mode=True)}")
        print(f"Speech (normal):  {format_for_speech(data, driving_mode=False)}")

        print(f"\nTraffic conditions: {get_traffic_conditions(DEFAULT_CITY)}")

    except Exception as e:
        print(f"Error: {e}")
        print("(Check GOOGLE_MAPS_API_KEY in your .env file)")

    print("=== maps_tool self-test complete ===")
