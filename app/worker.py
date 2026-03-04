"""
ARQ worker — background task definitions.
Run with: python -m app.worker
"""
import logging
from datetime import datetime, timezone

from arq import cron, func
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.garden import Garden
from app.models.logs import PipelineRun
from app.models.user import User
from app.services.hardiness import get_hardiness_zone
from app.services.weather import get_weather
from app.tasks.notifications import send_daily_digest, send_frost_alerts, send_heat_alerts
from app.tasks.cache_images import cache_images
from app.tasks.enrich_plants import enrich_plants
from app.tasks.fetch_perenual import fetch_perenual
from app.tasks.fetch_permapeople import fetch_permapeople

logger = logging.getLogger(__name__)


# ── Job functions ─────────────────────────────────────────────────────────────


async def sync_weather(ctx: dict) -> None:
    """Poll Open-Meteo for all gardens with coordinates and update WeatherCache. Runs every 3 hours."""
    logger.info("sync_weather: starting")
    started_at = datetime.now(timezone.utc)
    records = 0

    async with AsyncSessionLocal() as db:
        pipeline = PipelineRun(
            pipeline_name="weather_sync",
            status="running",
            started_at=started_at,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)

        try:
            result = await db.execute(
                select(Garden).where(
                    Garden.latitude.isnot(None),
                    Garden.longitude.isnot(None),
                )
            )
            gardens = result.scalars().all()

            for garden in gardens:
                try:
                    await get_weather(garden.latitude, garden.longitude, ctx["redis"], db)
                    records += 1
                except Exception as exc:
                    logger.warning("sync_weather: failed for garden %d: %s", garden.id, exc)

            finished_at = datetime.now(timezone.utc)
            pipeline.status = "success"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.records_processed = records
            await db.commit()

        except Exception as exc:
            logger.exception("sync_weather: unexpected error")
            finished_at = datetime.now(timezone.utc)
            pipeline.status = "failed"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.error_message = str(exc)
            await db.commit()
            raise

    logger.info("sync_weather: complete — %d garden locations updated", records)


async def sync_admin_weather(ctx: dict) -> None:
    """Poll Open-Meteo for admin users with coordinates and update WeatherCache. Runs every 3 hours."""
    logger.info("sync_admin_weather: starting")
    started_at = datetime.now(timezone.utc)
    records = 0

    async with AsyncSessionLocal() as db:
        pipeline = PipelineRun(
            pipeline_name="admin_weather_sync",
            status="running",
            started_at=started_at,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)

        try:
            result = await db.execute(
                select(User).where(
                    User.role == "admin",
                    User.latitude.isnot(None),
                    User.longitude.isnot(None),
                )
            )
            admins = result.scalars().all()

            for user in admins:
                try:
                    await get_weather(user.latitude, user.longitude, ctx["redis"], db)
                    records += 1
                except Exception as exc:
                    logger.warning("sync_admin_weather: failed for user %d: %s", user.id, exc)

            finished_at = datetime.now(timezone.utc)
            pipeline.status = "success"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.records_processed = records
            await db.commit()

        except Exception as exc:
            logger.exception("sync_admin_weather: unexpected error")
            finished_at = datetime.now(timezone.utc)
            pipeline.status = "failed"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.error_message = str(exc)
            await db.commit()
            raise

    logger.info("sync_admin_weather: complete — %d admin locations updated", records)


async def refresh_hardiness_zones(ctx: dict) -> None:
    """Back-fill hardiness zones for active users with a zip code but no zone set. Runs daily at 02:30."""
    logger.info("refresh_hardiness_zones: starting")
    started_at = datetime.now(timezone.utc)
    records = 0

    async with AsyncSessionLocal() as db:
        pipeline = PipelineRun(
            pipeline_name="zone_lookup",
            status="running",
            started_at=started_at,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)

        try:
            result = await db.execute(
                select(User).where(
                    User.zip_code.isnot(None),
                    User.hardiness_zone.is_(None),
                    User.is_active == True,
                )
            )
            users = result.scalars().all()

            for user in users:
                try:
                    data = await get_hardiness_zone(user.zip_code, ctx["redis"])
                    user.hardiness_zone = data["zone"]
                    records += 1
                except Exception as exc:
                    logger.warning("refresh_hardiness_zones: failed for user %d: %s", user.id, exc)

            await db.commit()

            finished_at = datetime.now(timezone.utc)
            pipeline.status = "success"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.records_processed = records
            await db.commit()

        except Exception as exc:
            logger.exception("refresh_hardiness_zones: unexpected error")
            finished_at = datetime.now(timezone.utc)
            pipeline.status = "failed"
            pipeline.finished_at = finished_at
            pipeline.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            pipeline.error_message = str(exc)
            await db.commit()
            raise

    logger.info("refresh_hardiness_zones: complete — %d zones updated", records)


# send_daily_digest — implemented (2026-02-25): runs daily at 07:00 UTC
# send_frost_alerts — implemented (2026-02-25): runs daily at 06:00 UTC
# send_heat_alerts  — implemented (2026-02-25): runs daily at 06:00 UTC


