"""
ARQ task: seed the Plant catalog from Perenual.

Strategy
--------
Phase 1 — Backfill: fetch full detail for any existing perenual plants that are
missing water_needs (inserted before detail fetching was added). Counts against
the daily budget.

Phase 2 — Pagination: fetch one species-list page, then immediately fetch full
detail for each new species on that page. Commit after each complete page.

The daily request budget is capped at REQUEST_BUDGET. The task stops cleanly
when the budget is reached and sends an email summary. SeederRun state is
persisted so the next daily run resumes from the correct page.

Completion condition: last page reached AND a final backfill pass completes
without hitting the budget (i.e. no un-fetched plants remain). Future cron
invocations are skipped via the "complete" status guard.

Notifications
-------------
- Quota not reset at cron time: "LoamBase Seeder — Quota Not Reset"
  In a worker context, schedules retries at 06:00, 09:00, and 12:00 UTC before
  sending the email. Email is sent only if all three retries are also 429.
- Budget exhausted / rate-limited mid-run: "LoamBase Seeder — Daily Run Complete"
- All pages done: "LoamBase Seeder Complete"
- Unexpected error: "LoamBase Seeder — Error"
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.logs import SeederRun
from app.models.plant import Plant
from app.services.email import send_email
from app.services.perenual import RateLimitError, fetch_species_detail, fetch_species_list

logger = logging.getLogger(__name__)

_REQUEST_BUDGET = 95
_CRON_HOUR = 4              # daily seed_plants ARQ cron fires at this UTC hour
_RETRY_HOURS_UTC = [6, 9, 12]  # quota-not-reset retry schedule (UTC)


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


# ── Time helpers ───────────────────────────────────────────────────────────────

def _next_cron_local() -> datetime:
    """Tomorrow at _CRON_HOUR:00 in naive local time."""
    now = datetime.now()
    tomorrow = now.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, _CRON_HOUR, 0)


def _retry_utc(hour: int) -> datetime:
    """Today at the given UTC hour; advances to tomorrow if that time has already passed."""
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    return candidate


def _fmt(dt: datetime) -> str:
    """Format a naive-local or aware datetime as 'Monday, Feb 24 at 4:00 AM'."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%A, %b %-d at %-I:%M %p")


# ── DB helpers ─────────────────────────────────────────────────────────────────

_STALE_THRESHOLD = timedelta(hours=2)


