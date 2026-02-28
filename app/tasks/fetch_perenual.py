"""
ARQ task: fetch plant data from the Perenual API into perenual_plants.

Strategy
--------
List-only: fetch one species-list page per iteration (1 request per page).
Extract common_name, scientific_name, default_image, and id from each species.
Writes to the perenual_plants source table. For each new species, matches by
scientific_name to the canonical plants table — creating a new plants row if
no match exists.

Care fields (watering, sunlight, hardiness, etc.) are NULL on the free tier and
will be populated later by the enrichment engine using other data sources.

The daily request budget is capped at REQUEST_BUDGET. At 1 request per page
(30 species), 95 pages/day, all 337 pages complete in ~4 days. The task stops
cleanly when the budget is reached and sends an email summary. SeederRun state
is persisted so the next daily run resumes from the correct page.

Notifications
-------------
- Quota not reset at cron time: "LoamBase Perenual Fetch — Quota Not Reset"
  In a worker context, schedules retries at 06:00, 09:00, and 12:00 UTC before
  sending the email. Email is sent only if all three retries are also 429.
- Budget exhausted / rate-limited mid-run: "LoamBase Perenual Fetch — Daily Run Complete"
- All pages done: "LoamBase Perenual Fetch Complete"
- Unexpected error: "LoamBase Perenual Fetch — Error"
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
from app.models.source_perenual import PerenualPlant
from app.services.email import send_email
from app.services.perenual import RateLimitError, fetch_species_list
from app.tasks.fetch_utils import to_local, fmt, find_plant_by_scientific_name

logger = logging.getLogger(__name__)

_REQUEST_BUDGET = 95
_CRON_HOUR = 4              # daily fetch_perenual ARQ cron fires at this UTC hour
_RETRY_HOURS_UTC = [6, 9, 12]  # quota-not-reset retry schedule (UTC)


# ── Field helpers ─────────────────────────────────────────────────────────────

def _image_url(species: dict) -> Optional[str]:
    img = species.get("default_image")
    if isinstance(img, dict):
        return img.get("original_url") or img.get("regular_url")
    return None


def _scientific_name(species: dict) -> Optional[str]:
    sci = species.get("scientific_name")
    if isinstance(sci, list) and sci:
        return sci[0]
    if isinstance(sci, str):
        return sci
    return None


# ── Time helpers ───────────────────────────────────────────────────────────────


def _next_cron_local() -> datetime:
    """Tomorrow at _CRON_HOUR:00 UTC, converted to local time."""
    now = datetime.now(timezone.utc)
    tomorrow = now.date() + timedelta(days=1)
    cron_utc = datetime(tomorrow.year, tomorrow.month, tomorrow.day, _CRON_HOUR, 0, tzinfo=timezone.utc)
    return to_local(cron_utc)


def _retry_utc(hour: int) -> datetime:
    """Today at the given UTC hour; advances to tomorrow if that time has already passed."""
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    return candidate


def _run_times(run: SeederRun) -> str:
    """Format started_at and finished_at for email bodies."""
    parts = []
    if run.started_at:
        parts.append(f"Started: {fmt(run.started_at)}")
    if run.finished_at:
        parts.append(f"Finished: {fmt(run.finished_at)}")
    return "\n".join(parts)


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


async def _perenual_plant_exists(db: AsyncSession, perenual_id: int) -> bool:
    result = await db.execute(
        select(PerenualPlant.id).where(PerenualPlant.perenual_id == perenual_id)
    )
    return result.scalar_one_or_none() is not None


async def _count_perenual_plants(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(PerenualPlant)
    )
    return result.scalar_one()


# ── Notification helpers ───────────────────────────────────────────────────────

async def _notify_complete(db: AsyncSession, run: SeederRun) -> None:
    total = await _count_perenual_plants(db)
    first = await _get_first_run(db)
    days_taken = 1
    if first:
        days_taken = max(1, (datetime.now(timezone.utc) - first.started_at).days + 1)

    body = (
        f"The Perenual plant fetch has finished.\n\n"
        f"Total records fetched: {total:,}\n"
        f"Final page: {run.current_page} / {run.total_pages}\n"
        f"Total days taken: {days_taken}\n\n"
        f"{_run_times(run)}"
    )
    try:
        await send_email("LoamBase Perenual Fetch Complete", body)
    except Exception:
        logger.exception("fetch_perenual: failed to send complete notification")


async def _notify_daily(db: AsyncSession, run: SeederRun) -> None:
    total = await _count_perenual_plants(db)

    if run.total_pages is not None:
        pages_remaining = max(0, run.total_pages - run.current_page)
        pages_str = str(pages_remaining)
        # 1 request per page with list-only strategy
        days_str = str(math.ceil(pages_remaining / _REQUEST_BUDGET)) if pages_remaining else "0"
    else:
        pages_str = "Unknown"
        days_str = "Unknown"

    body = (
        f"Today's Perenual fetch has reached the daily API request budget "
        f"({_REQUEST_BUDGET} requests).\n\n"
        f"Records fetched today: {run.records_synced:,}\n"
        f"Total records in source table: {total:,}\n"
        f"Current page: {run.current_page} / {run.total_pages or 'Unknown'}\n"
        f"Pages remaining: {pages_str}\n"
        f"Estimated days remaining: {days_str}\n\n"
        f"{_run_times(run)}\n\n"
        f"Next run scheduled: {fmt(_next_cron_local())}"
    )
    try:
        await send_email("LoamBase Perenual Fetch — Daily Run Complete", body)
    except Exception:
        logger.exception("fetch_perenual: failed to send daily notification")


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
                "fetch_perenual",
                retry_count=retry_count + 1,
                _defer_until=next_dt,
            )
            logger.info(
                "fetch_perenual: quota not reset — retry %d/%d scheduled at %02d:00 UTC",
                retry_count + 1,
                len(_RETRY_HOURS_UTC),
                next_hour,
            )
            return  # email deferred; will fire after the final retry
        except Exception:
            logger.exception("fetch_perenual: could not schedule ARQ retry — sending email now")
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
            f"Total records in source table: {total:,}\n\n"
            f"{_run_times(run)}\n\n"
            f"Next run: {fmt(_next_cron_local())} (daily cron)"
        )
    else:
        body = (
            f"The Perenual daily API quota was not yet available at "
            f"{_CRON_HOUR:02d}:00 UTC.\n\n"
            f"Current page: {run.current_page} / {run.total_pages or 'Unknown'}\n"
            f"Total records in source table: {total:,}\n\n"
            f"{_run_times(run)}\n\n"
            f"Next run: {fmt(_next_cron_local())} (daily cron)"
        )

    try:
        await send_email("LoamBase Perenual Fetch — Quota Not Reset", body)
    except Exception:
        logger.exception("fetch_perenual: failed to send quota-not-reset notification")


async def _notify_error(db: AsyncSession, run: SeederRun, error: str) -> None:
    body = (
        f"The Perenual plant fetch encountered an unexpected error.\n\n"
        f"Error: {error}\n"
        f"Last page reached: {run.current_page}\n"
        f"Records fetched this run: {run.records_synced:,}\n\n"
        f"{_run_times(run)}"
    )
    try:
        await send_email("LoamBase Perenual Fetch — Error", body)
    except Exception:
        logger.exception("fetch_perenual: failed to send error notification")


# ── Main task ──────────────────────────────────────────────────────────────────

async def fetch_perenual(ctx: dict, retry_count: int = 0) -> None:
    """
    Paginate through the Perenual species list and populate the perenual_plants
    source table. For each new species, matches to the canonical plants table
    by scientific_name — creating a new plants row if no match exists.

    Resumes from the last committed page on each daily run.

    List-only strategy: 1 request per page (30 species). Care fields are not
    available on the Perenual free tier — they will be populated by the
    enrichment engine using other data sources.

    retry_count is incremented by _handle_quota_not_reset each time an ARQ retry
    is scheduled (0 = initial cron invocation, 1–3 = quota-not-reset retries).
    """
    async with AsyncSessionLocal() as db:
        # Guard: skip if a fresh run is already in progress
        if await _get_active_run(db):
            logger.info("fetch_perenual: run already in progress, skipping")
            return

        # Guard: skip if catalog fetch is already complete
        last = await _get_last_run(db)
        if last and last.status == "complete":
            logger.info("fetch_perenual: catalog already complete, skipping")
            return

        # Resume from the page after the last committed one
        start_page = (last.current_page + 1) if last else 1
        if start_page > 1:
            logger.info("fetch_perenual: resuming from page %d", start_page)

        run = SeederRun(
            status="running",
            current_page=start_page - 1,
            records_synced=0,
            requests_used=0,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()  # persist immediately so rollbacks don't lose the run record

        logger.info("fetch_perenual: starting (run_id=%d, start_page=%d)", run.id, start_page)

        try:
            page = start_page
            catalog_complete = False

            while True:
                # Budget check before the list-page fetch (1 request)
                if run.requests_used >= _REQUEST_BUDGET:
                    logger.info("fetch_perenual: budget exhausted before page %d", page)
                    break

                logger.info("fetch_perenual: fetching page %d", page)
                try:
                    page_data = await fetch_species_list(page)
                except RateLimitError as exc:
                    logger.warning("fetch_perenual: rate limited on list fetch (page=%d): %s", page, exc)
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
                    logger.info("fetch_perenual: total pages = %s", run.total_pages)

                species_list: list[dict] = page_data.get("data", [])
                if not species_list:
                    logger.info("fetch_perenual: empty page %d, stopping", page)
                    catalog_complete = True
                    break

                # ── Insert new species from this page ─────────────────────
                page_synced = 0

                for species in species_list:
                    species_id = species.get("id")
                    if species_id is None:
                        continue

                    if await _perenual_plant_exists(db, species_id):
                        continue

                    common_name = species.get("common_name") or "Unknown"
                    sci_name = _scientific_name(species)
                    image_url = _image_url(species)

                    # Match to canonical plants table by scientific_name
                    plant = None
                    if sci_name:
                        plant = await find_plant_by_scientific_name(db, sci_name)

                    # Create a new plants row if no match
                    if plant is None:
                        plant = Plant(
                            common_name=common_name,
                            scientific_name=sci_name,
                            image_url=image_url,
                            source="perenual",
                            external_id=str(species_id),
                            is_user_defined=False,
                            data_sources=["perenual"],
                        )
                        db.add(plant)
                        await db.flush()  # get plant.id for the FK

                    # Insert PerenualPlant source row
                    pp = PerenualPlant(
                        perenual_id=species_id,
                        plant_id=plant.id,
                        common_name=common_name,
                        scientific_name=sci_name,
                        image_url=image_url,
                    )
                    db.add(pp)
                    page_synced += 1

                run.current_page = page
                run.records_synced += page_synced
                await db.commit()
                logger.info(
                    "fetch_perenual: page %d done (+%d species, total=%d, requests=%d/%d)",
                    page, page_synced, run.records_synced, run.requests_used, _REQUEST_BUDGET,
                )

                last_page = page_data.get("last_page", 1)
                if page >= last_page:
                    logger.info("fetch_perenual: reached last page (%d), done", last_page)
                    catalog_complete = True
                    break

                page += 1

            # ── Finalise run ───────────────────────────────────────────────
            if catalog_complete:
                run.status = "complete"
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info(
                    "fetch_perenual: complete — %d species fetched over %d requests",
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
            logger.exception("fetch_perenual: unexpected error: %s", exc)
            try:
                await db.rollback()
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
            except Exception:
                logger.exception("fetch_perenual: could not persist failed status for run %d", run.id)
            await _notify_error(db, run, str(exc))
            raise
