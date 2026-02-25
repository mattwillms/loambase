"""
ARQ worker — background task definitions.
Run with: python -m app.worker
"""
import logging
from datetime import datetime, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.logs import PipelineRun
from app.models.user import User
from app.services.hardiness import get_hardiness_zone
from app.services.weather import get_weather
from app.tasks.notifications import send_daily_digest, send_frost_alerts, send_heat_alerts
from app.tasks.seed_plants import seed_plants

logger = logging.getLogger(__name__)


# ── Job functions ─────────────────────────────────────────────────────────────


async def sync_weather(ctx: dict) -> None:
    """Poll Open-Meteo for all located users and update WeatherCache. Runs every 3 hours."""
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
                select(User).where(
                    User.latitude.isnot(None),
                    User.longitude.isnot(None),
                    User.is_active == True,
                )
            )
            users = result.scalars().all()

            for user in users:
                try:
                    await get_weather(user.latitude, user.longitude, ctx["redis"], db)
                    records += 1
                except Exception as exc:
                    logger.warning("sync_weather: failed for user %d: %s", user.id, exc)

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

    logger.info("sync_weather: complete — %d locations updated", records)


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


async def sync_plant_database(ctx: dict) -> None:
    """Pull latest plant data from Perenual. Runs weekly."""
    logger.info("sync_plant_database: starting")
    # TODO: implement in Phase 1 seeding
    logger.info("sync_plant_database: complete")


# ── Worker settings ───────────────────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [sync_weather, refresh_hardiness_zones, sync_plant_database, seed_plants, send_daily_digest, send_frost_alerts, send_heat_alerts]
    cron_jobs = [
        cron(sync_weather, hour={0, 3, 6, 9, 12, 15, 18, 21}, minute=0),
        cron(refresh_hardiness_zones, hour=2, minute=30),
        cron(sync_plant_database, weekday=0, hour=3, minute=0),  # Monday 3am
        cron(seed_plants, hour=4, minute=0),  # Daily 4am
        cron(send_frost_alerts, hour=6, minute=0),   # Daily 6am UTC
        cron(send_heat_alerts, hour=6, minute=0),    # Daily 6am UTC
        cron(send_daily_digest, hour=7, minute=0),   # Daily 7am UTC
    ]
    on_startup = None
    on_shutdown = None


if __name__ == "__main__":
    import asyncio
    from arq import run_worker

    run_worker(WorkerSettings)
