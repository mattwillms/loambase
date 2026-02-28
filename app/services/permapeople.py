"""
Permapeople plant API client.

Auth via x-permapeople-key-id / x-permapeople-key-secret headers.
Timeout: 30 seconds. Retries on timeout (up to 3) and 429 with exponential backoff.
"""
import asyncio
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://permapeople.org/api"
_TIMEOUT = 30.0
_MAX_RETRIES = 3


class PermapeopleAPIError(Exception):
    """Raised on non-retryable failures from the Permapeople API."""


def _headers() -> dict[str, str]:
    return {
        "x-permapeople-key-id": settings.PERMAPEOPLE_KEY_ID,
        "x-permapeople-key-secret": settings.PERMAPEOPLE_KEY_SECRET,
    }


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with retry on timeout and 429."""
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.request(method, url, headers=_headers(), **kwargs)

            if response.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning("permapeople: 429 on %s, retrying in %ds (attempt %d/%d)", url, wait, attempt + 1, _MAX_RETRIES)
                await asyncio.sleep(wait)
                continue

            if response.status_code >= 400:
                raise PermapeopleAPIError(f"HTTP {response.status_code} from {url}: {response.text[:200]}")

            return response

        except httpx.TimeoutException:
            if attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("permapeople: timeout on %s, retrying in %ds (attempt %d/%d)", url, wait, attempt + 1, _MAX_RETRIES)
                await asyncio.sleep(wait)
            else:
                raise PermapeopleAPIError(f"Timeout after {_MAX_RETRIES} attempts: {url}")

    raise PermapeopleAPIError(f"Retries exhausted for {url}")


async def fetch_plant_list(last_id: int | None = None, updated_since: str | None = None) -> dict:
    """
    GET /api/plants with optional cursor pagination and incremental update filter.

    Returns the full parsed JSON body.
    """
    params: dict[str, str] = {}
    if last_id is not None:
        params["last_id"] = str(last_id)
    if updated_since is not None:
        params["updated_since"] = updated_since

    response = await _request_with_retry("GET", f"{_BASE_URL}/plants", params=params)
    return response.json()


async def fetch_plant_detail(plant_id: int) -> dict:
    """
    GET /api/plants/{plant_id}

    Returns the full parsed JSON body for a single plant.
    """
    response = await _request_with_retry("GET", f"{_BASE_URL}/plants/{plant_id}")
    return response.json()


async def search_plants(query: str) -> dict:
    """
    POST /api/search with JSON {"q": query}

    Returns the full parsed JSON body.
    """
    response = await _request_with_retry("POST", f"{_BASE_URL}/search", json={"q": query})
    return response.json()
