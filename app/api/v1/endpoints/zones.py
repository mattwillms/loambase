import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, get_db
from app.schemas.zone import ZoneCoordinates, ZoneRead
from app.services.hardiness import get_hardiness_zone

router = APIRouter(prefix="/users/me/zone", tags=["zones"])

# Module-level Redis client (connection pool, created once on first use)
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis():
    yield _get_redis()


@router.get("", response_model=ZoneRead)
async def get_my_zone(current_user: CurrentUser):
    """Return the current user's stored hardiness zone."""
    if not current_user.hardiness_zone:
        raise HTTPException(
            status_code=422,
            detail="Hardiness zone not set — add a zip code to your profile and POST /users/me/zone/refresh",
        )
    return ZoneRead(zone=current_user.hardiness_zone)


@router.post("/refresh", response_model=ZoneRead)
async def refresh_my_zone(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Fetch a fresh zone lookup for the user's zip code, update their profile, and return full metadata."""
    if not current_user.zip_code:
        raise HTTPException(
            status_code=422,
            detail="No zip code set on your profile — update your profile first",
        )

    data = await get_hardiness_zone(current_user.zip_code, redis)

    if not data.get("zone"):
        raise HTTPException(
            status_code=502,
            detail=f"PHZMapi returned no zone for zip code {current_user.zip_code}",
        )

    current_user.hardiness_zone = data["zone"]
    await db.commit()

    coords = data.get("coordinates")
    return ZoneRead(
        zone=data["zone"],
        temperature_range=data.get("temperature_range"),
        coordinates=ZoneCoordinates(**coords) if coords else None,
    )