async def _get_active_run(db: AsyncSession) -> Optional[SeederRun]:
    """Return a running SeederRun started within the last 2 hours."""
    cutoff = datetime.now(timezone.utc) - _STALE_THRESHOLD
    result = await db.execute(
        select(SeederRun)
        .where(SeederRun.status == "running", SeederRun.started_at >= cutoff)
        .order_by(SeederRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_last_run(db: AsyncSession) -> Optional[SeederRun]:
    result = await db.execute(
        select(SeederRun).order_by(SeederRun.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_first_run(db: AsyncSession) -> Optional[SeederRun]:
    result = await db.execute(
        select(SeederRun).order_by(SeederRun.started_at).limit(1)
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


async def _count_perenual_plants(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(Plant).where(Plant.source == "perenual")
    )
    return result.scalar_one()


async def _get_plants_to_backfill(db: AsyncSession) -> list[Plant]:
    """Plants inserted without full detail (water_needs IS NULL)."""
    result = await db.execute(
        select(Plant)
        .where(Plant.source == "perenual", Plant.water_needs.is_(None))
        .order_by(Plant.id)
    )
    return list(result.scalars().all())


# ── Notification helpers ───────────────────────────────────────────────────────

async def _notify_complete(db: AsyncSession, run: SeederRun) -> None:
    total = await _count_perenual_plants(db)
    first = await _get_first_run(db)
    days_taken = 1
    if first:
        days_taken = max(1, (datetime.now(timezone.utc) - first.started_at).days + 1)

    body = (
        f"The Perenual plant catalog seeder has finished.\n\n"
        f"Total records synced: {total:,}\n"
        f"Final page: {run.current_page} / {run.total_pages}\n"
        f"Total days taken: {days_taken}\n"
    )
    try:
        await send_email("LoamBase Seeder Complete", body)
    except Exception:
        logger.exception("seed_plants: failed to send complete notification")


async def _notify_daily(db: AsyncSession, run: SeederRun) -> None:
    total = await _count_perenual_plants(db)

    if run.total_pages is not None:
        pages_remaining = max(0, run.total_pages - run.current_page)
        pages_str = str(pages_remaining)
        days_str = str(math.ceil(pages_remaining * 31 / _REQUEST_BUDGET)) if pages_remaining else "0"
    else:
        pages_str = "Unknown"
        days_str = "Unknown"

    body = (
        f"Today's seeding run has reached the daily API request budget "
        f"({_REQUEST_BUDGET} requests).\n\n"
        f"Records synced today: {run.records_synced:,}\n"
        f"Total records in catalog: {total:,}\n"
        f"Current page: {run.current_page} / {run.total_pages or 'Unknown'}\n"
        f"Pages remaining: {pages_str}\n"
        f"Estimated days remaining: {days_str}\n\n"
        f"Next run scheduled: {_fmt(_next_cron_local())}"
    )
    try:
        await send_email("LoamBase Seeder — Daily Run Complete", body)
    except Exception:
        logger.exception("seed_plants: failed to send daily notification")


async def _handle_quota_not_reset(
    ctx: dict, db: AsyncSession, run: SeederRun, retry_count: int
) -> None:
    """
    Handle a quota-not-reset (429) response at the start of a run.

    In a worker context with retries remaining, enqueues the next attempt at the
    next hour in _RETRY_HOURS_UTC and returns without sending an email — the email
    is deferred until all retries are also exhausted.

    On the final retry (retry_count == len(_RETRY_HOURS_UTC)), or when running
    outside a worker context (manual trigger), sends a single summary email.
    """
    redis = ctx.get("redis")

    if redis and retry_count < len(_RETRY_HOURS_UTC):
        next_hour = _RETRY_HOURS_UTC[retry_count]
        next_dt = _retry_utc(next_hour)
        try:
            await redis.enqueue_job(
                "seed_plants",
                retry_count=retry_count + 1,
                _defer_until=next_dt,
            )
            logger.info(
                "seed_plants: quota not reset — retry %d/%d scheduled at %02d:00 UTC",
                retry_count + 1,
                len(_RETRY_HOURS_UTC),
                next_hour,
            )
            return  # email deferred; will fire after the final retry
        except Exception:
            logger.exception("seed_plants: could not schedule ARQ retry — sending email now")
            # fall through to send the email immediately

    # Send email: all retries exhausted, manual context, or scheduling failed.
    total = await _count_perenual_plants(db)

    if retry_count >= len(_RETRY_HOURS_UTC):
        attempt_hours = [_CRON_HOUR] + _RETRY_HOURS_UTC
        attempts_str = ", ".join(f"{h:02d}:00 UTC" for h in attempt_hours)
        body = (
            f"The Perenual daily API quota was unavailable at all scheduled attempts.\n\n"
            f"Attempts: {attempts_str} — all returned 429.\n"
            f"Quota appears to be on a rolling 24-hour window, not a calendar-day reset.\n\n"
            f"Current page: {run.current_page} / {run.total_pages or 'Unknown'}\n"
            f"Total records in catalog: {total:,}\n\n"
            f"Next run: {_fmt(_next_cron_local())} (daily cron)"
        )
    else:
        body = (
            f"The Perenual daily API quota was not yet available at "
            f"{_CRON_HOUR:02d}:00 UTC.\n\n"
            f"Current page: {run.current_page} / {run.total_pages or 'Unknown'}\n"
            f"Total records in catalog: {total:,}\n\n"
            f"Next run: {_fmt(_next_cron_local())} (daily cron)"
        )

    try:
        await send_email("LoamBase Seeder — Quota Not Reset", body)
    except Exception:
        logger.exception("seed_plants: failed to send quota-not-reset notification")


async def _notify_error(db: AsyncSession, run: SeederRun, error: str) -> None:
    body = (
        f"The Perenual plant catalog seeder encountered an unexpected error.\n\n"
        f"Error: {error}\n"
        f"Last page reached: {run.current_page}\n"
        f"Records synced this run: {run.records_synced:,}\n"
    )
    try:
        await send_email("LoamBase Seeder — Error", body)
    except Exception:
        logger.exception("seed_plants: failed to send error notification")


# ── Backfill phase ─────────────────────────────────────────────────────────────

async def _backfill_nulls(db: AsyncSession, run: SeederRun) -> bool:
    """
    Fetch full detail for existing perenual plants missing water_needs.
    Commits each plant update individually so partial progress is saved if the
    budget runs out mid-backfill.

    Returns True if the budget was exhausted or a rate-limit error occurred.
    """
    to_backfill = await _get_plants_to_backfill(db)
    if not to_backfill:
        return False

    logger.info("seed_plants: backfill — %d plants with missing data", len(to_backfill))

    for plant in to_backfill:
        if run.requests_used >= _REQUEST_BUDGET:
            logger.info("seed_plants: budget exhausted during backfill")
            await db.commit()
            return True

        try:
            detail = await fetch_species_detail(int(plant.external_id))
        except RateLimitError as exc:
            logger.warning("seed_plants: rate limited during backfill: %s", exc)
            await db.commit()
            return True

        run.requests_used += 1

        kwargs = _plant_kwargs(detail)
        for field, value in kwargs.items():
            if field not in ("source", "external_id", "is_user_defined"):
                setattr(plant, field, value)

        run.records_synced += 1
        await db.commit()

    logger.info("seed_plants: backfill complete")
    return False


# ── Main task ──────────────────────────────────────────────────────────────────

async def seed_plants(ctx: dict, retry_count: int = 0) -> None:
    """
    Paginate through the Perenual species list and populate the Plant catalog.
    Resumes from the last committed page on each daily run.

    retry_count is incremented by _handle_quota_not_reset each time an ARQ retry
    is scheduled (0 = initial cron invocation, 1–3 = quota-not-reset retries).
    """
    async with AsyncSessionLocal() as db:
        # Guard: skip if a fresh run is already in progress
        if await _get_active_run(db):
            logger.info("seed_plants: run already in progress, skipping")
            return

        # Guard: skip if catalog seeding is already complete
        last = await _get_last_run(db)
        if last and last.status == "complete":
            logger.info("seed_plants: catalog already complete, skipping")
            return

        # Resume from the page after the last committed one
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
        await db.commit()  # persist immediately so rollbacks don't lose the run record

        logger.info("seed_plants: starting (run_id=%d, start_page=%d)", run.id, start_page)

        try:
            # ── Phase 1: Backfill plants missing detail ────────────────────
            if await _backfill_nulls(db, run):
                run.finished_at = datetime.now(timezone.utc)
                if run.requests_used < _REQUEST_BUDGET:
                    # RateLimitError (429) during backfill — quota not reset
                    run.status = "failed"
                    run.error_message = "Rate limited during backfill (quota not reset)"
                    await db.commit()
                    await _handle_quota_not_reset(ctx, db, run, retry_count)
                else:
                    # Budget cap reached during backfill
                    run.status = "failed"
                    run.error_message = f"Daily budget reached ({_REQUEST_BUDGET} requests) during backfill"
                    await db.commit()
                    await _notify_daily(db, run)
                return

            # ── Phase 2: Paginate new species ──────────────────────────────
            page = start_page
            catalog_complete = False

            while True:
                # Budget check before the list-page fetch (1 request)
                if run.requests_used >= _REQUEST_BUDGET:
                    logger.info("seed_plants: budget exhausted before page %d list fetch", page)
                    break

                logger.info("seed_plants: fetching page %d", page)
                try:
                    page_data = await fetch_species_list(page)
                except RateLimitError as exc:
                    logger.warning("seed_plants: rate limited on list fetch (page=%d): %s", page, exc)
                    run.status = "failed"
                    run.error_message = (
                        f"Quota not reset at {_CRON_HOUR:02d}:00 UTC (page {page})"
                        if run.requests_used == 0
                        else f"Rate limited on page {page}: {exc}"
                    )
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()

                    if run.requests_used == 0:
                        await _handle_quota_not_reset(ctx, db, run, retry_count)
                    else:
                        await _notify_daily(db, run)
                    return

                run.requests_used += 1

                if run.total_pages is None:
                    run.total_pages = page_data.get("last_page")
                    logger.info("seed_plants: total pages = %s", run.total_pages)

                species_list: list[dict] = page_data.get("data", [])
                if not species_list:
                    logger.info("seed_plants: empty page %d, stopping", page)
                    catalog_complete = True
                    break

                # ── Fetch detail for each new species on this page ─────────
                page_synced = 0
                budget_hit = False

                for species in species_list:
                    species_id = species.get("id")
                    if species_id is None:
                        continue

                    # Budget check before each detail fetch (1 request each)
                    if run.requests_used >= _REQUEST_BUDGET:
                        logger.info(
                            "seed_plants: budget exhausted mid-page %d (after %d new plants)",
                            page, page_synced,
                        )
                        budget_hit = True
                        break

                    if await _plant_exists(db, str(species_id)):
                        continue

                    try:
                        detail = await fetch_species_detail(species_id)
                    except RateLimitError as exc:
                        logger.warning(
                            "seed_plants: rate limited on detail fetch (id=%d): %s",
                            species_id, exc,
                        )
                        budget_hit = True
                        break

                    run.requests_used += 1
                    db.add(Plant(**_plant_kwargs(detail)))
                    page_synced += 1

                # ── Commit what we have for this page ──────────────────────
                if budget_hit:
                    # Don't advance current_page — next run retries from this page.
                    # Commit partial inserts so the API calls aren't wasted;
                    # _plant_exists will skip them on retry.
                    run.records_synced += page_synced
                    await db.commit()
                    logger.info(
                        "seed_plants: partial page %d committed (%d plants), stopping",
                        page, page_synced,
                    )
                    break

                run.current_page = page
                run.records_synced += page_synced
                await db.commit()
                logger.info(
                    "seed_plants: page %d done (+%d plants, total=%d, requests=%d/%d)",
                    page, page_synced, run.records_synced, run.requests_used, _REQUEST_BUDGET,
                )

                last_page = page_data.get("last_page", 1)
                if page >= last_page:
                    logger.info("seed_plants: reached last page (%d), done", last_page)
                    catalog_complete = True
                    break

                page += 1

            # ── Finalise run ───────────────────────────────────────────────
            if catalog_complete:
                # Run a final backfill pass to clear any nulls from phase 2
                # insertions. Completion requires last page reached AND this
                # pass finishing without hitting the budget.
                if await _backfill_nulls(db, run):
                    run.status = "failed"
                    run.error_message = "Budget reached during final backfill"
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    await _notify_daily(db, run)
                else:
                    run.status = "complete"
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(
                        "seed_plants: complete — %d plants synced over %d requests",
                        run.records_synced, run.requests_used,
                    )
                    await _notify_complete(db, run)
            else:
                run.status = "failed"
                run.error_message = f"Daily budget reached ({_REQUEST_BUDGET} requests)"
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                await _notify_daily(db, run)

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
            await _notify_error(db, run, str(exc))
            raise
