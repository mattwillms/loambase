from datetime import date, datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis
from arq.connections import ArqRedis
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, exists, func, select, text
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
from app.models.cron_job import CronJob
from app.models.enrichment import EnrichmentRule
from app.schemas.admin_plant import (
    AdminPlantListResponse,
    AdminPlantSummary,
    EnrichmentRuleRead,
    EnrichmentRuleUpdate,
    EnrichmentRulesResponse,
    FieldCoverageItem,
    PerenualSourceData,
    PermapeopleSourceData,
    PlantCoverageResponse,
    PlantSourcesResponse,
)
from app.schemas.user import AdminUserCreate, AdminUserRead, AdminUserUpdate
from app.services.audit import write_audit_log
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
    request: Request,
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
    await write_audit_log(
        db, action="user_created", entity_type="user", entity_id=user.id,
        user_id=admin_user.id, ip=request.client.host if request.client else None,
        details={"email": user.email, "role": user.role},
    )
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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    changes = data.model_dump(exclude_unset=True)
    old_is_active = user.is_active
    for field, value in changes.items():
        if field == "password":
            setattr(user, "hashed_password", hash_password(value))
        else:
            setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    ip = request.client.host if request.client else None
    # Log activation/deactivation separately
    if "is_active" in changes and changes["is_active"] != old_is_active:
        action = "user_reactivated" if changes["is_active"] else "user_deactivated"
        await write_audit_log(
            db, action=action, entity_type="user", entity_id=user_id,
            user_id=admin_user.id, ip=ip,
        )
    # Log the general update
    logged_changes = {k: v for k, v in changes.items() if k != "password"}
    if "password" in changes:
        logged_changes["password"] = "***"
    await write_audit_log(
        db, action="user_updated", entity_type="user", entity_id=user_id,
        user_id=admin_user.id, ip=ip, details=logged_changes,
    )
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


_QUARTER_RANGES = {
    1: (1, 1, 3, 31),
    2: (4, 1, 6, 30),
    3: (7, 1, 9, 30),
    4: (10, 1, 12, 31),
}


def _quarter_date_range(quarter: int, year: int) -> tuple[date, date]:
    """Return (start, end) for a calendar quarter."""
    sm, sd, em, ed = _QUARTER_RANGES[quarter]
    return date(year, sm, sd), date(year, em, ed)


