import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, get_db
from app.schemas.recommendation import WateringRecommendation
from app.services.recommendations import get_watering_recommendations

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Module-level Redis client (connection pool, created once on first use)
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis():
    yield _get_redis()


@router.get("/watering", response_model=list[WateringRecommendation])
async def watering_recommendations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    return await get_watering_recommendations(current_user, db, redis)
