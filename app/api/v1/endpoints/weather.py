import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, get_db
from app.models.garden import Garden
from app.schemas.weather import WeatherRead
from app.services.weather import get_weather

router = APIRouter(tags=["weather"])

# Module-level Redis client (connection pool, created once on first use)
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis():
    yield _get_redis()


@router.get("/gardens/{garden_id}/weather", response_model=WeatherRead)
async def get_garden_weather(
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

    lat = current_user.latitude
    lon = current_user.longitude
    if lat is None or lon is None:
        raise HTTPException(
            status_code=422,
            detail="User location not set — update your profile with latitude and longitude",
        )

    data = await get_weather(lat, lon, redis, db)
    return WeatherRead(**data)
