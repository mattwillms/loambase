from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, get_db
from app.schemas.recommendation import (
    CompanionRecommendation,
    SeasonalTaskItem,
    SeasonalTaskResponse,
    WateringRecommendation,
)
from app.services.recommendations import get_companion_recommendations, get_watering_recommendations
from app.services.seasonal_tasks import get_seasonal_tasks

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


@router.get("/companions", response_model=CompanionRecommendation)
async def companion_recommendations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    plant_id: int = Query(...),
):
    result = await get_companion_recommendations(plant_id, db)
    if result is None:
        raise HTTPException(status_code=404, detail="Plant not found")
    return result


@router.get("/tasks", response_model=SeasonalTaskResponse)
async def seasonal_task_recommendations(
    current_user: CurrentUser,
):
    zone = current_user.hardiness_zone
    month = datetime.now(timezone.utc).month

    if zone is None:
        return SeasonalTaskResponse(
            zone=None,
            month=month,
            zone_missing=True,
            tasks=[],
        )

    raw_tasks = get_seasonal_tasks(zone, month)
    tasks = [
        SeasonalTaskItem(
            title=t.title,
            description=t.description,
            task_type=t.task_type,
            urgency=t.urgency,
        )
        for t in raw_tasks
    ]

    return SeasonalTaskResponse(
        zone=zone,
        month=month,
        zone_missing=False,
        tasks=tasks,
    )