# ── Dynamic cron scheduling ──────────────────────────────────────────────────

CRON_DEFAULTS = {
    'sync_weather':            {'interval_hours': 3, 'minute': 0, 'enabled': True},
    'sync_admin_weather':      {'interval_hours': 3, 'minute': 0, 'enabled': True},
    'cache_images':            {'hour': 2,  'minute': 0,  'enabled': True},
    'fetch_permapeople':       {'hour': 3,  'minute': 0,  'enabled': True},
    'fetch_perenual':          {'hour': 4,  'minute': 0,  'enabled': True},
    'refresh_hardiness_zones': {'hour': 2,  'minute': 30, 'enabled': True},
    'send_frost_alerts':       {'hour': 6,  'minute': 0,  'enabled': True},
    'send_heat_alerts':        {'hour': 6,  'minute': 0,  'enabled': True},
    'send_daily_digest':       {'hour': 7,  'minute': 0,  'enabled': True},
}

CRON_FUNCTIONS = {
    'sync_weather': sync_weather,
    'sync_admin_weather': sync_admin_weather,
    'cache_images': cache_images,
    'fetch_permapeople': fetch_permapeople,
    'fetch_perenual': fetch_perenual,
    'refresh_hardiness_zones': refresh_hardiness_zones,
    'send_frost_alerts': send_frost_alerts,
    'send_heat_alerts': send_heat_alerts,
    'send_daily_digest': send_daily_digest,
}


async def sync_cron_jobs_with_db() -> None:
    """Seed CRON_DEFAULTS into cron_jobs table — insert-only, never overwrites existing rows."""
    from app.models.cron_job import CronJob

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CronJob.name))
        existing = {row[0] for row in result.all()}

        for name, defaults in CRON_DEFAULTS.items():
            if name not in existing:
                db.add(CronJob(
                    name=name,
                    enabled=defaults.get('enabled', True),
                    hour=defaults.get('hour'),
                    minute=defaults.get('minute', 0),
                    interval_hours=defaults.get('interval_hours'),
                ))
                logger.info("sync_cron_jobs: seeded %s", name)

        await db.commit()
    logger.info("sync_cron_jobs: done (%d defaults, %d already existed)", len(CRON_DEFAULTS), len(existing))


async def rebuild_cron_schedule() -> None:
    """Read cron_jobs table and build WorkerSettings.cron_jobs dynamically."""
    from app.models.cron_job import CronJob

    jobs = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CronJob))
        for row in result.scalars().all():
            if not row.enabled:
                logger.info("rebuild_cron: %s — disabled, skipping", row.name)
                continue

            fn = CRON_FUNCTIONS.get(row.name)
            if fn is None:
                logger.warning("rebuild_cron: %s — no function found, skipping", row.name)
                continue

            minute = row.minute if row.minute is not None else 0

            if row.interval_hours:
                hours = set(range(0, 24, row.interval_hours))
                jobs.append(cron(fn, hour=hours, minute=minute))
                logger.info("rebuild_cron: %s — every %dh at :%02d", row.name, row.interval_hours, minute)
            elif row.hour is not None:
                jobs.append(cron(fn, hour={row.hour}, minute=minute))
                logger.info("rebuild_cron: %s — daily at %02d:%02d", row.name, row.hour, minute)
            else:
                logger.warning("rebuild_cron: %s — no hour or interval, skipping", row.name)

    WorkerSettings.cron_jobs = jobs
    logger.info("rebuild_cron: %d cron jobs configured", len(jobs))


def _build_default_cron_jobs() -> list:
    """Build cron job list from CRON_DEFAULTS — used as initial schedule before DB is available."""
    jobs = []
    for name, defaults in CRON_DEFAULTS.items():
        if not defaults.get('enabled', True):
            continue
        fn = CRON_FUNCTIONS.get(name)
        if fn is None:
            continue
        minute = defaults.get('minute', 0)
        if 'interval_hours' in defaults:
            hours = set(range(0, 24, defaults['interval_hours']))
            jobs.append(cron(fn, hour=hours, minute=minute))
        elif 'hour' in defaults:
            jobs.append(cron(fn, hour={defaults['hour']}, minute=minute))
    return jobs


async def startup(ctx: dict) -> None:
    """Worker on_startup hook — sync DB defaults, then rebuild schedule from DB."""
    await sync_cron_jobs_with_db()
    await rebuild_cron_schedule()


# ── Worker settings ───────────────────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [
        sync_weather,
        sync_admin_weather,
        refresh_hardiness_zones,
        func(fetch_perenual, timeout=600),         # 10 minutes
        func(fetch_permapeople, timeout=1800),     # 30 minutes
        func(enrich_plants, timeout=600),           # 10 minutes
        func(cache_images, timeout=3600),            # 1 hour
        send_daily_digest,
        send_frost_alerts,
        send_heat_alerts,
    ]
    cron_jobs: list = _build_default_cron_jobs()
    on_startup = startup
    on_shutdown = None


if __name__ == "__main__":
    import asyncio
    from arq import run_worker

    asyncio.set_event_loop(asyncio.new_event_loop())
    run_worker(WorkerSettings)
