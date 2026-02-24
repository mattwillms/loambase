"""
Perenual plant API client.

Free tier limit: 100 requests/day.
Rate limit responses are signalled by HTTP 429 or an upgrade-required JSON body.
"""
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://perenual.com/api"
_UPGRADE_MARKER = "Upgrade Plan To Premium Access"


class RateLimitError(Exception):
    """Raised when Perenual signals the daily request quota is exhausted."""


def _check_rate_limited(data: Any) -> None:
    """Raise RateLimitError if the response body contains an upgrade notice."""
    if isinstance(data, dict):
        error = data.get("error", "")
        if _UPGRADE_MARKER in str(error):
            raise RateLimitError(error)


async def fetch_species_list(page: int, per_page: int = 30) -> dict:
    """
    Fetch one page of the species list.

    Returns the full parsed JSON body, which includes:
      data, current_page, last_page, total, per_page, from, to
    """
    params = {
        "key": settings.PERENUAL_API_KEY,
        "page": page,
        "per_page": per_page,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = client.build_request("GET", f"{_BASE_URL}/species-list", params=params)
        logger.debug("GET %s (page=%d)", _BASE_URL + "/species-list", page)
        response = await client.send(resp)

        if response.status_code == 429:
            raise RateLimitError("HTTP 429 from Perenual")

        response.raise_for_status()
        data = response.json()
        _check_rate_limited(data)
        return data


async def fetch_species_detail(species_id: int) -> dict:
    """
    Fetch full detail for a single species.

    Returns the parsed JSON body for that species.
    """
    params = {"key": settings.PERENUAL_API_KEY}
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{_BASE_URL}/species/details/{species_id}"
        logger.debug("GET %s", url)
        response = await client.get(url, params=params)

        if response.status_code == 429:
            raise RateLimitError("HTTP 429 from Perenual")

        response.raise_for_status()
        data = response.json()
        _check_rate_limited(data)
        return data
