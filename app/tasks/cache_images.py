"""
ARQ task: cache plant images as WebP files on disk.

Strategy
--------
Query all plants that have an image_url and are linked to a perenual_plants
source row, but do not yet have a cached WebP file on disk. For each plant,
attempt to download directly from the existing plants.image_url. If the
download fails (non-200, timeout, DNS error), hit the Perenual species detail
endpoint to refresh the URL and retry once. This means most plants with valid
URLs are cached without touching the API quota.

Budget cap: 90 Perenual API requests per run (same pattern as fetch_perenual),
but only consumed for genuinely broken URLs.
Tracks run via DataSourceRun (source="image_cache").
Sends email report on completion or budget exhaustion.
"""
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.plant import Plant
from app.models.source_perenual import PerenualPlant
from app.services.email import send_email
from app.services.perenual import RateLimitError, fetch_species_detail
from app.tasks.fetch_utils import (
    complete_run,
    fail_run,
    fmt,
    is_source_running,
    start_run,
)

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/app/image_cache/plants")
_REQUEST_BUDGET = 90
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _image_url_from_detail(detail: dict) -> Optional[str]:
    """Extract best image URL from a Perenual species detail response."""
    img = detail.get("default_image")
    if isinstance(img, dict):
        return img.get("original_url") or img.get("regular_url")
    return None


