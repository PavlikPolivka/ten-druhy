"""Current information from outside: DuckDuckGo web search and Open-Meteo weather (both free, no keys).

(Gemini's Google Search grounding isn't available on the free tier.)
"""

import json
import time
import urllib.parse
import urllib.request
from functools import lru_cache

from app import config

WMO = {0: "jasno", 1: "skoro jasno", 2: "polojasno", 3: "zataženo", 45: "mlha", 48: "mrznoucí mlha",
       51: "slabé mrholení", 53: "mrholení", 55: "silné mrholení", 61: "slabý déšť", 63: "déšť", 65: "silný déšť",
       66: "mrznoucí déšť", 67: "silný mrznoucí déšť", 71: "slabé sněžení", 73: "sněžení", 75: "silné sněžení",
       77: "sněhová zrna", 80: "přeháňky", 81: "silné přeháňky", 82: "průtrž mračen", 85: "sněhové přeháňky",
       86: "silné sněhové přeháňky", 95: "bouřka", 96: "bouřka s kroupami", 99: "silná bouřka s kroupami"}
DAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


def _get(url: str, params: dict, attempts: int = 3) -> dict:
    for i in range(attempts):  # Open-Meteo occasionally answers 503
        try:
            with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=10) as r:
                return json.load(r)
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(1 + i)


def search(query: str, n: int = 5) -> list[dict]:
    from ddgs import DDGS  # unofficial; may rate-limit — callers treat failure as "no results"

    hits = DDGS().text(query, region="cz-cz", max_results=n)
    return [{"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")} for h in hits]


@lru_cache(maxsize=64)
def geocode(place: str) -> tuple[str, float, float] | None:
    res = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": place, "count": 1, "language": "cs"}).get("results")
    return (res[0]["name"], res[0]["latitude"], res[0]["longitude"]) if res else None


def weather(place: str | None = None) -> str:
    """Current conditions + 3-day forecast as a short Czech text block."""
    loc = geocode(place or config.HOME_PLACE) or geocode(config.HOME_PLACE)
    name, lat, lon = loc
    f = _get("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Prague", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,weather_code",
    })
    c, d = f["current"], f["daily"]
    lines = [f"Počasí {name} – teď: {WMO.get(c['weather_code'], '?')}, {c['temperature_2m']:.0f} °C "
             f"(pocitově {c['apparent_temperature']:.0f}), vítr {c['wind_speed_10m']:.0f} km/h."]
    from datetime import date
    for i, day in enumerate(d["time"]):
        dd = date.fromisoformat(day)
        lines.append(f"{DAYS[dd.weekday()]} {dd.day}. {dd.month}.: {WMO.get(d['weather_code'][i], '?')}, "
                     f"{d['temperature_2m_min'][i]:.0f}–{d['temperature_2m_max'][i]:.0f} °C, "
                     f"srážky {d['precipitation_probability_max'][i] or 0} % ({d['precipitation_sum'][i] or 0} mm)")
    return "\n".join(lines)
