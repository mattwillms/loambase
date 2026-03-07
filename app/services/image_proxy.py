"""
Image proxy with disk cache for plant images.

Fetches cross-origin images (Flickr, Wikimedia, Pexels S3) once and stores
them permanently on disk as WebP so browsers never hit CORS/ORB restrictions.
"""
import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/app/image_cache/plants")


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


async def get_plant_image(plant_id: int, image_url: str) -> tuple[bytes, str] | None:
    """
    Return (image_bytes, content_type) for a plant image, or None if not cached.

    Only serves from the local disk cache — never fetches on demand.
    On first serve, migrates legacy .jpg cache files to .webp.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE_DIR / f"{plant_id}.webp"

    if not cache_path.exists():
        _migrate_jpg_to_webp(plant_id)

    if cache_path.exists():
        logger.debug("image cache hit: plant %d", plant_id)
        return cache_path.read_bytes(), "image/webp"

    logger.debug("image cache miss: plant %d — not cached, returning None", plant_id)
    return None
