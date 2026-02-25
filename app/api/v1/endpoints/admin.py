import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AdminUser, get_db
from app.models.logs import SeederRun
from app.models.user import User

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
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "last_login": u.last_login,
            "hardiness_zone": u.hardiness_zone,
            "zip_code": u.zip_code,
        }
        for u in users
    ]

    return {"items": items, "total": total, "page": page, "per_page": per_page}