@router.get("/analytics/weather")
async def get_weather_analytics(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    quarter: Optional[int] = Query(None, ge=1, le=4),
    quarter_year: Optional[int] = Query(None, ge=2020, le=2100),
) -> dict:
    if admin_user.latitude is None or admin_user.longitude is None:
        raise HTTPException(status_code=422, detail="Admin user has no location set")

    coord_filter = [
        func.abs(WeatherCache.latitude - admin_user.latitude) < 0.5,
        func.abs(WeatherCache.longitude - admin_user.longitude) < 0.5,
    ]

    # Date filtering: quarter > year > days
    if quarter is not None and quarter_year is not None and quarter in _QUARTER_RANGES:
        q_start, q_end = _quarter_date_range(quarter, quarter_year)
        date_filter = [WeatherCache.date >= q_start, WeatherCache.date <= q_end]
    elif year is not None:
        date_filter = [WeatherCache.date >= date(year, 1, 1), WeatherCache.date <= date(year, 12, 31)]
    else:
        date_filter = [WeatherCache.date >= date.today() - timedelta(days=days)]

    result = await db.execute(
        select(WeatherCache).where(*date_filter, *coord_filter).order_by(WeatherCache.date.asc())
    )
    all_records = result.scalars().all()

    # Deduplicate by date — keep the row closest to admin coordinates per day.
    by_date: dict[date, list] = {}
    for r in all_records:
        by_date.setdefault(r.date, []).append(r)

    def _pick_best(rows: list, lat: float, lon: float):
        def sort_key(r):
            dist = abs(r.latitude - lat) + abs(r.longitude - lon)
            populated = sum(1 for v in (r.high_temp_f, r.low_temp_f, r.precip_inches, r.humidity_pct, r.wind_mph) if v is not None)
            return (dist, -populated)
        return min(rows, key=sort_key)

    records = [
        _pick_best(rows, admin_user.latitude, admin_user.longitude)
        for rows in by_date.values()
    ]
    records.sort(key=lambda r: r.date)

    high_temps = [r.high_temp_f for r in records if r.high_temp_f is not None]
    low_temps = [r.low_temp_f for r in records if r.low_temp_f is not None]
    precip_vals = [r.precip_inches for r in records if r.precip_inches is not None]
    frost_days = sum(1 for r in records if r.frost_warning)
    heat_days = sum(1 for r in records if r.heat_warning)

    summary = {
        "avg_high_f": round(sum(high_temps) / len(high_temps), 1) if high_temps else None,
        "avg_low_f": round(sum(low_temps) / len(low_temps), 1) if low_temps else None,
        "total_precip_inches": round(sum(precip_vals), 2) if precip_vals else None,
        "frost_days": frost_days,
        "heat_days": heat_days,
    }

    items = [
        {
            "date": r.date.isoformat(),
            "high_temp_f": r.high_temp_f,
            "low_temp_f": r.low_temp_f,
            "precip_inches": r.precip_inches,
            "humidity_pct": r.humidity_pct,
            "frost_warning": r.frost_warning,
            "heat_warning": r.heat_warning or False,
        }
        for r in records
    ]

    # Available years
    years_result = await db.execute(
        select(func.distinct(func.extract("year", WeatherCache.date)))
        .where(*coord_filter)
        .order_by(func.extract("year", WeatherCache.date).asc())
    )
    available_years = [int(row[0]) for row in years_result.all()]

    # Available quarters
    today = date.today()
    cur_quarter = (today.month - 1) // 3 + 1
    _quarter_labels = {1: "Q1 (Jan–Mar)", 2: "Q2 (Apr–Jun)", 3: "Q3 (Jul–Sep)", 4: "Q4 (Oct–Dec)"}
    available_quarters: list[dict] = []

    for y in available_years:
        for q in range(1, 5):
            q_start, q_end = _quarter_date_range(q, y)
            if q_start > today:
                continue  # future quarter
            is_current = (y == today.year and q == cur_quarter)
            if is_current:
                available_quarters.append({
                    "label": f"{y} {_quarter_labels[q]}",
                    "quarter": q,
                    "quarter_year": y,
                })
            else:
                count = await db.scalar(
                    select(func.count()).select_from(WeatherCache).where(
                        WeatherCache.date >= q_start, WeatherCache.date <= q_end, *coord_filter
                    )
                )
                if count and count > 0:
                    available_quarters.append({
                        "label": f"{y} {_quarter_labels[q]}",
                        "quarter": q,
                        "quarter_year": y,
                    })

    available_quarters.reverse()  # most recent first

    return {
        "summary": summary,
        "records": items,
        "available_years": available_years,
        "available_quarters": available_quarters,
    }


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
    request: Request,
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

    await write_audit_log(
        db, action="pipeline_triggered", entity_type="pipeline",
        user_id=admin_user.id, ip=request.client.host if request.client else None,
        details={"pipeline": "permapeople", "triggered_by": "mimus", "force_full": body.force_full},
    )
    return {"status": "queued", "message": "Permapeople fetch started", "force_full": body.force_full}


