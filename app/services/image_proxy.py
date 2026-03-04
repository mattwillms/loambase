"""
Image proxy with disk cache for plant images.

Fetches cross-origin images (Flickr, Wikimedia, Pexels S3) once and stores
them permanently on disk as WebP so browsers never hit CORS/ORB restrictions.
"""
import logging
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/app/image_cache/plants")
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _migrate_jpg_to_webp(plant_id: int) -> bool:
    """
    One-time migration: if {plant_id}.jpg exists but .webp does not,
    convert to WebP and delete the .jpg. Returns True if migration happened.
    """
    jpg_path = _CACHE_DIR / f"{plant_id}.jpg"
    webp_path = _CACHE_DIR / f"{plant_id}.webp"

    if jpg_path.exists() and not webp_path.exists():
        try:
            from PIL import Image
            img = Image.open(jpg_path)
            img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="WEBP", quality=80)
            webp_path.write_bytes(buf.getvalue())
            jpg_path.unlink()
            logger.info("migrated plant %d image from .jpg to .webp", plant_id)
            return True
        except Exception as exc:
            logger.warning("failed to migrate plant %d .jpg to .webp: %s", plant_id, exc)
    return False


async def get_plant_image(plant_id: int, image_url: str) -> tuple[bytes, str]:
    """
    Return (image_bytes, content_type) for a plant image.

    Cache hit  → read from /app/image_cache/plants/{plant_id}.webp
    Cache miss → fetch from source, write to cache, return
    Fetch failure (non-200, timeout, network error) → HTTPException(404)
    Failures are never cached.

    On first serve, migrates legacy .jpg cache files to .webp.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE_DIR / f"{plant_id}.webp"

    # One-time migration from .jpg to .webp
    if not cache_path.exists():
        _migrate_jpg_to_webp(plant_id)

    if cache_path.exists():
        logger.debug("image cache hit: plant %d", plant_id)
        return cache_path.read_bytes(), "image/webp"

    logger.debug("image cache miss: plant %d — fetching %s", plant_id, image_url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                image_url,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("image fetch failed for plant %d: %s", plant_id, exc)
        raise HTTPException(status_code=404, detail="Image unavailable")

    if response.status_code != 200:
        logger.warning(
            "image fetch returned %d for plant %d", response.status_code, plant_id
        )
        raise HTTPException(status_code=404, detail="Image unavailable")

    content = response.content

    # Convert to WebP before caching
    try:
        from PIL import Image
        img = Image.open(BytesIO(content))
        img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=80)
        webp_bytes = buf.getvalue()
        cache_path.write_bytes(webp_bytes)
        logger.debug("cached image for plant %d → %s", plant_id, cache_path)
        return webp_bytes, "image/webp"
    except Exception:
        # If Pillow fails, serve the original content but don't cache as webp
        logger.warning("WebP conversion failed for plant %d, serving original", plant_id)
        content_type = (
            response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        )
        return content, content_type
