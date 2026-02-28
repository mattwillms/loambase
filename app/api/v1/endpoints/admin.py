from datetime import date, datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis
from arq.connections import ArqRedis
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AdminUser, get_db
from app.core.security import hash_password
from app.models.data_source_run import DataSourceRun
from app.models.garden import Garden, Bed
from app.models.logs import AuditLog, ApiRequestLog, NotificationLog, PipelineRun, SeederRun, WeatherCache
from app.models.plant import Plant
from app.models.schedule import Planting
from app.models.source_perenual import PerenualPlant
from app.models.source_permapeople import PermapeoplePlant
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserRead, AdminUserUpdate
from app.tasks.fetch_utils import is_source_running

router = APIRouter(prefix="/admin", tags=["admin"])


class FetchRequest(BaseModel):
    force_full: bool = False

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
            "timezone": u.timezone,
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


@router.get("/analytics/gardens")
async def get_garden_analytics(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_count = await db.scalar(select(func.count()).select_from(User)) or 0
    garden_count = await db.scalar(select(func.count()).select_from(Garden)) or 0
    bed_count = await db.scalar(select(func.count()).select_from(Bed)) or 0
    active_planting_count = (
        await db.scalar(
            select(func.count()).select_from(Planting).where(
                Planting.status.not_in(["removed", "dormant"])
            )
        )
        or 0
    )

    status_result = await db.execute(
        select(Planting.status, func.count(Planting.id).label("count"))
        .group_by(Planting.status)
        .order_by(func.count(Planting.id).desc())
    )
    plantings_by_status = [
        {"status": row.status, "count": row.count} for row in status_result
    ]

    top_result = await db.execute(
        select(Plant.id, Plant.common_name, func.count(Planting.id).label("count"))
        .join(Planting, Planting.plant_id == Plant.id)
        .group_by(Plant.id, Plant.common_name)
        .order_by(func.count(Planting.id).desc())
        .limit(10)
    )
    top_plants = [
        {"plant_id": row.id, "common_name": row.common_name, "count": row.count}
        for row in top_result
    ]

    return {
        "totals": {
            "users": user_count,
            "gardens": garden_count,
            "beds": bed_count,
            "active_plantings": active_planting_count,
        },
        "plantings_by_status": plantings_by_status,
        "top_plants": top_plants,
    }


@router.get("/logs")
async def list_api_logs(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    endpoint: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    status_class: Optional[int] = Query(None),
    since: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
) -> dict:
    query = select(ApiRequestLog)
    count_query = select(func.count()).select_from(ApiRequestLog)

    if endpoint is not None:
        query = query.where(ApiRequestLog.endpoint.ilike(f"%{endpoint}%"))
        count_query = count_query.where(ApiRequestLog.endpoint.ilike(f"%{endpoint}%"))
    if status_code is not None:
        query = query.where(ApiRequestLog.status_code == status_code)
        count_query = count_query.where(ApiRequestLog.status_code == status_code)
    if status_class is not None:
        lo = status_class * 100
        hi = (status_class + 1) * 100
        query = query.where(ApiRequestLog.status_code >= lo, ApiRequestLog.status_code < hi)
        count_query = count_query.where(ApiRequestLog.status_code >= lo, ApiRequestLog.status_code < hi)
    if since is not None:
        query = query.where(ApiRequestLog.timestamp >= since)
        count_query = count_query.where(ApiRequestLog.timestamp >= since)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(ApiRequestLog.timestamp.desc()).offset(offset).limit(per_page)
    )
    logs = result.scalars().all()

    items = [
        {
            "id": log.id,
            "timestamp": log.timestamp,
            "method": log.method,
            "endpoint": log.endpoint,
            "user_id": log.user_id,
            "status_code": log.status_code,
            "latency_ms": log.latency_ms,
            "ip_address": log.ip_address,
        }
        for log in logs
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/audit")
async def list_audit_log(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    since: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
) -> dict:
    query = select(AuditLog, User.email).join(User, AuditLog.user_id == User.id, isouter=True)
    count_query = select(func.count()).select_from(AuditLog)

    if action is not None:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
        count_query = count_query.where(AuditLog.entity_type == entity_type)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if since is not None:
        query = query.where(AuditLog.timestamp >= since)
        count_query = count_query.where(AuditLog.timestamp >= since)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(per_page)
    )
    rows = result.all()

    items = [
        {
            "id": log.id,
            "timestamp": log.timestamp,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "user_id": log.user_id,
            "user_email": email,
            "ip_address": log.ip_address,
            "details": log.details,
        }
        for log, email in rows
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


# ── Fetch trigger endpoints ──────────────────────────────────────────────────


async def _get_arq_redis() -> ArqRedis:
    """Create an ArqRedis instance from the same Redis URL the worker uses."""
    from arq.connections import RedisSettings, create_pool
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    return await create_pool(redis_settings)


@router.post("/fetch/permapeople")
async def trigger_fetch_permapeople(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    body: FetchRequest = FetchRequest(),
) -> dict:
    if await is_source_running(db, "permapeople"):
        return {"status": "already_running"}

    pool = await _get_arq_redis()
    try:
        await pool.enqueue_job("fetch_permapeople", triggered_by="mimus", force_full=body.force_full)
    finally:
        await pool.close()

    return {"status": "queued", "message": "Permapeople fetch started", "force_full": body.force_full}


@router.post("/fetch/perenual")
async def trigger_fetch_perenual(
    admin_user: AdminUser,
) -> dict:
    pool = await _get_arq_redis()
    try:
        await pool.enqueue_job("fetch_perenual")
    finally:
        await pool.close()

    return {"status": "queued", "message": "Perenual fetch started"}


@router.get("/fetch/status")
async def get_fetch_status(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Latest DataSourceRun for permapeople
    pp_result = await db.execute(
        select(DataSourceRun)
        .where(DataSourceRun.source == "permapeople")
        .order_by(DataSourceRun.started_at.desc())
        .limit(1)
    )
    pp_run = pp_result.scalar_one_or_none()

    pp_latest = None
    if pp_run:
        pp_latest = {
            "id": pp_run.id,
            "status": pp_run.status,
            "started_at": pp_run.started_at,
            "finished_at": pp_run.finished_at,
            "new_species": pp_run.new_species,
            "updated": pp_run.updated,
            "gap_filled": pp_run.gap_filled,
            "unchanged": pp_run.unchanged,
            "skipped": pp_run.skipped,
            "errors": pp_run.errors,
            "error_detail": pp_run.error_detail,
            "triggered_by": pp_run.triggered_by,
        }

    pp_total = await db.scalar(select(func.count()).select_from(PermapeoplePlant))
    pp_matched = await db.scalar(
        select(func.count()).select_from(PermapeoplePlant).where(PermapeoplePlant.plant_id.isnot(None))
    )
    pp_running = await is_source_running(db, "permapeople")

    # Latest SeederRun for perenual
    pr_result = await db.execute(
        select(SeederRun).order_by(SeederRun.started_at.desc()).limit(1)
    )
    pr_run = pr_result.scalar_one_or_none()

    pr_latest = None
    if pr_run:
        pr_latest = {
            "id": pr_run.id,
            "status": pr_run.status,
            "started_at": pr_run.started_at,
            "finished_at": pr_run.finished_at,
            "current_page": pr_run.current_page,
            "records_synced": pr_run.records_synced,
            "requests_used": pr_run.requests_used,
            "error_detail": pr_run.error_message,
        }

    pr_total = await db.scalar(select(func.count()).select_from(PerenualPlant))
    pr_matched = await db.scalar(
        select(func.count()).select_from(PerenualPlant).where(PerenualPlant.plant_id.isnot(None))
    )
    # Perenual uses SeederRun, check if latest is "running"
    pr_running = pr_run is not None and pr_run.status == "running"

    plants_total = await db.scalar(select(func.count()).select_from(Plant))

    return {
        "permapeople": {
            "latest_run": pp_latest,
            "total_records": pp_total or 0,
            "matched_to_plants": pp_matched or 0,
            "is_running": pp_running,
        },
        "perenual": {
            "latest_run": pr_latest,
            "total_records": pr_total or 0,
            "matched_to_plants": pr_matched or 0,
            "is_running": pr_running,
        },
        "plants_total": plants_total or 0,
    }


@router.get("/fetch/history")
async def get_fetch_history(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    source: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    """Paginated run history for data source fetchers."""
    rows: list[dict] = []

    # Gather DataSourceRun entries (permapeople)
    if source is None or source == "permapeople":
        dsr_result = await db.execute(
            select(DataSourceRun)
            .where(DataSourceRun.source == "permapeople")
            .order_by(DataSourceRun.started_at.desc())
        )
        for run in dsr_result.scalars().all():
            rows.append({
                "id": run.id,
                "source": "permapeople",
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "new_species": run.new_species,
                "updated": run.updated,
                "gap_filled": run.gap_filled,
                "unchanged": run.unchanged,
                "skipped": run.skipped,
                "errors": run.errors,
                "error_detail": run.error_detail,
                "triggered_by": run.triggered_by,
            })

    # Gather SeederRun entries (perenual)
    if source is None or source == "perenual":
        sr_result = await db.execute(
            select(SeederRun).order_by(SeederRun.started_at.desc())
        )
        for run in sr_result.scalars().all():
            # Normalize status: SeederRun uses "complete" → "completed"
            status = run.status
            if status == "complete":
                status = "completed"
            rows.append({
                "id": run.id,
                "source": "perenual",
                "status": status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "new_species": None,
                "updated": None,
                "gap_filled": None,
                "unchanged": None,
                "skipped": None,
                "errors": None,
                "error_detail": run.error_message,
                "triggered_by": "cron",
                "current_page": run.current_page,
                "records_synced": run.records_synced,
                "requests_used": run.requests_used,
            })

    # Sort combined by started_at DESC
    rows.sort(key=lambda r: r["started_at"] or "", reverse=True)

    total = len(rows)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "items": rows[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
