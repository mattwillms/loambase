"""
ARQ worker — background task definitions.
Run with: python -m app.worker
"""
import logging
from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.tasks.seed_plants import seed_plants

logger = logging.getLogger(__name__)


# ── Job functions ─────────────────────────────────────────────────────────────


async def sync_weather(ctx: dict) -> None:
    """Poll Open-Meteo and update WeatherCache. Runs every 3 hours."""
    logger.info("sync_weather: starting")
    # TODO: implement in Phase 2
    logger.info("sync_weather: complete")


async def refresh_hardiness_zones(ctx: dict) -> None:
    """Back-fill hardiness zones for users missing them. Runs daily."""
    logger.info("refresh_hardiness_zones: starting")
    # TODO: implement in Phase 1 plant setup
    logger.info("refresh_hardiness_zones: complete")


async def sync_plant_database(ctx: dict) -> None:
    """Pull latest plant data from Perenual. Runs weekly."""
    logger.info("sync_plant_database: starting")
    # TODO: implement in Phase 1 seeding
    logger.info("sync_plant_database: complete")


# ── Worker settings ───────────────────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [sync_weather, refresh_hardiness_zones, sync_plant_database, seed_plants]
    cron_jobs = [
        cron(sync_weather, hour={0, 3, 6, 9, 12, 15, 18, 21}, minute=0),
        cron(refresh_hardiness_zones, hour=2, minute=30),
        cron(sync_plant_database, weekday=0, hour=3, minute=0),  # Monday 3am
        cron(seed_plants, hour=4, minute=0),  # Daily 4am
    ]
    on_startup = None
    on_shutdown = None


if __name__ == "__main__":
    import asyncio
    from arq import run_worker

    run_worker(WorkerSettings)