async def _download_image(url: str) -> Optional[bytes]:
    """Download image bytes from a URL. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            return resp.content
    except (httpx.TimeoutException, httpx.RequestError):
        return None


def _convert_to_webp(image_bytes: bytes) -> Optional[bytes]:
    """Convert raw image bytes to WebP at quality 80. Returns None on failure."""
    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=80)
        return buf.getvalue()
    except Exception:
        return None


async def _get_plants_needing_cache(db: AsyncSession) -> list[tuple[int, int, str]]:
    """
    Return list of (plant_id, perenual_id, image_url) for plants that:
    - Have an image_url
    - Are linked to a perenual_plants source row
    - Do not yet have a cached .webp file on disk
    """
    result = await db.execute(
        select(Plant.id, PerenualPlant.perenual_id, Plant.image_url)
        .join(PerenualPlant, PerenualPlant.plant_id == Plant.id)
        .where(Plant.image_url.isnot(None))
    )
    rows = result.all()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    needs_cache = []
    for plant_id, perenual_id, image_url in rows:
        cache_path = _CACHE_DIR / f"{plant_id}.webp"
        if not cache_path.exists():
            needs_cache.append((plant_id, perenual_id, image_url))

    return needs_cache


async def cache_images(ctx: dict, triggered_by: str = "cron") -> None:
    """
    Cache plant images as WebP files. Tries the existing image_url first;
    only hits Perenual API to refresh the URL when the download fails.
    """
    async with AsyncSessionLocal() as db:
        if await is_source_running(db, "image_cache"):
            logger.info("cache_images: run already in progress, skipping")
            return

        run = start_run(db, source="image_cache", triggered_by=triggered_by)
        await db.commit()
        await db.refresh(run)

        logger.info("cache_images: starting (run_id=%d)", run.id)

        try:
            plants = await _get_plants_needing_cache(db)
            total_eligible = len(plants)
            logger.info("cache_images: %d plants need caching", total_eligible)

            cached = 0
            failed = 0
            skipped = 0
            requests_used = 0
            error_messages: list[str] = []

            # Count already-cached for the report
            all_result = await db.execute(
                select(Plant.id)
                .join(PerenualPlant, PerenualPlant.plant_id == Plant.id)
                .where(Plant.image_url.isnot(None))
            )
            total_with_image = len(all_result.all())
            already_cached = total_with_image - total_eligible

            for plant_id, perenual_id, current_url in plants:
                try:
                    # 1. Try downloading from the existing URL (no API call)
                    image_bytes = await _download_image(current_url)

                    if not image_bytes:
                        # 2. Download failed — refresh URL via Perenual API
                        if requests_used >= _REQUEST_BUDGET:
                            logger.info("cache_images: budget exhausted after %d requests", requests_used)
                            break

                        detail = await fetch_species_detail(perenual_id)
                        requests_used += 1

                        fresh_url = _image_url_from_detail(detail)
                        if not fresh_url:
                            logger.warning("cache_images: no image URL in detail for plant %d", plant_id)
                            failed += 1
                            error_messages.append(f"Plant {plant_id}: no image URL in Perenual detail")
                            continue

                        # Update image_url if changed
                        if fresh_url != current_url:
                            plant = await db.get(Plant, plant_id)
                            if plant:
                                plant.image_url = fresh_url
                                await db.commit()

                        # Retry download with refreshed URL
                        image_bytes = await _download_image(fresh_url)
                        if not image_bytes:
                            logger.warning("cache_images: download failed for plant %d (after refresh)", plant_id)
                            failed += 1
                            error_messages.append(f"Plant {plant_id}: download failed after URL refresh")
                            continue

                    # 3. Convert to WebP
                    webp_bytes = _convert_to_webp(image_bytes)
                    if not webp_bytes:
                        logger.warning("cache_images: WebP conversion failed for plant %d", plant_id)
                        failed += 1
                        error_messages.append(f"Plant {plant_id}: WebP conversion failed")
                        continue

                    # 4. Save
                    cache_path = _CACHE_DIR / f"{plant_id}.webp"
                    cache_path.write_bytes(webp_bytes)
                    cached += 1
                    logger.debug("cache_images: cached plant %d (%d bytes)", plant_id, len(webp_bytes))

                except RateLimitError as exc:
                    logger.warning("cache_images: rate limited after %d requests: %s", requests_used, exc)
                    error_messages.append(f"Rate limited after {requests_used} requests")
                    break

                except Exception as exc:
                    logger.warning("cache_images: error on plant %d: %s", plant_id, exc)
                    failed += 1
                    error_messages.append(f"Plant {plant_id}: {exc}")
                    continue

            # Finalize
            budget_exhausted = requests_used >= _REQUEST_BUDGET
            stats = {
                "new_species": cached,
                "updated": 0,
                "skipped": already_cached,
                "errors": failed,
            }
            if error_messages:
                run.error_detail = "\n".join(error_messages[:50])

            await complete_run(db, run, stats)
            await db.commit()

            logger.info(
                "cache_images: done — cached=%d, skipped=%d, failed=%d, requests=%d/%d",
                cached, already_cached, failed, requests_used, _REQUEST_BUDGET,
            )

            # Send email report
            await _send_report(
                run=run,
                cached=cached,
                already_cached=already_cached,
                failed=failed,
                total_with_image=total_with_image,
                requests_used=requests_used,
                budget_exhausted=budget_exhausted,
            )

        except Exception as exc:
            logger.exception("cache_images: unexpected error: %s", exc)
            try:
                await db.rollback()
                await fail_run(db, run, str(exc))
                await db.commit()
            except Exception:
                logger.exception("cache_images: could not persist failed status for run %d", run.id)
            raise


async def _send_report(
    run,
    cached: int,
    already_cached: int,
    failed: int,
    total_with_image: int,
    requests_used: int,
    budget_exhausted: bool,
) -> None:
    """Send email report for image cache run."""
    started = fmt(run.started_at) if run.started_at else "N/A"
    finished = fmt(run.finished_at) if run.finished_at else "N/A"

    elapsed = "N/A"
    if run.started_at and run.finished_at:
        delta = run.finished_at - run.started_at
        minutes = int(delta.total_seconds() // 60)
        seconds = int(delta.total_seconds() % 60)
        elapsed = f"{minutes}m {seconds}s"

    body = (
        f"LoamBase Image Cache Report\n\n"
        f"Started:  {started}\n"
        f"Finished: {finished}\n"
        f"Duration: {elapsed}\n\n"
        f"── Results ──────────────────────────────\n"
        f"Newly cached:    {cached:>6,}\n"
        f"Already cached:  {already_cached:>6,}\n"
        f"Failed:          {failed:>6,}\n"
        f"Total w/ image:  {total_with_image:>6,}\n\n"
        f"── API Usage ────────────────────────────\n"
        f"Requests used:   {requests_used:>6,} / {_REQUEST_BUDGET}\n"
    )

    if budget_exhausted:
        body += "\nBudget exhausted — remaining images will be cached on next run.\n"

    subject = "LoamBase Image Cache — Complete" if not budget_exhausted else "LoamBase Image Cache — Budget Reached"

    try:
        await send_email(subject, body)
    except Exception:
        logger.exception("cache_images: failed to send report email")
