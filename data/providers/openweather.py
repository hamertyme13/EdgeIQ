"""OpenWeather provider for outdoor-sport conditions."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from data.providers.cache import get_json


_BASE = "https://api.openweathermap.org/data/2.5/weather"
_TEAM_LOCATIONS = {
    "ARI": "Phoenix,US",
    "ATL": "Atlanta,US",
    "BAL": "Baltimore,US",
    "BOS": "Boston,US",
    "BUF": "Buffalo,US",
    "CAR": "Charlotte,US",
    "CHC": "Chicago,US",
    "CHI": "Chicago,US",
    "CIN": "Cincinnati,US",
    "CLE": "Cleveland,US",
    "COL": "Denver,US",
    "DAL": "Dallas,US",
    "DEN": "Denver,US",
    "DET": "Detroit,US",
    "GB": "Green Bay,US",
    "HOU": "Houston,US",
    "KC": "Kansas City,US",
    "LAA": "Anaheim,US",
    "LAD": "Los Angeles,US",
    "LV": "Las Vegas,US",
    "MIA": "Miami,US",
    "MIL": "Milwaukee,US",
    "MIN": "Minneapolis,US",
    "NE": "Foxborough,US",
    "NO": "New Orleans,US",
    "NYG": "East Rutherford,US",
    "NYJ": "East Rutherford,US",
    "NYY": "New York,US",
    "NYM": "New York,US",
    "OAK": "Oakland,US",
    "PHI": "Philadelphia,US",
    "PIT": "Pittsburgh,US",
    "SEA": "Seattle,US",
    "SF": "Santa Clara,US",
    "STL": "St. Louis,US",
    "TB": "Tampa,US",
    "TEN": "Nashville,US",
    "WAS": "Washington,US",
}


def fetch_weather_for_game(game: str, sport: str) -> dict | None:
    if sport.upper() not in {"MLB", "NFL"}:
        return None
    location = _location_from_game(game)
    if not location:
        return None
    return fetch_current_weather(location)


def fetch_current_weather(location: str) -> dict | None:
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        return None

    url = f"{_BASE}?q={quote_plus(location)}&appid={api_key}&units=imperial"
    try:
        data = get_json(url, timeout=12, ttl_seconds=900).data
    except RuntimeError:
        return None
    wind = data.get("wind", {})
    main = data.get("main", {})
    weather = (data.get("weather") or [{}])[0]
    return {
        "location": location,
        "temp_f": main.get("temp"),
        "wind_mph": wind.get("speed"),
        "condition": weather.get("main", ""),
        "description": weather.get("description", ""),
    }


def weather_signal(weather: dict | None) -> dict | None:
    if not weather:
        return None
    wind = float(weather.get("wind_mph") or 0)
    condition = str(weather.get("condition") or "").lower()
    if wind >= 15:
        return {"risk": "wind", "impact": -3.0, "message": f"Wind {wind:.0f} mph may suppress outdoor production."}
    if any(term in condition for term in ("rain", "snow", "storm")):
        return {"risk": "precipitation", "impact": -3.0, "message": f"{weather.get('condition')} conditions may add variance."}
    return None


def _location_from_game(game: str) -> str:
    token = str(game or "").strip().upper()
    if not token:
        return ""
    parts = [part.strip() for separator in ("@", " at ", " vs ") for part in token.split(separator)]
    for part in reversed(parts):
        if part in _TEAM_LOCATIONS:
            return _TEAM_LOCATIONS[part]
    return _TEAM_LOCATIONS.get(token, "")
