"""
ARQ task: fetch plant data from the Permapeople API into permapeople_plants.

Strategy
--------
Two-pass approach:
  Pass 1 — New species discovery: paginate all plants via last_id cursor.
           Insert new PermapeoplePlant rows, match to canonical plants table.
  Pass 2 — Update detection: fetch plants updated since the last fetched_at.
           Detect version bumps (update), gap-fill nulls, or skip unchanged.

Triggered on-demand only (no cron). Can be triggered via:
  - Admin endpoint: POST /admin/fetch/permapeople
  - Manual script: run_fetch_permapeople.py
"""
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.plant import Plant
from app.models.source_permapeople import PermapeoplePlant
from app.services.email import send_email
from app.services.permapeople import PermapeopleAPIError, fetch_plant_list
from app.tasks.fetch_utils import (
    complete_run,
    fail_run,
    find_plant_by_name,
    fmt,
    is_source_running,
    send_fetch_report,
    start_run,
)

logger = logging.getLogger(__name__)


# ── KEY_MAP: Permapeople data[] key-value pairs → model columns ──────────────

COVERAGE_FIELDS = {
    "Water requirement": "water_requirement",
    "Light requirement": "light_requirement",
    "Hardiness zone": "hardiness_zone",
    "Soil type": "soil_type",
    "Edible": "edible",
    "Height": "height",
    "Life cycle": "life_cycle",
    "Medicinal": "medicinal",
    "Native to": "native_to",
    "Soil pH": "soil_ph",
    "Growth": "growth",
    "Family": "family",
}

