"""
Shared utilities for data source fetch tasks.

Provides timezone helpers, plant matching, DataSourceRun lifecycle management,
and email reporting — used by fetch_perenual and fetch_permapeople.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.data_source_run import DataSourceRun
from app.models.plant import Plant
from app.services.email import send_email

logger = logging.getLogger(__name__)

_tz = ZoneInfo(settings.TIMEZONE)
_STALE_THRESHOLD = timedelta(hours=2)


# ── Time helpers ──────────────────────────────────────────────────────────────

def to_local(dt: datetime) -> datetime:
    """Convert an aware datetime to the configured local timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz)


def fmt(dt: datetime) -> str:
    """Format an aware datetime in local time as 'Monday, Feb 24 at 4:00 AM CST'."""
    local = to_local(dt)
    return local.strftime("%A, %b %-d at %-I:%M %p %Z")


# ── Plant matching ────────────────────────────────────────────────────────────

async def find_plant_by_scientific_name(db: AsyncSession, sci_name: str) -> Optional[Plant]:
    """Find a canonical plant by scientific_name (case-insensitive)."""
    result = await db.execute(
        select(Plant).where(func.lower(Plant.scientific_name) == func.lower(sci_name)).limit(1)
    )
    return result.scalar_one_or_none()


# ── DataSourceRun lifecycle ───────────────────────────────────────────────────

def start_run(db: AsyncSession, source: str, triggered_by: str) -> DataSourceRun:
    """Create a DataSourceRun with status='running'. Caller must commit."""
    run = DataSourceRun(
        source=source,
        status="running",
        triggered_by=triggered_by,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    return run


async def complete_run(db: AsyncSession, run: DataSourceRun, stats: dict) -> None:
    """Set status='completed', finished_at=now(), populate stats. Caller must commit."""
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    for key in ("new_species", "updated", "gap_filled", "unchanged", "skipped", "errors"):
        if key in stats:
            setattr(run, key, stats[key])


async def fail_run(db: AsyncSession, run: DataSourceRun, error: str) -> None:
    """Set status='failed', finished_at=now(), error_detail. Caller must commit."""
    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    run.error_detail = error[:4000] if error else None


async def is_source_running(db: AsyncSession, source: str) -> bool:
    """Check if a DataSourceRun with status='running' exists for source (within last 2 hours)."""
    cutoff = datetime.now(timezone.utc) - _STALE_THRESHOLD
    result = await db.execute(
        select(DataSourceRun.id)
        .where(
            DataSourceRun.source == source,
            DataSourceRun.status == "running",
            DataSourceRun.started_at >= cutoff,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── Email reporting ───────────────────────────────────────────────────────────

async def send_fetch_report(
    source: str,
    run: DataSourceRun,
    changes: list[str],
    total_count: int,
    matched_count: int,
    plants_total: int = 0,
    new_plants_created: int = 0,
    matched_existing: int = 0,
    coverage: dict[str, int] | None = None,
) -> None:
    """Send structured email report using send_email()."""
    source_title = source.capitalize()
    started = fmt(run.started_at) if run.started_at else "N/A"
    finished = fmt(run.finished_at) if run.finished_at else "N/A"

    elapsed = "N/A"
    if run.started_at and run.finished_at:
        delta = run.finished_at - run.started_at
        minutes = int(delta.total_seconds() // 60)
        seconds = int(delta.total_seconds() % 60)
        elapsed = f"{minutes}m {seconds}s"

    # ── Results section (right-aligned numbers) ──
    results_lines = [
        ("New species added:", run.new_species),
    ]
    if new_plants_created or matched_existing:
        results_lines.append(("  New plants created:", new_plants_created))
        results_lines.append(("  Matched existing:", matched_existing))
    results_lines.extend([
        ("Updated:", run.updated),
        ("Gaps filled:", run.gap_filled),
        ("Unchanged:", run.unchanged),
        ("Skipped:", run.skipped),
        ("Errors:", run.errors),
    ])

    # Find max width for right-aligning numbers
    max_label = max(len(label) for label, _ in results_lines)
    max_num = max(len(f"{val:,}") for _, val in results_lines)
    results_section = "\n".join(
        f"{label:<{max_label}} {val:>{max_num},}" for label, val in results_lines
    )

    # ── Totals section ──
    totals_section = f"Source table:  {total_count:,}\n"
    if plants_total:
        totals_section += f"Plants table: {plants_total:,} (matched: {matched_count:,})"
    else:
        totals_section += f"Matched to plants table: {matched_count:,}"

    # ── Coverage section ──
    coverage_section = ""
    if coverage:
        visible = {k: v for k, v in coverage.items() if v > 0}
        if visible:
            max_cov_label = max(len(k) for k in visible)
            max_cov_num = max(len(f"{v:,}") for v in visible.values())
            cov_lines = []
            for label, count in visible.items():
                pct = int(count * 100 / total_count) if total_count else 0
                cov_lines.append(
                    f"{label + ':':<{max_cov_label + 1}} {count:>{max_cov_num},} / {total_count:,} ({pct}%)"
                )
            coverage_section = "\n".join(cov_lines)

    # ── Changes / initial load section ──
    is_initial = (
        run.skipped == 0
        and run.new_species > 0
        and run.updated == 0
        and run.gap_filled == 0
    )

    if is_initial:
        changes_section = f"Initial load complete — {run.new_species:,} species imported."
    elif changes:
        shown = changes[:50]
        changes_section = "\n".join(shown)
        if len(changes) > 50:
            changes_section += f"\n...and {len(changes) - 50} more"
    else:
        changes_section = ""

    # ── Assemble body ──
    body = (
        f"LoamBase {source_title} Fetch Report\n\n"
        f"Started:  {started}\n"
        f"Finished: {finished}\n"
        f"Duration: {elapsed}\n\n"
        f"── Results ──────────────────────────────\n"
        f"{results_section}\n\n"
        f"── Totals ───────────────────────────────\n"
        f"{totals_section}\n"
    )

    if coverage_section:
        body += (
            f"\n── Field Coverage ───────────────────────\n"
            f"{coverage_section}\n"
        )

    if changes_section:
        body += f"\n{changes_section}\n"

    subject = f"LoamBase {source_title} Fetch — {'Complete' if run.status == 'completed' else 'Report'}"

    try:
        await send_email(subject, body)
    except Exception:
        logger.exception("send_fetch_report: failed to send %s report email", source)
