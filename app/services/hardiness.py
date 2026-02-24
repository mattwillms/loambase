"""
PHZMapi hardiness zone service.

Fetch USDA hardiness zone for a ZIP code from phzmapi.org.
Results are cached in Redis for 30 days — zone data is static and rarely changes.

API: GET {PHZMAPI_BASE_URL}/{zipcode}.json
Response: {"zone": "8b", "temperature_range": "15 to 20", "coordinates": {"lat": "...", "lon": "..."}}
"""
import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _cache_key(zip_code: str) -> str:
    return f"hardiness_zone:{zip_code}"


async def fetch_phzmapi(zip_code: str) -> dict:
    """Raw HTTP call to PHZMapi. Returns parsed JSON."""
    url = f"{settings.PHZMAPI_BASE_URL}/{zip_code}.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_hardiness_zone(zip_code: str, redis: Any) -> dict:
    """
    Return hardiness zone data for the given ZIP code.

    Checks Redis first. On miss: fetches PHZMapi, caches for 30 days.
    Returns dict with keys: zone, temperature_range, coordinates.
    """
    key = _cache_key(zip_code)

    cached = await redis.get(key)
    if cached is not None:
        logger.debug("hardiness zone cache hit: %s", key)
        raw_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
        return json.loads(raw_str)

    logger.debug("hardiness zone cache miss: %s — fetching PHZMapi", key)
    raw = await fetch_phzmapi(zip_code)

    result = {
        "zone": raw.get("zone"),
        "temperature_range": raw.get("temperature_range"),
        "coordinates": raw.get("coordinates"),
    }

    await redis.setex(key, CACHE_TTL_SECONDS, json.dumps(result))
    return result