KEY_MAP = {
    "Water requirement": "water_requirement",
    "Light requirement": "light_requirement",
    "USDA Hardiness zone": "hardiness_zone",
    "Growth": "growth",
    "Soil type": "soil_type",
    "Soil pH": "soil_ph",
    "Layer": "layer",
    "Edible": "edible",
    "Edible parts": "edible_parts",
    "Edible uses": "edible_uses",
    "Family": "family",
    "Genus": "genus",
    "Height": "height",
    "Width": "width",
    "Spacing": "spacing",
    "Life cycle": "life_cycle",
    "Days to harvest": "days_to_harvest",
    "Days to maturity": "days_to_maturity",
    "Propagation method": "propagation_method",
    "Propagation - Cuttings": "propagation_cuttings",
    "Propagation - Direct sowing": "propagation_direct_sowing",
    "Propagation - Transplanting": "propagation_transplanting",
    "Germination time": "germination_time",
    "Germination temperature": "germination_temperature",
    "When to sow (outdoors)": "sow_outdoors",
    "When to sow (indoors)": "sow_indoors",
    "When to start indoors (weeks)": "start_indoors_weeks",
    "When to start outdoors (weeks)": "start_outdoors_weeks",
    "When to plant (transplant)": "plant_transplant",
    "When to plant (cuttings)": "plant_cuttings",
    "When to plant (division)": "plant_division",
    "Seed planting depth": "seed_planting_depth",
    "Seed viability": "seed_viability",
    "1000 Seed Weight (g)": "seed_weight_per_1000_g",
    "Nitrogen Fixing": "nitrogen_fixing",
    "Nitrogen Usage": "nitrogen_usage",
    "Drought resistant": "drought_resistant",
    "Native to": "native_to",
    "Introduced into": "introduced_into",
    "Habitat": "habitat",
    "Root type": "root_type",
    "Root depth": "root_depth",
    "Leaves": "leaves",
    "Pests": "pests",
    "Diseases": "diseases",
    "Pollination": "pollination",
    "Medicinal": "medicinal",
    "Medicinal parts": "medicinal_parts",
    "Utility": "utility",
    "Warning": "warning",
    "Alternate name": "alternate_name",
    "Wikipedia": "wikipedia_url",
    "Plants For A Future": "pfaf_url",
    "Plants of the World Online": "powo_url",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_data_keys(data: list[dict] | None) -> dict[str, str]:
    """Parse Permapeople data[] key-value pairs into model column values."""
    if not data:
        return {}
    result = {}
    for item in data:
        key = item.get("key", "")
        value = item.get("value")
        if key in KEY_MAP and value:
            col = KEY_MAP[key]
            result[col] = str(value).strip() if value else None
    return result


def _extract_image_url(plant_data: dict) -> Optional[str]:
    """Extract image URL from Permapeople plant response."""
    images = plant_data.get("images")
    if isinstance(images, dict):
        return images.get("title") or images.get("thumb") or None
    return None


async def _permapeople_exists(db: AsyncSession, permapeople_id: int) -> Optional[PermapeoplePlant]:
    """Return the existing PermapeoplePlant if it exists, else None."""
    result = await db.execute(
        select(PermapeoplePlant).where(PermapeoplePlant.permapeople_id == permapeople_id)
    )
    return result.scalar_one_or_none()


async def _count_permapeople(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(PermapeoplePlant))
    return result.scalar_one()


async def _count_matched(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(PermapeoplePlant).where(PermapeoplePlant.plant_id.isnot(None))
    )
    return result.scalar_one()


async def _insert_new_species(
    db: AsyncSession, plant_data: dict, parsed: dict[str, str], stats: dict, changes: list[str]
) -> None:
    """Insert a new PermapeoplePlant and match/create canonical plant."""
    permapeople_id = plant_data["id"]
    common_name = plant_data.get("name") or "Unknown"
    sci_name = plant_data.get("scientific_name")
    description = plant_data.get("description")
    image_url = _extract_image_url(plant_data)
    slug = plant_data.get("slug")
    version = plant_data.get("version")

    # Match to canonical plants table by scientific_name + common_name
    plant = None
    if sci_name:
        plant = await find_plant_by_name(db, sci_name, common_name)

    if plant is None:
        plant = Plant(
            common_name=common_name,
            scientific_name=sci_name,
            image_url=image_url,
            source="permapeople",
            external_id=str(permapeople_id),
            is_user_defined=False,
            data_sources=["permapeople"],
        )
        db.add(plant)
        await db.flush()
        stats["new_plants_created"] += 1
    else:
        stats["matched_existing"] += 1

    pp = PermapeoplePlant(
        permapeople_id=permapeople_id,
        plant_id=plant.id,
        common_name=common_name,
        scientific_name=sci_name,
        description=description,
        image_url=image_url,
        slug=slug,
        version=version,
        **parsed,
    )
    db.add(pp)
    stats["new_species"] += 1
    changes.append(f"Added: {sci_name or common_name} ({common_name})")


# ── Main task ─────────────────────────────────────────────────────────────────

async def fetch_permapeople(ctx: dict, triggered_by: str = "manual", force_full: bool = False) -> None:
    """
    Fetch plant data from the Permapeople API in two passes:
    Pass 1: discover new species via full pagination (first run or force_full only).
    Pass 2: detect updates via updated_since filter.
    """
    async with AsyncSessionLocal() as db:
        # Guard: skip if already running
        if await is_source_running(db, "permapeople"):
            logger.info("fetch_permapeople: already running, skipping")
            return

        run = start_run(db, "permapeople", triggered_by)
        await db.commit()
        await db.refresh(run)

        logger.info("fetch_permapeople: starting (run_id=%d, triggered_by=%s)", run.id, triggered_by)

        stats = {
            "new_species": 0,
            "updated": 0,
            "gap_filled": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "new_plants_created": 0,
            "matched_existing": 0,
        }
        changes: list[str] = []
        error_messages: list[str] = []

        try:
            # ── Pass 1: New species discovery ─────────────────────────
            existing_count = await _count_permapeople(db)
            run_full = force_full or existing_count == 0

            if not run_full:
                logger.info(
                    "fetch_permapeople: Pass 1 skipped — %d species already loaded (incremental mode)",
                    existing_count,
                )
            else:
                logger.info("fetch_permapeople: Pass 1 — new species discovery")
                last_id: int | None = None
                page_num = 0

                while True:
                    page_num += 1
                    try:
                        page_data = await fetch_plant_list(last_id=last_id)
                    except PermapeopleAPIError as exc:
                        logger.error("fetch_permapeople: API error on page %d: %s", page_num, exc)
                        stats["errors"] += 1
                        break

                    plants_list = page_data.get("plants", [])
                    if not plants_list:
                        logger.info("fetch_permapeople: Pass 1 — no more plants after page %d", page_num)
                        break

                    for p in plants_list:
                        pid = p.get("id")
                        if pid is None:
                            continue

                        existing = await _permapeople_exists(db, pid)
                        if existing:
                            stats["skipped"] += 1
                            last_id = pid
                            continue

                        parsed = _parse_data_keys(p.get("data"))
                        try:
                            await _insert_new_species(db, p, parsed, stats, changes)
                        except Exception as exc:
                            sci_name = p.get("scientific_name") or "unknown"
                            logger.warning("fetch_permapeople: error inserting permapeople_id=%d: %s", pid, exc)
                            stats["errors"] += 1
                            error_messages.append(f"Plant {pid} ({sci_name}): {exc}")
                            await db.rollback()

                        last_id = pid

                    await db.commit()
                    logger.info(
                        "fetch_permapeople: Pass 1 page %d done (new=%d, skipped=%d, errors=%d)",
                        page_num, stats["new_species"], stats["skipped"], stats["errors"],
                    )
                    await asyncio.sleep(1.0)

            # ── Pass 2: Update detection ──────────────────────────────
            max_fetched_result = await db.execute(
                select(func.max(PermapeoplePlant.fetched_at))
            )
            max_fetched = max_fetched_result.scalar_one_or_none()

            if max_fetched is None or stats["new_species"] > 0 and stats["skipped"] == 0:
                # First run or all new — skip pass 2
                logger.info("fetch_permapeople: Pass 2 — skipped (first run or all new)")
            else:
                logger.info("fetch_permapeople: Pass 2 — update detection since %s", max_fetched.isoformat())
                last_id = None
                page_num = 0

                while True:
                    page_num += 1
                    try:
                        page_data = await fetch_plant_list(
                            last_id=last_id,
                            updated_since=max_fetched.isoformat(),
                        )
                    except PermapeopleAPIError as exc:
                        logger.error("fetch_permapeople: API error on update page %d: %s", page_num, exc)
                        stats["errors"] += 1
                        break

                    plants_list = page_data.get("plants", [])
                    if not plants_list:
                        logger.info("fetch_permapeople: Pass 2 — no more updates after page %d", page_num)
                        break

                    for p in plants_list:
                        pid = p.get("id")
                        if pid is None:
                            continue

                        existing = await _permapeople_exists(db, pid)
                        parsed = _parse_data_keys(p.get("data"))

                        if existing is None:
                            # New species found during update check
                            try:
                                await _insert_new_species(db, p, parsed, stats, changes)
                            except Exception as exc:
                                sci_name = p.get("scientific_name") or "unknown"
                                logger.warning("fetch_permapeople: error inserting permapeople_id=%d: %s", pid, exc)
                                stats["errors"] += 1
                                error_messages.append(f"Plant {pid} ({sci_name}): {exc}")
                                await db.rollback()
                        else:
                            new_version = p.get("version")
                            if new_version is not None and existing.version is not None and new_version > existing.version:
                                # Version bump — update all columns
                                old_version = existing.version
                                existing.common_name = p.get("name") or existing.common_name
                                existing.scientific_name = p.get("scientific_name") or existing.scientific_name
                                existing.description = p.get("description") or existing.description
                                existing.image_url = _extract_image_url(p) or existing.image_url
                                existing.slug = p.get("slug") or existing.slug
                                existing.version = new_version
                                for col, val in parsed.items():
                                    if val is not None:
                                        setattr(existing, col, val)
                                existing.fetched_at = datetime.now(timezone.utc)
                                stats["updated"] += 1
                                changes.append(f"Updated: {existing.scientific_name} v{old_version}→{new_version}")
                            else:
                                # Same version — check for gap-fill
                                filled_fields = []
                                for col, val in parsed.items():
                                    if val is not None and getattr(existing, col, None) is None:
                                        setattr(existing, col, val)
                                        filled_fields.append(col)
                                # Also check top-level fields
                                if existing.image_url is None:
                                    img = _extract_image_url(p)
                                    if img:
                                        existing.image_url = img
                                        filled_fields.append("image_url")
                                if existing.description is None and p.get("description"):
                                    existing.description = p["description"]
                                    filled_fields.append("description")

                                if filled_fields:
                                    existing.fetched_at = datetime.now(timezone.utc)
                                    stats["gap_filled"] += 1
                                    changes.append(f"Gap-filled: {existing.scientific_name} ({', '.join(filled_fields)})")
                                else:
                                    stats["unchanged"] += 1

                        last_id = pid

                    await db.commit()
                    logger.info(
                        "fetch_permapeople: Pass 2 page %d done (updated=%d, gap_filled=%d, unchanged=%d)",
                        page_num, stats["updated"], stats["gap_filled"], stats["unchanged"],
                    )
                    await asyncio.sleep(1.0)

            # ── Finish ────────────────────────────────────────────────
            if error_messages:
                run.error_detail = "\n".join(error_messages[:50])
            await complete_run(db, run, stats)
            await db.commit()

            total_count = await _count_permapeople(db)
            matched_count = await _count_matched(db)

            # Query plants table total
            plants_total = await db.scalar(select(func.count()).select_from(Plant))

            # Query field coverage
            coverage: dict[str, int] = {}
            for label, col in COVERAGE_FIELDS.items():
                col_attr = getattr(PermapeoplePlant, col)
                count = await db.scalar(
                    select(func.count()).select_from(PermapeoplePlant).where(col_attr.isnot(None))
                )
                coverage[label] = count or 0

            logger.info(
                "fetch_permapeople: complete — new=%d, updated=%d, gap_filled=%d, unchanged=%d, skipped=%d, errors=%d",
                stats["new_species"], stats["updated"], stats["gap_filled"],
                stats["unchanged"], stats["skipped"], stats["errors"],
            )

            await send_fetch_report(
                "permapeople",
                run,
                changes,
                total_count,
                matched_count,
                plants_total=plants_total,
                new_plants_created=stats["new_plants_created"],
                matched_existing=stats["matched_existing"],
                coverage=coverage,
            )

        except Exception as exc:
            logger.exception("fetch_permapeople: unexpected error: %s", exc)
            try:
                await db.rollback()
                await fail_run(db, run, traceback.format_exc())
                await db.commit()
            except Exception:
                logger.exception("fetch_permapeople: could not persist failed status for run %d", run.id)

            try:
                await send_email(
                    "LoamBase Permapeople Fetch — Error",
                    f"The Permapeople plant fetch encountered an unexpected error.\n\n"
                    f"Error: {exc}\n\n"
                    f"Started: {fmt(run.started_at) if run.started_at else 'N/A'}",
                )
            except Exception:
                logger.exception("fetch_permapeople: failed to send error email")
            raise