@router.post("/fetch/perenual")
async def trigger_fetch_perenual(
    admin_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    pool = await _get_arq_redis()
    try:
        await pool.enqueue_job("fetch_perenual")
    finally:
        await pool.close()

    await write_audit_log(
        db, action="pipeline_triggered", entity_type="pipeline",
        user_id=admin_user.id, ip=request.client.host if request.client else None,
        details={"pipeline": "perenual", "triggered_by": "mimus"},
    )
    return {"status": "queued", "message": "Perenual fetch started"}


@router.post("/fetch/image-cache")
async def trigger_image_cache(
    admin_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await is_source_running(db, "image_cache"):
        return {"status": "already_running"}

    pool = await _get_arq_redis()
    try:
        await pool.enqueue_job("cache_images", triggered_by="mimus")
    finally:
        await pool.close()

    await write_audit_log(
        db, action="pipeline_triggered", entity_type="pipeline",
        user_id=admin_user.id, ip=request.client.host if request.client else None,
        details={"pipeline": "image_cache", "triggered_by": "mimus"},
    )
    return {"status": "queued", "message": "Image cache started"}


@router.post("/enrich")
async def trigger_enrichment(
    admin_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await is_source_running(db, "enrichment"):
        return {"status": "already_running"}

    pool = await _get_arq_redis()
    try:
        await pool.enqueue_job("enrich_plants", triggered_by="mimus")
    finally:
        await pool.close()

    await write_audit_log(
        db, action="pipeline_triggered", entity_type="pipeline",
        user_id=admin_user.id, ip=request.client.host if request.client else None,
        details={"pipeline": "enrichment", "triggered_by": "mimus"},
    )
    return {"status": "queued", "message": "Enrichment started"}


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

    # Latest DataSourceRun for enrichment
    enrich_result = await db.execute(
        select(DataSourceRun)
        .where(DataSourceRun.source == "enrichment")
        .order_by(DataSourceRun.started_at.desc())
        .limit(1)
    )
    enrich_run = enrich_result.scalar_one_or_none()
    enrich_latest = None
    if enrich_run:
        enrich_latest = {
            "id": enrich_run.id,
            "status": enrich_run.status,
            "started_at": enrich_run.started_at,
            "finished_at": enrich_run.finished_at,
            "new_species": enrich_run.new_species,
            "updated": enrich_run.updated,
            "gap_filled": enrich_run.gap_filled,
            "unchanged": enrich_run.unchanged,
            "skipped": enrich_run.skipped,
            "errors": enrich_run.errors,
            "error_detail": enrich_run.error_detail,
            "triggered_by": enrich_run.triggered_by,
        }
    enrich_running = await is_source_running(db, "enrichment")

    # Latest DataSourceRun for image_cache
    ic_result = await db.execute(
        select(DataSourceRun)
        .where(DataSourceRun.source == "image_cache")
        .order_by(DataSourceRun.started_at.desc())
        .limit(1)
    )
    ic_run = ic_result.scalar_one_or_none()
    ic_latest = None
    if ic_run:
        ic_latest = {
            "id": ic_run.id,
            "status": ic_run.status,
            "started_at": ic_run.started_at,
            "finished_at": ic_run.finished_at,
            "new_species": ic_run.new_species,
            "updated": ic_run.updated,
            "skipped": ic_run.skipped,
            "errors": ic_run.errors,
            "error_detail": ic_run.error_detail,
            "triggered_by": ic_run.triggered_by,
        }
    ic_running = await is_source_running(db, "image_cache")

    # Image cache stats
    plants_with_image = await db.scalar(
        select(func.count()).select_from(Plant).where(Plant.image_url.isnot(None))
    ) or 0

    import os
    _IMAGE_CACHE_DIR = "/app/image_cache/plants"
    try:
        cached_on_disk = sum(
            1 for f in os.scandir(_IMAGE_CACHE_DIR)
            if f.is_file() and f.name.endswith(".webp")
        )
    except FileNotFoundError:
        cached_on_disk = 0

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
        "enrichment": {
            "latest_run": enrich_latest,
            "is_running": enrich_running,
        },
        "image_cache": {
            "latest_run": ic_latest,
            "is_running": ic_running,
            "plants_with_image": plants_with_image,
            "cached_on_disk": cached_on_disk,
        },
        "plants_total": plants_total or 0,
    }


@router.get("/fetch/history")
async def get_fetch_history(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    source: Optional[str] = Query(None),
    exclude_sources: Optional[str] = Query(None, description="Comma-separated sources to exclude"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    """Paginated run history for data source fetchers."""
    excluded = {s.strip() for s in exclude_sources.split(",")} if exclude_sources else set()
    rows: list[dict] = []

    # Gather DataSourceRun entries (permapeople + enrichment + image_cache)
    dsr_sources = []
    if source is None:
        dsr_sources = [s for s in ["permapeople", "enrichment", "image_cache"] if s not in excluded]
    elif source in ("permapeople", "enrichment", "image_cache") and source not in excluded:
        dsr_sources = [source]

    if dsr_sources:
        dsr_result = await db.execute(
            select(DataSourceRun)
            .where(DataSourceRun.source.in_(dsr_sources))
            .order_by(DataSourceRun.started_at.desc())
        )
        for run in dsr_result.scalars().all():
            rows.append({
                "id": run.id,
                "source": run.source,
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
    if (source is None or source == "perenual") and "perenual" not in excluded:
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


# ── Plant Browser ────────────────────────────────────────────────

_FIELD_COUNT_COLUMNS = [
    Plant.height_inches, Plant.width_inches, Plant.soil_type, Plant.soil_ph_min,
    Plant.life_cycle, Plant.propagation_method, Plant.germination_days_min,
    Plant.native_to, Plant.edible, Plant.edible_parts, Plant.medicinal,
    Plant.wikipedia_url, Plant.description, Plant.companion_plants,
]


@router.get("/plants/browse", response_model=AdminPlantListResponse)
async def admin_browse_plants(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    name: str | None = Query(None),
    source: str | None = Query(None),
    both_sources: bool | None = Query(None),
    sort_by: str = Query("name_asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    perenual_exists = exists(
        select(PerenualPlant.id).where(PerenualPlant.plant_id == Plant.id)
    )
    permapeople_exists = exists(
        select(PermapeoplePlant.id).where(PermapeoplePlant.plant_id == Plant.id)
    )

    field_count_expr = sum(
        case((col.isnot(None), 1), else_=0) for col in _FIELD_COUNT_COLUMNS
    ).label("field_count")

    query = select(
        Plant,
        perenual_exists.label("has_perenual"),
        permapeople_exists.label("has_permapeople"),
        field_count_expr,
    )

    if name:
        query = query.where(Plant.common_name.ilike(f"%{name}%"))
    if source:
        query = query.where(Plant.source == source)
    if both_sources is True:
        query = query.where(perenual_exists).where(permapeople_exists)

    sort_map = {
        "name_asc": Plant.common_name.asc(),
        "name_desc": Plant.common_name.desc(),
        "coverage_asc": field_count_expr.asc(),
        "coverage_desc": field_count_expr.desc(),
    }
    order = sort_map.get(sort_by, Plant.common_name.asc())

    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(order).offset(offset).limit(per_page)
    )
    rows = result.all()

    items = []
    for plant, has_per, has_perm, fc in rows:
        items.append(AdminPlantSummary(
            id=plant.id,
            common_name=plant.common_name,
            scientific_name=plant.scientific_name,
            cultivar_name=plant.cultivar_name,
            plant_type=plant.plant_type,
            source=plant.source,
            data_sources=plant.data_sources,
            has_perenual=has_per,
            has_permapeople=has_perm,
            field_count=fc,
            image_url=plant.image_url,
        ))

    return AdminPlantListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/plants/{plant_id}/sources", response_model=PlantSourcesResponse)
async def admin_plant_sources(
    plant_id: int,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Plant).where(Plant.id == plant_id))
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    perenual_result = await db.execute(
        select(PerenualPlant).where(PerenualPlant.plant_id == plant_id)
    )
    perenual_row = perenual_result.scalar_one_or_none()

    permapeople_result = await db.execute(
        select(PermapeoplePlant).where(PermapeoplePlant.plant_id == plant_id)
    )
    permapeople_row = permapeople_result.scalar_one_or_none()

    return PlantSourcesResponse(
        plant_id=plant.id,
        common_name=plant.common_name,
        scientific_name=plant.scientific_name,
        perenual=PerenualSourceData.model_validate(perenual_row) if perenual_row else None,
        permapeople=PermapeopleSourceData.model_validate(permapeople_row) if permapeople_row else None,
    )


# ── Coverage ─────────────────────────────────────────────────────

_COVERAGE_FIELDS = [
    "common_name", "scientific_name", "image_url", "description", "plant_type",
    "water_needs", "sun_requirement", "hardiness_zones", "days_to_maturity",
    "spacing_inches", "planting_depth_inches", "common_pests", "common_diseases",
    "height_inches", "width_inches", "soil_type", "soil_ph_min", "soil_ph_max",
    "growth_rate", "life_cycle", "drought_resistant", "days_to_harvest",
    "propagation_method", "germination_days_min", "germination_days_max",
    "germination_temp_min_f", "germination_temp_max_f", "sow_outdoors",
    "sow_indoors", "start_indoors_weeks", "start_outdoors_weeks",
    "plant_transplant", "plant_cuttings", "plant_division", "native_to",
    "habitat", "family", "genus", "edible", "edible_parts", "edible_uses",
    "medicinal", "medicinal_parts", "utility", "warning", "pollination",
    "nitrogen_fixing", "root_type", "root_depth", "wikipedia_url", "pfaf_url",
    "powo_url",
]


@router.get("/plants/coverage", response_model=PlantCoverageResponse)
async def get_plant_coverage(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    cols = {
        name: func.count(getattr(Plant, name)).label(name)
        for name in _COVERAGE_FIELDS
    }
    result = await db.execute(
        select(func.count().label("total"), *cols.values()).select_from(Plant)
    )
    row = result.one()
    total = row.total

    fields = []
    for name in _COVERAGE_FIELDS:
        populated = getattr(row, name)
        pct = round(populated / total * 100, 1) if total > 0 else 0.0
        fields.append(FieldCoverageItem(
            field_name=name, populated=populated, total=total, pct=pct,
        ))

    fields.sort(key=lambda f: f.pct, reverse=True)

    return PlantCoverageResponse(total_plants=total, fields=fields)


# ── Enrichment Rules ─────────────────────────────────────────────


@router.get("/enrichment/rules", response_model=EnrichmentRulesResponse)
async def list_enrichment_rules(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EnrichmentRule).order_by(EnrichmentRule.field_name.asc())
    )
    rules = result.scalars().all()
    return EnrichmentRulesResponse(
        items=[EnrichmentRuleRead.model_validate(r) for r in rules]
    )


@router.patch("/enrichment/rules/{field_name}", response_model=EnrichmentRuleRead)
async def update_enrichment_rule(
    field_name: str,
    data: EnrichmentRuleUpdate,
    admin_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EnrichmentRule).where(EnrichmentRule.field_name == field_name)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Enrichment rule not found")

    changes = data.model_dump(exclude_unset=True)
    old_values = {k: getattr(rule, k) for k in changes}
    for field, value in changes.items():
        setattr(rule, field, value)
    rule.updated_by = admin_user.id

    await db.commit()
    await db.refresh(rule)
    await write_audit_log(
        db, action="enrichment_rule_updated", entity_type="enrichment_rule",
        entity_id=rule.id, user_id=admin_user.id,
        ip=request.client.host if request.client else None,
        details={"field_name": field_name, "changes": {k: {"old": old_values[k], "new": v} for k, v in changes.items()}},
    )
    return EnrichmentRuleRead.model_validate(rule)


# ── Cron Job Scheduling ─────────────────────────────────────────


class CronJobUpdate(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    interval_hours: Optional[int] = None


@router.get("/cron/jobs")
async def get_cron_jobs(
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all cron job schedule rows."""
    result = await db.execute(select(CronJob).order_by(CronJob.name))
    rows = result.scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "enabled": r.enabled,
                "hour": r.hour,
                "minute": r.minute,
                "interval_hours": r.interval_hours,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


@router.patch("/cron/jobs/{name}")
async def update_cron_job(
    name: str,
    body: CronJobUpdate,
    admin_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a cron job's schedule or enabled state."""
    result = await db.execute(select(CronJob).where(CronJob.name == name))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, f"Cron job '{name}' not found")

    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(job, field, value)
    job.updated_at = datetime.now()

    await db.commit()
    await db.refresh(job)
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "hour": job.hour,
        "minute": job.minute,
        "interval_hours": job.interval_hours,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("/worker/restart")
async def restart_worker(admin_user: AdminUser) -> dict:
    """Restart the loambase-worker container to apply schedule changes."""
    import docker

    client = docker.from_env()
    container = client.containers.get("loambase-loambase-worker-1")
    container.restart()
    return {"status": "restarting"}
