"""
ARQ task: seed the Plant catalog from Perenual.

State is persisted in SeederRun so interrupted runs resume from the last
completed page rather than restarting from page 1.

Perenual free tier: 100 requests/day.
Each page fetch = 1 request; each species detail fetch = 1 request.
The task stops gracefully when the quota is exhausted and resumes the
next time it runs.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.logs import SeederRun
from app.models.plant import Plant
from app.services.perenual import RateLimitError, fetch_species_detail, fetch_species_list

logger = logging.getLogger(__name__)


# ── Field mapping helpers ──────────────────────────────────────────────────────

_CYCLE_MAP: dict[str, str] = {
    "annual": "annual",
    "biennial": "annual",
    "biannual": "annual",
    "perennial": "perennial",
    "shrub": "shrub",
    "tree": "tree",
}

_WATER_MAP: dict[str, str] = {
    "none": "low",
    "minimum": "low",
    "average": "medium",
    "frequent": "high",
}

_SUN_MAP: dict[str, str] = {
    "full_sun": "full_sun",
    "full sun": "full_sun",
    "part_shade": "partial_shade",
    "part shade": "partial_shade",
    "partial shade": "partial_shade",
    "filtered shade": "full_shade",
    "full_shade": "full_shade",
    "full shade": "full_shade",
}


def _map_cycle(cycle: Optional[str]) -> Optional[str]:
    if not cycle:
        return None
    return _CYCLE_MAP.get(cycle.lower())


def _map_water(watering: Optional[str]) -> Optional[str]:
    if not watering:
        return None
    return _WATER_MAP.get(watering.lower())


def _map_sun(sunlight: Optional[list]) -> Optional[str]:
    if not sunlight:
        return None
    for entry in sunlight:
        mapped = _SUN_MAP.get(str(entry).lower())
        if mapped:
            return mapped
    return None


def _hardiness_zones(hardiness: Optional[dict]) -> Optional[list[str]]:
    """Expand a {min, max} hardiness dict into a list of zone strings."""
    if not hardiness:
        return None
    try:
        lo = int(hardiness.get("min", 0) or 0)
        hi = int(hardiness.get("max", 0) or 0)
        if lo and hi and lo <= hi:
            return [str(z) for z in range(lo, hi + 1)]
    except (ValueError, TypeError):
        pass
    return None


def _image_url(detail: dict) -> Optional[str]:
    img = detail.get("default_image")
    if isinstance(img, dict):
        return img.get("original_url") or img.get("regular_url")
    return None


def _scientific_name(detail: dict) -> Optional[str]:
    sci = detail.get("scientific_name")
    if isinstance(sci, list) and sci:
        return sci[0]
    if isinstance(sci, str):
        return sci
    return None


def _pests(detail: dict) -> Optional[list[str]]:
    pests = detail.get("pest_susceptibility")
    if isinstance(pests, list) and pests:
        return [str(p) for p in pests if p]
    return None


def _plant_kwargs(detail: dict) -> dict:
    return {
        "common_name": detail.get("common_name") or "Unknown",
        "scientific_name": _scientific_name(detail),
        "plant_type": _map_cycle(detail.get("cycle")),
        "water_needs": _map_water(detail.get("watering")),
        "sun_requirement": _map_sun(detail.get("sunlight")),
        "hardiness_zones": _hardiness_zones(detail.get("hardiness")),
        "description": detail.get("description"),
        "image_url": _image_url(detail),
        "common_pests": _pests(detail),
        "source": "perenual",
        "external_id": str(detail["id"]),
        "is_user_defined": False,
    }


# ── DB helpers ─────────────────────────────────────────────────────────────────

_STALE_THRESHOLD = timedelta(hours=2)


async def _get_active_run(db: AsyncSession) -> Optional[SeederRun]:
    """Return a running SeederRun that started within the last 2 hours.

    Runs older than that are considered crashed/stale and are not treated as
    blocking — the caller will start a fresh run which resumes from the saved
    page.
    """
    cutoff = datetime.now(timezone.utc) - _STALE_THRESHOLD
    result = await db.execute(
        select(SeederRun)
        .where(SeederRun.status == "running", SeederRun.started_at >= cutoff)
        .order_by(SeederRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_last_run(db: AsyncSession) -> Optional[SeederRun]:
    """Return the most recent SeederRun regardless of status."""
    result = await db.execute(
        select(SeederRun).order_by(SeederRun.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _plant_exists(db: AsyncSession, perenual_id: str) -> bool:
    result = await db.execute(
        select(Plant.id).where(
            Plant.source == "perenual",
            Plant.external_id == perenual_id,
        )
    )
    return result.scalar_one_or_none() is not None


# ── Main task ──────────────────────────────────────────────────────────────────

async def seed_plants(ctx: dict) -> None:
    """
    Paginate through the Perenual species list and upsert plants into the
    local catalog. Persists progress in SeederRun for safe resumption.
    """
    async with AsyncSessionLocal() as db:
        # Guard: skip if a run is already in progress
        if await _get_active_run(db):
            logger.info("seed_plants: run already in progress, skipping")
            return

        # Guard: skip if catalog seeding is already complete
        last = await _get_last_run(db)
        if last and last.status == "complete":
            logger.info("seed_plants: catalog already complete, skipping")
            return

        # Determine start page.
        # current_page tracks the last successfully *committed* page, so we
        # always resume from current_page + 1 (handles failed, stale-running,
        # and fresh-start cases uniformly).
        start_page = (last.current_page + 1) if last else 1
        if start_page > 1:
            logger.info("seed_plants: resuming from page %d", start_page)

        run = SeederRun(
            status="running",
            current_page=start_page - 1,
            records_synced=0,
            requests_used=0,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()  # commit immediately so the run survives any later rollback

        logger.info("seed_plants: starting (run_id=%d, start_page=%d)", run.id, start_page)

        try:
            page = start_page
            while True:
                # ── Fetch species list page ────────────────────────────────
                logger.info("seed_plants: fetching page %d", page)
                try:
                    page_data = await fetch_species_list(page)
                except RateLimitError as exc:
                    logger.warning("seed_plants: rate limited on list fetch (page=%d): %s", page, exc)
                    run.status = "failed"
                    run.error_message = f"Rate limited on page {page}: {exc}"
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    return

                run.requests_used += 1

                # Set total_pages on first fetch
                if run.total_pages is None:
                    run.total_pages = page_data.get("last_page")
                    logger.info("seed_plants: total pages = %s", run.total_pages)

                species_list: list[dict] = page_data.get("data", [])
                if not species_list:
                    logger.info("seed_plants: empty page %d, stopping", page)
                    break

                # ── Process each species on this page ─────────────────────
                page_synced = 0
                for species in species_list:
                    species_id = species.get("id")
                    if species_id is None:
                        continue

                    perenual_id = str(species_id)
                    if await _plant_exists(db, perenual_id):
                        continue

                    # Fetch full detail
                    try:
                        detail = await fetch_species_detail(species_id)
                    except RateLimitError as exc:
                        logger.warning(
                            "seed_plants: rate limited on detail fetch (id=%d): %s",
                            species_id, exc,
                        )
                        run.requests_used += 1
                        run.status = "failed"
                        run.error_message = f"Rate limited on species detail {species_id}: {exc}"
                        run.current_page = page
                        run.records_synced += page_synced
                        run.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                        return

                    run.requests_used += 1
                    plant = Plant(**_plant_kwargs(detail))
                    db.add(plant)
                    page_synced += 1

                # ── Commit page progress ───────────────────────────────────
                run.current_page = page
                run.records_synced += page_synced
                await db.commit()
                logger.info(
                    "seed_plants: page %d done (+%d plants, total=%d, requests=%d)",
                    page, page_synced, run.records_synced, run.requests_used,
                )

                # Check if we've reached the last page
                last_page = page_data.get("last_page", 1)
                if page >= last_page:
                    logger.info("seed_plants: reached last page (%d), done", last_page)
                    break

                page += 1

            # All pages done
            run.status = "complete"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "seed_plants: complete — %d plants synced over %d requests",
                run.records_synced, run.requests_used,
            )

        except Exception as exc:
            logger.exception("seed_plants: unexpected error: %s", exc)
            try:
                await db.rollback()
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
            except Exception:
                logger.exception("seed_plants: could not persist failed status for run %d", run.id)
            raise
