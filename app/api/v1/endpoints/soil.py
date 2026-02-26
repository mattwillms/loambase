import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, get_db
from app.models.garden import Garden
from app.schemas.soil import SoilDataRead
from app.services.soil import get_soil_data

router = APIRouter(tags=["soil"])

# Module-level Redis client (connection pool, created once on first use)
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis():
    yield _get_redis()


@router.get("/gardens/{garden_id}/soil", response_model=SoilDataRead)
async def get_garden_soil(
    garden_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    result = await db.execute(
        select(Garden).where(Garden.id == garden_id, Garden.user_id == current_user.id)
    )
    garden = result.scalar_one_or_none()
    if not garden:
        raise HTTPException(status_code=404, detail="Garden not found")

    lat = garden.latitude if garden.latitude is not None else current_user.latitude
    lon = garden.longitude if garden.longitude is not None else current_user.longitude
    if lat is None or lon is None:
        raise HTTPException(status_code=422, detail="No location set for this garden or user profile")

    data = await get_soil_data(lat, lon, redis)
    if data is None:
        raise HTTPException(status_code=404, detail="No soil data found for this location")

    return SoilDataRead(**data)
