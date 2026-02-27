from datetime import date, timedelta
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AdminUser, get_db
from app.core.security import hash_password
from app.models.logs import NotificationLog, PipelineRun, SeederRun, WeatherCache
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserRead, AdminUserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis():
    yield _get_redis()


@router.get("/health")
async def get_health(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> dict:
    # API: if this endpoint responds, API is up
    api_status = "ok"

    # DB check
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    # Redis check
    try:
        await redis.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "error"

    # Worker: most recent SeederRun row
    result = await db.execute(
        select(SeederRun).order_by(SeederRun.started_at.desc()).limit(1)
    )
    last_run = result.scalar_one_or_none()

    if last_run is None:
        worker: dict = {
            "last_run_status": "unknown",
            "last_run_at": None,
            "records_synced": None,
        }
    else:
        # DB enum is "complete"; response normalises to "completed".
        # A failed run caused by quota exhaustion is surfaced as "quota_reached".
        if last_run.status == "failed" and last_run.error_message and (
            last_run.error_message.startswith("Daily budget reached")
            or last_run.error_message.startswith("Budget reached")
        ):
            run_status = "quota_reached"
        else:
            status_map = {"complete": "completed", "running": "running", "failed": "failed"}
            run_status = status_map.get(last_run.status, "unknown")
        worker = {
            "last_run_status": run_status,
            "last_run_at": last_run.finished_at,
            "records_synced": last_run.records_synced,
        }

    return {
        "api": api_status,
        "db": db_status,
        "redis": redis_status,
        "worker": worker,
    }


@router.get("/users")
async def list_users(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(User)) or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )
    users = result.scalars().all()

    items = [
        {
            "id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "last_login": u.last_login,
            "hardiness_zone": u.hardiness_zone,
            "zip_code": u.zip_code,
            "latitude": u.latitude,
            "longitude": u.longitude,
        }
        for u in users
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.post("/users", response_model=AdminUserRead, status_code=201)
async def create_user_admin(
    data: AdminUserCreate,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role,
        is_active=data.is_active,
        timezone=data.timezone,
        zip_code=data.zip_code,
        hardiness_zone=data.hardiness_zone,
        latitude=data.latitude,
        longitude=data.longitude,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=AdminUserRead)
async def get_user_admin(
    user_id: int,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user_admin(
    user_id: int,
    data: AdminUserUpdate,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "password":
            setattr(user, "hashed_password", hash_password(value))
        else:
            setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_admin(
    user_id: int,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    await db.delete(user)
    await db.commit()


@router.get("/pipelines")
async def list_pipelines(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    pipeline_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    query = select(PipelineRun)
    count_query = select(func.count()).select_from(PipelineRun)

    if pipeline_name is not None:
        query = query.where(PipelineRun.pipeline_name == pipeline_name)
        count_query = count_query.where(PipelineRun.pipeline_name == pipeline_name)
    if status is not None:
        query = query.where(PipelineRun.status == status)
        count_query = count_query.where(PipelineRun.status == status)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(PipelineRun.started_at.desc()).offset(offset).limit(per_page)
    )
    runs = result.scalars().all()

    items = [
        {
            "id": r.id,
            "pipeline_name": r.pipeline_name,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_ms": r.duration_ms,
            "records_processed": r.records_processed,
            "error_message": r.error_message,
        }
        for r in runs
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/notifications/log")
async def list_notification_log(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    notification_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    query = select(NotificationLog, User.email).join(User, NotificationLog.user_id == User.id)
    count_query = select(func.count()).select_from(NotificationLog).join(User, NotificationLog.user_id == User.id)

    if notification_type is not None:
        query = query.where(NotificationLog.notification_type == notification_type)
        count_query = count_query.where(NotificationLog.notification_type == notification_type)
    if status is not None:
        query = query.where(NotificationLog.status == status)
        count_query = count_query.where(NotificationLog.status == status)
    if user_id is not None:
        query = query.where(NotificationLog.user_id == user_id)
        count_query = count_query.where(NotificationLog.user_id == user_id)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(NotificationLog.timestamp.desc()).offset(offset).limit(per_page)
    )
    rows = result.all()

    items = [
        {
            "id": log.id,
            "user_id": log.user_id,
            "user_email": email,
            "notification_type": log.notification_type,
            "channel": log.channel,
            "status": log.status,
            "timestamp": log.timestamp,
            "message_preview": log.message_preview,
        }
        for log, email in rows
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/analytics/weather")
async def get_weather_analytics(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    if admin_user.latitude is None or admin_user.longitude is None:
        raise HTTPException(status_code=422, detail="Admin user has no location set")

    since = date.today() - timedelta(days=days)

    result = await db.execute(
        select(WeatherCache).where(
            WeatherCache.date >= since,
            func.abs(WeatherCache.latitude - admin_user.latitude) < 0.01,
            func.abs(WeatherCache.longitude - admin_user.longitude) < 0.01,
        ).order_by(WeatherCache.date.asc())
    )
    records = result.scalars().all()

    high_temps = [r.high_temp_f for r in records if r.high_temp_f is not None]
    low_temps = [r.low_temp_f for r in records if r.low_temp_f is not None]
    precip_vals = [r.precip_inches for r in records if r.precip_inches is not None]
    frost_days = sum(1 for r in records if r.frost_warning)

    summary = {
        "avg_high_f": round(sum(high_temps) / len(high_temps), 1) if high_temps else None,
        "avg_low_f": round(sum(low_temps) / len(low_temps), 1) if low_temps else None,
        "total_precip_inches": round(sum(precip_vals), 2) if precip_vals else None,
        "frost_days": frost_days,
    }

    items = [
        {
            "date": r.date.isoformat(),
            "high_temp_f": r.high_temp_f,
            "low_temp_f": r.low_temp_f,
            "precip_inches": r.precip_inches,
            "humidity_pct": r.humidity_pct,
            "frost_warning": r.frost_warning,
        }
        for r in records
    ]

    return {"summary": summary, "records": items}
