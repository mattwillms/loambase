"""
Open-Meteo weather service.

Fetch current conditions + today's forecast for a lat/lon.
Results are cached in Redis for 3 hours (CACHE_TTL_SECONDS).
Each fetch also upserts a daily WeatherCache DB record for historical tracking.

Location note: Garden has no lat/lon fields — callers must pass the garden
owner's User.latitude / User.longitude.
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.logs import WeatherCache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 10_800  # 3 hours

# WMO weather interpretation codes → human-readable string
_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _cache_key(lat: float, lon: float) -> str:
    return f"weather:{lat:.4f}:{lon:.4f}"


def _forecast_cache_key(lat: float, lon: float) -> str:
    return f"forecast:{lat:.4f}:{lon:.4f}"


async def fetch_open_meteo(lat: float, lon: float) -> dict:
    """Raw HTTP call to Open-Meteo. Returns parsed JSON."""
    url = f"{settings.OPEN_METEO_BASE_URL}/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "uv_index",
            "weather_code",
            "soil_temperature_0cm",
        ]),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "forecast_days": 1,
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _parse_raw(raw: dict) -> dict:
    """Map an Open-Meteo response to our domain dict."""
    cur = raw.get("current", {})
    daily = raw.get("daily", {})

    high_temp_f = (daily.get("temperature_2m_max") or [None])[0]
    low_temp_f = (daily.get("temperature_2m_min") or [None])[0]
    weather_code = cur.get("weather_code")
    conditions = _WMO_CONDITIONS.get(weather_code, f"Code {weather_code}") if weather_code is not None else None

    return {
        "latitude": raw["latitude"],
        "longitude": raw["longitude"],
        "date": date.today().isoformat(),
        "current_temp_f": cur.get("temperature_2m"),
        "high_temp_f": high_temp_f,
        "low_temp_f": low_temp_f,
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precip_inches": cur.get("precipitation"),
        "wind_mph": cur.get("wind_speed_10m"),
        "conditions": conditions,
        "uv_index": cur.get("uv_index"),
        "soil_temp_f": cur.get("soil_temperature_0cm"),
        "frost_warning": bool(low_temp_f is not None and low_temp_f < 32.0),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_weather(lat: float, lon: float, redis: Any, db: AsyncSession) -> dict:
    """
    Return weather dict for the given location.

    Hits Redis cache first. On miss: fetches Open-Meteo, caches result for
    CACHE_TTL_SECONDS, and upserts a daily WeatherCache DB record.
    """
    key = _cache_key(lat, lon)

    cached = await redis.get(key)
    if cached is not None:
        logger.debug("weather cache hit: %s", key)
        raw_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
        return json.loads(raw_str)

    logger.debug("weather cache miss: %s — fetching Open-Meteo", key)
    raw = await fetch_open_meteo(lat, lon)
    result = _parse_raw(raw)

    await redis.setex(key, CACHE_TTL_SECONDS, json.dumps(result))
    await _upsert_daily_record(db, result)

    return result


async def get_forecast(lat: float, lon: float, redis: Any, db: AsyncSession) -> list[dict]:
    """
    Return a 3-day precipitation/temperature forecast for the given location.

    Hits Redis cache first (key: forecast:{lat}:{lon}, TTL 3h). On miss: fetches
    Open-Meteo with forecast_days=3 and daily fields only. Does NOT upsert to DB.
    """
    key = _forecast_cache_key(lat, lon)

    cached = await redis.get(key)
    if cached is not None:
        logger.debug("forecast cache hit: %s", key)
        raw_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
        return json.loads(raw_str)

    logger.debug("forecast cache miss: %s — fetching Open-Meteo", key)
    url = f"{settings.OPEN_METEO_BASE_URL}/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "forecast_days": 3,
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()

    daily = raw.get("daily", {})
    dates = daily.get("time", [])
    precip = daily.get("precipitation_sum", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])

    result = []
    for i, d in enumerate(dates):
        low = lows[i] if i < len(lows) else None
        result.append({
            "date": d,
            "precip_inches": precip[i] if i < len(precip) else 0.0,
            "high_temp_f": highs[i] if i < len(highs) else None,
            "low_temp_f": low,
            "frost_warning": bool(low is not None and low < 32.0),
        })

    await redis.setex(key, CACHE_TTL_SECONDS, json.dumps(result))
    return result


async def _upsert_daily_record(db: AsyncSession, data: dict) -> None:
    """Upsert today's WeatherCache row for this location."""
    today = date.today()
    lat = data["latitude"]
    lon = data["longitude"]

    record = await db.scalar(
        select(WeatherCache).where(
            WeatherCache.latitude == lat,
            WeatherCache.longitude == lon,
            WeatherCache.date == today,
        )
    )
    if record is None:
        record = WeatherCache(latitude=lat, longitude=lon, date=today)
        db.add(record)

    record.high_temp_f = data.get("high_temp_f")
    record.low_temp_f = data.get("low_temp_f")
    record.humidity_pct = data.get("humidity_pct")
    record.precip_inches = data.get("precip_inches")
    record.wind_mph = data.get("wind_mph")
    record.conditions = data.get("conditions")
    record.uv_index = data.get("uv_index")
    record.soil_temp_f = data.get("soil_temp_f")
    record.frost_warning = data.get("frost_warning", False)
    record.fetched_at = datetime.now(timezone.utc)

    await db.commit()
