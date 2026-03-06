"""
ARQ task: cache plant images as WebP files on disk.

Strategy (three-pass)
---------------------
Pass 0 — .jpg migration sweep: convert any legacy .jpg cache files to .webp.
Pass 1 — Direct URLs (Permapeople CDN, etc.): download and cache all plants
         whose image_url is NOT a Wasabi/Perenual signed URL. No API quota used.
Pass 2 — Wasabi/Perenual (quota-aware, URL-deduplicated): group plants by
         shared Wasabi URL, fetch a fresh signed URL from Perenual API once per
         unique URL, download once, write .webp for every plant_id in the group.

Budget cap: 90 Perenual API requests per run.
Tracks run via DataSourceRun (source="image_cache").
Sends email report on completion or budget exhaustion.
"""
import logging
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image
from sqlalchemy import func, select, update
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


# ── Pass 0: .jpg → .webp migration ──────────────────────────────


def _migrate_jpg_files() -> int:
    """Convert all .jpg files in the cache directory to .webp. Returns count."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    migrated = 0
    for jpg_path in _CACHE_DIR.glob("*.jpg"):
        try:
            img = Image.open(jpg_path)
            img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="WEBP", quality=80)
            webp_path = jpg_path.with_suffix(".webp")
            webp_path.write_bytes(buf.getvalue())
            jpg_path.unlink()
            migrated += 1
        except Exception as exc:
            logger.warning("cache_images: jpg migration failed for %s: %s", jpg_path.name, exc)
    if migrated:
        logger.info("cache_images: migrated %d .jpg files to .webp", migrated)
    return migrated


# ── Pass 1: Direct (non-Wasabi) URLs ────────────────────────────


async def _get_direct_plants(db: AsyncSession) -> list[tuple[int, str]]:
    """Plants with image_url that is NOT a Wasabi URL and has no .webp on disk."""
    result = await db.execute(
        select(Plant.id, Plant.image_url)
        .where(Plant.image_url.isnot(None))
        .where(~Plant.image_url.ilike("%wasabi%"))
    )
    rows = result.all()
    return [
        (pid, url) for pid, url in rows
        if not (_CACHE_DIR / f"{pid}.webp").exists()
    ]


async def _run_pass1(
    db: AsyncSession,
    error_messages: list[str],
) -> int:
    """Download and cache all direct-URL plants. Returns count cached."""
    plants = await _get_direct_plants(db)
    logger.info("cache_images: pass 1 — %d direct-URL plants to cache", len(plants))

    cached = 0
    for plant_id, image_url in plants:
        try:
            image_bytes = await _download_image(image_url)
            if not image_bytes:
                error_messages.append(f"Plant {plant_id}: direct download failed")
                continue

            webp_bytes = _convert_to_webp(image_bytes)
            if not webp_bytes:
                error_messages.append(f"Plant {plant_id}: WebP conversion failed")
                continue

            (_CACHE_DIR / f"{plant_id}.webp").write_bytes(webp_bytes)
            cached += 1
        except Exception as exc:
            error_messages.append(f"Plant {plant_id}: {exc}")

    logger.info("cache_images: pass 1 done — cached %d direct-URL plants", cached)
    return cached


# ── Pass 2: Wasabi/Perenual (deduplicated, quota-aware) ─────────


async def _get_wasabi_groups(db: AsyncSession) -> dict[str, list[int]]:
    """
    Plants with Wasabi image_url that have no .webp on disk,
    grouped by URL → list of plant_ids.
    """
    result = await db.execute(
        select(Plant.id, Plant.image_url)
        .where(Plant.image_url.isnot(None))
        .where(Plant.image_url.ilike("%wasabi%"))
    )
    rows = result.all()

    groups: dict[str, list[int]] = defaultdict(list)
    for pid, url in rows:
        if not (_CACHE_DIR / f"{pid}.webp").exists():
            groups[url].append(pid)
    return dict(groups)


async def _run_pass2(
    db: AsyncSession,
    error_messages: list[str],
) -> tuple[int, int]:
    """
    Deduplicated Wasabi pass. Returns (wasabi_cached, requests_used).
    """
    groups = await _get_wasabi_groups(db)
    logger.info(
        "cache_images: pass 2 — %d unique Wasabi URLs covering %d plants",
        len(groups),
        sum(len(v) for v in groups.values()),
    )

    wasabi_cached = 0
    requests_used = 0

    for old_url, plant_ids in groups.items():
        try:
            # Budget check
            if requests_used >= _REQUEST_BUDGET:
                logger.info("cache_images: pass 2 budget exhausted at %d requests", requests_used)
                break

            # Look up perenual_id via any plant in the group
            perenual_row = await db.execute(
                select(PerenualPlant.perenual_id)
                .where(PerenualPlant.plant_id.in_(plant_ids))
                .limit(1)
            )
            perenual_id = perenual_row.scalar_one_or_none()
            if perenual_id is None:
                logger.warning("cache_images: no perenual source for Wasabi group (%d plants)", len(plant_ids))
                for pid in plant_ids:
                    error_messages.append(f"Plant {pid}: Wasabi URL but no Perenual source")
                continue

            # Fetch fresh signed URL
            detail = await fetch_species_detail(perenual_id)
            requests_used += 1

            fresh_url = _image_url_from_detail(detail)
            if not fresh_url:
                logger.warning("cache_images: no image URL in Perenual detail for perenual_id=%d", perenual_id)
                for pid in plant_ids:
                    error_messages.append(f"Plant {pid}: no image URL in Perenual detail")
                continue

            # Update image_url for all plants in this group
            if fresh_url != old_url:
                await db.execute(
                    update(Plant)
                    .where(Plant.id.in_(plant_ids))
                    .values(image_url=fresh_url)
                )
                await db.commit()

            # Download once
            image_bytes = await _download_image(fresh_url)
            if not image_bytes:
                logger.warning("cache_images: download failed for Wasabi group (perenual_id=%d)", perenual_id)
                for pid in plant_ids:
                    error_messages.append(f"Plant {pid}: download failed after URL refresh")
                continue

            # Convert once
            webp_bytes = _convert_to_webp(image_bytes)
            if not webp_bytes:
                for pid in plant_ids:
                    error_messages.append(f"Plant {pid}: WebP conversion failed")
                continue

            # Write for every plant_id in the group
            for pid in plant_ids:
                (_CACHE_DIR / f"{pid}.webp").write_bytes(webp_bytes)
            wasabi_cached += len(plant_ids)

        except RateLimitError as exc:
            logger.warning("cache_images: rate limited after %d requests: %s", requests_used, exc)
            error_messages.append(f"Rate limited after {requests_used} requests")
            break

        except Exception as exc:
            logger.warning("cache_images: error on Wasabi group: %s", exc)
            for pid in plant_ids:
                error_messages.append(f"Plant {pid}: {exc}")

    logger.info("cache_images: pass 2 done — cached %d plants, used %d API requests", wasabi_cached, requests_used)
    return wasabi_cached, requests_used


# ── Main task ────────────────────────────────────────────────────


async def cache_images(ctx: dict, triggered_by: str = "cron") -> None:
    """
    Cache plant images as WebP files in three passes:
    Pass 0: migrate .jpg → .webp
    Pass 1: direct-URL plants (Permapeople CDN, etc.)
    Pass 2: Wasabi/Perenual plants (deduplicated, quota-aware)
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
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # Count total plants with images
            total_with_image = await db.scalar(
                select(func.count()).select_from(Plant).where(Plant.image_url.isnot(None))
            ) or 0

            # Count already-cached .webp files on disk before any work
            already_cached = sum(
                1 for f in _CACHE_DIR.iterdir()
                if f.is_file() and f.suffix == ".webp"
            )

            error_messages: list[str] = []

            # Pass 0: .jpg → .webp migration
            migrated = _migrate_jpg_files()

            # Pass 1: Direct URLs (no quota)
            direct_cached = await _run_pass1(db, error_messages)

            # Pass 2: Wasabi/Perenual (quota-aware, deduplicated)
            wasabi_cached, requests_used = await _run_pass2(db, error_messages)

            # Finalize
            total_cached = direct_cached + wasabi_cached
            total_failed = len(error_messages)
            budget_exhausted = requests_used >= _REQUEST_BUDGET

            stats = {
                "new_species": total_cached,
                "updated": migrated,
                "skipped": already_cached,
                "errors": total_failed,
            }
            if error_messages:
                run.error_detail = "\n".join(error_messages[:50])

            await complete_run(db, run, stats)
            await db.commit()

            logger.info(
                "cache_images: done — direct=%d, wasabi=%d, migrated=%d, skipped=%d, failed=%d, api_requests=%d/%d",
                direct_cached, wasabi_cached, migrated, already_cached, total_failed,
                requests_used, _REQUEST_BUDGET,
            )

            await _send_report(
                run=run,
                direct_cached=direct_cached,
                wasabi_cached=wasabi_cached,
                migrated=migrated,
                already_cached=already_cached,
                failed=total_failed,
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
    direct_cached: int,
    wasabi_cached: int,
    migrated: int,
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

    total_cached = direct_cached + wasabi_cached

    body = (
        f"LoamBase Image Cache Report\n\n"
        f"Started:  {started}\n"
        f"Finished: {finished}\n"
        f"Duration: {elapsed}\n\n"
        f"── Pass 1: Direct URLs (Permapeople CDN) ─\n"
        f"Newly cached:    {direct_cached:>6,}\n\n"
        f"── Pass 2: Wasabi/Perenual ──────────────\n"
        f"Newly cached:    {wasabi_cached:>6,}\n"
        f"API requests:    {requests_used:>6,} / {_REQUEST_BUDGET}\n\n"
        f"── Summary ─────────────────────────────\n"
        f"Total cached:    {total_cached:>6,}\n"
        f"JPG migrated:    {migrated:>6,}\n"
        f"Already cached:  {already_cached:>6,}\n"
        f"Failed:          {failed:>6,}\n"
        f"Total w/ image:  {total_with_image:>6,}\n"
    )

    if budget_exhausted:
        body += "\nBudget exhausted — remaining Wasabi images will be cached on next run.\n"

    subject = "LoamBase Image Cache — Complete" if not budget_exhausted else "LoamBase Image Cache — Budget Reached"

    try:
        await send_email(subject, body)
    except Exception:
        logger.exception("cache_images: failed to send report email")
