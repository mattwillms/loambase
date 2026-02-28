"""
ARQ task: enrich canonical plants table from source tables.

Reads perenual_plants + permapeople_plants + enrichment_rules and merges
data into the canonical plants table using configurable strategies
(priority, union, longest, average).

Includes value normalization for enums, unit conversions, and range parsing.

Triggered on-demand only (no cron). Can be triggered via:
  - Admin endpoint: POST /admin/enrich
"""
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.enrichment import EnrichmentRule
from app.models.plant import Plant
from app.models.source_perenual import PerenualPlant
from app.models.source_permapeople import PermapeoplePlant
from app.services.email import send_email
from app.tasks.fetch_utils import (
    complete_run,
    fail_run,
    fmt,
    is_source_running,
    start_run,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


# ── Source field mapping ──────────────────────────────────────────────────────
# canonical_field: { source_name: source_column_name }

SOURCE_FIELD_MAP: dict[str, dict[str, str]] = {
    # Existing fields
    "common_name":           {"perenual": "common_name", "permapeople": "common_name"},
    "scientific_name":       {"perenual": "scientific_name", "permapeople": "scientific_name"},
    "image_url":             {"perenual": "image_url", "permapeople": "image_url"},
    "description":           {"permapeople": "description"},
    "plant_type":            {"permapeople": "life_cycle"},
    "water_needs":           {"permapeople": "water_requirement"},
    "sun_requirement":       {"permapeople": "light_requirement"},
    "hardiness_zones":       {"permapeople": "hardiness_zone"},
    "days_to_maturity":      {"permapeople": "days_to_maturity"},
    "spacing_inches":        {"permapeople": "spacing"},
    "planting_depth_inches": {"permapeople": "seed_planting_depth"},
    "common_pests":          {"permapeople": "pests"},
    "common_diseases":       {"permapeople": "diseases"},
    # New fields
    "height_inches":         {"permapeople": "height"},
    "width_inches":          {"permapeople": "width"},
    "soil_type":             {"permapeople": "soil_type"},
    "soil_ph_min":           {"permapeople": "soil_ph"},
    "soil_ph_max":           {"permapeople": "soil_ph"},
    "growth_rate":           {"permapeople": "growth"},
    "life_cycle":            {"permapeople": "life_cycle"},
    "drought_resistant":     {"permapeople": "drought_resistant"},
    "days_to_harvest":       {"permapeople": "days_to_harvest"},
    "propagation_method":    {"permapeople": "propagation_method"},
    "germination_days_min":  {"permapeople": "germination_time"},
    "germination_days_max":  {"permapeople": "germination_time"},
    "germination_temp_min_f": {"permapeople": "germination_temperature"},
    "germination_temp_max_f": {"permapeople": "germination_temperature"},
    "sow_outdoors":          {"permapeople": "sow_outdoors"},
    "sow_indoors":           {"permapeople": "sow_indoors"},
    "start_indoors_weeks":   {"permapeople": "start_indoors_weeks"},
    "start_outdoors_weeks":  {"permapeople": "start_outdoors_weeks"},
    "plant_transplant":      {"permapeople": "plant_transplant"},
    "plant_cuttings":        {"permapeople": "plant_cuttings"},
    "plant_division":        {"permapeople": "plant_division"},
    "native_to":             {"permapeople": "native_to"},
    "habitat":               {"permapeople": "habitat"},
    "family":                {"permapeople": "family"},
    "genus":                 {"permapeople": "genus"},
    "edible":                {"permapeople": "edible"},
    "edible_parts":          {"permapeople": "edible_parts"},
    "edible_uses":           {"permapeople": "edible_uses"},
    "medicinal":             {"permapeople": "medicinal"},
    "medicinal_parts":       {"permapeople": "medicinal_parts"},
    "utility":               {"permapeople": "utility"},
    "warning":               {"permapeople": "warning"},
    "pollination":           {"permapeople": "pollination"},
    "nitrogen_fixing":       {"permapeople": "nitrogen_fixing"},
    "root_type":             {"permapeople": "root_type"},
    "root_depth":            {"permapeople": "root_depth"},
    "wikipedia_url":         {"permapeople": "wikipedia_url"},
    "pfaf_url":              {"permapeople": "pfaf_url"},
    "powo_url":              {"permapeople": "powo_url"},
}

# Fields that are enrichable (used for coverage queries)
ENRICHABLE_FIELDS = list(SOURCE_FIELD_MAP.keys())


# ── Normalization functions ───────────────────────────────────────────────────

WATER_MAP = {
    "dry": "low",
    "low": "low",
    "low/average": "low",
    "moist": "medium",
    "average to moist": "medium",
    "moist, well-drained, dry": "medium",
    "moist, dry": "medium",
    "dry, moist": "medium",
    "dry-wet": "medium",
    "dry, moist, wet": "medium",
    "dry, moist, wet, water": "medium",
    "wet, dry": "medium",
    "wet": "high",
    "water": "high",
    "moist, wet": "high",
    "wet, water": "high",
    "wet, moist": "high",
    "moist, wet, water": "high",
    "wet to moist": "high",
    "moist; wet": "high",
}

SUN_MAP = {
    "full sun": "full_sun",
    "full sun, partial sun/shade": "partial_shade",
    "partial sun/shade, full sun": "partial_shade",
    "full sun, partial sun/shade, full shade": "partial_shade",
    "partial sun/shade, full sun, full shade": "partial_shade",
    "full shade, full sun, partial sun/shade": "partial_shade",
    "full sun,partial sun/shade, partial sun/shade": "partial_shade",
    "partial sun/shade": "partial_shade",
    "partial sun/shade, full shade": "full_shade",
    "full shade, partial sun/shade": "full_shade",
    "full shade": "full_shade",
}

PLANT_TYPE_MAP = {
    "annual": "annual",
    "perennial": "perennial",
    "biennial": "biennial",
    "annual, biennial": "annual",
    "annual, perennial": "annual",
    "biennial, perennial": "perennial",
}


def normalize_water(raw: str) -> Optional[str]:
    return WATER_MAP.get(raw.lower().strip())


def normalize_sun(raw: str) -> Optional[str]:
    return SUN_MAP.get(raw.lower().strip())


def normalize_plant_type(raw: str) -> Optional[str]:
    return PLANT_TYPE_MAP.get(raw.lower().strip())


SUBZONES = ["a", "b"]


def _parse_zone_endpoint(s: str) -> tuple[int, Optional[str]]:
    """Parse '9b' -> (9, 'b'), '7' -> (7, None)."""
    s = s.strip().lower()
    if s and s[-1] in ("a", "b"):
        return int(s[:-1]), s[-1]
    return int(s), None


def _expand_zone_range(
    start_num: int, start_sub: Optional[str],
    end_num: int, end_sub: Optional[str],
) -> list[str]:
    has_subzones = start_sub is not None or end_sub is not None
    if not has_subzones:
        return [str(z) for z in range(start_num, end_num + 1)]
    # Normalize: bare start = 'a', bare end = 'b'
    start_sub = start_sub or "a"
    end_sub = end_sub or "b"
    result: list[str] = []
    for z in range(start_num, end_num + 1):
        for sub in SUBZONES:
            if z == start_num and sub < start_sub:
                continue
            if z == end_num and sub > end_sub:
                continue
            result.append(f"{z}{sub}")
    return result


def normalize_hardiness_zones(raw: str) -> Optional[list[str]]:
    """Parse '2-11', '7a-9b', '9b to 11' into list of zone strings with subzone support."""
    # Clean input: strip extra quotes, trim
    raw = raw.strip().strip('"').strip("'").strip()
    if not raw:
        return None
    # Normalize separators
    raw = raw.replace(" to ", "-").replace(" - ", "-")

    # Try range: "7-9", "7a-9b", "9b-11"
    m = re.match(r"^(\d+[ab]?)\s*-\s*(\d+[ab]?)$", raw, re.IGNORECASE)
    if m:
        try:
            s_num, s_sub = _parse_zone_endpoint(m.group(1))
            e_num, e_sub = _parse_zone_endpoint(m.group(2))
            if 0 <= s_num <= e_num <= 13:
                return _expand_zone_range(s_num, s_sub, e_num, e_sub)
        except (ValueError, TypeError):
            return None

    # Single zone: "7", "9b"
    m = re.match(r"^(\d+[ab]?)$", raw, re.IGNORECASE)
    if m:
        return [m.group(1).lower()]

    return None


def normalize_days(raw: str) -> Optional[int]:
    """Parse day ranges/values into integer average. '60-70' -> 65, '40 (leaves)' -> 40."""
    raw = raw.strip()
    # Try simple range: "60-70"
    m = re.match(r"^(\d+)\s*-\s*(\d+)", raw)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    # Single number
    m = re.match(r"^(\d+)", raw)
    if m:
        return int(m.group(1))
    return None


_MEASUREMENT_RE = re.compile(
    r"^([\d.]+)\s*(?:-\s*([\d.]+))?\s*(cm|m|inches|inch|in|\"|\'|feet|ft)?",
    re.IGNORECASE,
)


def parse_measurement_to_inches(raw: str, default_unit: str = "m") -> Optional[float]:
    """Parse a measurement string to inches.

    Handles: '1.5m', '0.7-1.5m', '3ft', '30cm', '12-18 inches', '30x30cm',
    pure numeric (uses default_unit: 'm' for height/width, 'cm' for spacing/depth).
    """
    raw = raw.strip().replace("\u2019", "'").replace("\u2018", "'")
    # Handle "30x30cm" — take first dimension
    if "x" in raw.lower():
        raw = raw.lower().split("x")[0].strip()

    m = _MEASUREMENT_RE.match(raw)
    if not m:
        return None

    try:
        val1 = float(m.group(1))
    except ValueError:
        return None
    val2 = float(m.group(2)) if m.group(2) else val1
    avg = (val1 + val2) / 2
    unit = (m.group(3) or "").lower().rstrip(".")

    if unit in ("cm",):
        return round(avg / 2.54, 1)
    elif unit in ("m",):
        return round(avg * 39.3701, 1)
    elif unit in ("inches", "inch", "in", '"'):
        return round(avg, 1)
    elif unit in ("'", "feet", "ft"):
        return round(avg * 12, 1)
    else:
        # No explicit unit — apply default
        if default_unit == "cm":
            if avg > 10:
                return round(avg / 2.54, 1)
            # Small bare number with cm default — probably cm
            return round(avg / 2.54, 1)
        else:
            # default_unit == "m"
            return round(avg * 39.3701, 1)


def normalize_height_to_inches(raw: str) -> Optional[float]:
    """Convert height to inches. '1.5m' -> 59.1, '3ft' -> 36."""
    return parse_measurement_to_inches(raw, default_unit="m")


def normalize_spacing_to_inches(raw: str) -> Optional[float]:
    """Parse mixed-unit spacing to inches. '30cm' -> 11.8, '12-18 inches' -> 15."""
    return parse_measurement_to_inches(raw, default_unit="cm")


def normalize_depth_to_inches(raw: str) -> Optional[float]:
    """Parse depth values to inches. '2.5 cm' -> 1.0."""
    return parse_measurement_to_inches(raw, default_unit="cm")


def normalize_soil_ph(raw: str) -> Optional[tuple[float, float]]:
    """Parse '6.0-6.8' into (min, max) tuple. Handles en-dash, em-dash, > and <."""
    raw = raw.strip()
    # Normalize dashes: en-dash (U+2013), em-dash (U+2014) → hyphen
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
    # Handle inequality: ">6.5" or "< 6"
    m = re.match(r"^[>≥]\s*([\d.]+)", raw)
    if m:
        val = float(m.group(1))
        return (val, val)
    m = re.match(r"^[<≤]\s*([\d.]+)", raw)
    if m:
        val = float(m.group(1))
        return (val, val)
    # Range: "6.0-6.8"
    m = re.match(r"^([\d.]+)\s*-\s*([\d.]+)", raw)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except ValueError:
            return None
    # Single value
    try:
        val = float(raw)
        return (val, val)
    except (ValueError, TypeError):
        return None


def normalize_germination_time(raw: str) -> Optional[tuple[int, int]]:
    """Parse '7-21 days' or '2-8 weeks' into (min_days, max_days)."""
    raw = raw.strip().lower()

    # Try "N-M unit"
    m = re.match(r"^([\d.]+)\s*-\s*([\d.]+)\s*(days?|weeks?|months?)?", raw)
    if m:
        v1, v2 = float(m.group(1)), float(m.group(2))
        unit = (m.group(3) or "days").rstrip("s")
        mult = {"day": 1, "week": 7, "month": 30}.get(unit, 1)
        return (int(v1 * mult), int(v2 * mult))

    # Try "N unit"
    m = re.match(r"^([\d.]+)\s*(days?|weeks?|months?)?", raw)
    if m:
        v = float(m.group(1))
        unit = (m.group(2) or "days").rstrip("s")
        mult = {"day": 1, "week": 7, "month": 30}.get(unit, 1)
        days = int(v * mult)
        return (days, days)

    return None


_TEMP_F_RE = re.compile(r"([\d.]+)\s*-?\s*([\d.]+)?\s*°?\s*[fF]")
_TEMP_C_RE = re.compile(r"([\d.]+)\s*-?\s*([\d.]+)?\s*°?\s*[cC]")


def normalize_germination_temp(raw: str) -> Optional[tuple[float, float]]:
    """Parse germination temperature to (min_f, max_f) in Fahrenheit."""
    raw = raw.strip()

    # Prefer °F if present (often in parentheses)
    f_match = _TEMP_F_RE.search(raw)
    if f_match:
        lo = float(f_match.group(1))
        hi = float(f_match.group(2)) if f_match.group(2) else lo
        return (round(lo, 1), round(hi, 1))

    # Fall back to °C and convert
    c_match = _TEMP_C_RE.search(raw)
    if c_match:
        lo_c = float(c_match.group(1))
        hi_c = float(c_match.group(2)) if c_match.group(2) else lo_c
        return (round(lo_c * 9 / 5 + 32, 1), round(hi_c * 9 / 5 + 32, 1))

    # Try raw range of numbers (assume °C)
    m = re.match(r"^([\d.]+)\s*-\s*([\d.]+)", raw)
    if m:
        lo_c, hi_c = float(m.group(1)), float(m.group(2))
        return (round(lo_c * 9 / 5 + 32, 1), round(hi_c * 9 / 5 + 32, 1))

    return None


def normalize_bool(raw: str) -> Optional[bool]:
    low = raw.lower().strip()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    return None


def normalize_int(raw: str) -> Optional[int]:
    raw = raw.strip()
    m = re.match(r"^-?\d+", raw)
    if m:
        return int(m.group(0))
    return None


def normalize_list(raw: str) -> Optional[list[str]]:
    items = [s.strip() for s in raw.split(",") if s.strip()]
    return items if items else None


# ── Normalizer registry ──────────────────────────────────────────────────────

def _soil_ph_min(raw: str) -> Optional[float]:
    r = normalize_soil_ph(raw)
    return r[0] if r else None


def _soil_ph_max(raw: str) -> Optional[float]:
    r = normalize_soil_ph(raw)
    return r[1] if r else None


def _germ_days_min(raw: str) -> Optional[int]:
    r = normalize_germination_time(raw)
    return r[0] if r else None


def _germ_days_max(raw: str) -> Optional[int]:
    r = normalize_germination_time(raw)
    return r[1] if r else None


def _germ_temp_min(raw: str) -> Optional[float]:
    r = normalize_germination_temp(raw)
    return r[0] if r else None


def _germ_temp_max(raw: str) -> Optional[float]:
    r = normalize_germination_temp(raw)
    return r[1] if r else None


NORMALIZERS: dict[str, Any] = {
    "water_needs": normalize_water,
    "sun_requirement": normalize_sun,
    "plant_type": normalize_plant_type,
    "hardiness_zones": normalize_hardiness_zones,
    "days_to_maturity": normalize_days,
    "days_to_harvest": normalize_days,
    "height_inches": normalize_height_to_inches,
    "width_inches": normalize_height_to_inches,
    "spacing_inches": normalize_spacing_to_inches,
    "planting_depth_inches": normalize_depth_to_inches,
    "soil_ph_min": _soil_ph_min,
    "soil_ph_max": _soil_ph_max,
    "germination_days_min": _germ_days_min,
    "germination_days_max": _germ_days_max,
    "germination_temp_min_f": _germ_temp_min,
    "germination_temp_max_f": _germ_temp_max,
    "edible": normalize_bool,
    "drought_resistant": normalize_bool,
    "nitrogen_fixing": normalize_bool,
    "start_indoors_weeks": normalize_int,
    "start_outdoors_weeks": normalize_int,
    "common_pests": normalize_list,
    "common_diseases": normalize_list,
}


# ── Strategy implementations ─────────────────────────────────────────────────

def apply_priority(sources: dict[str, Any], source_priority: list[str]) -> Any:
    for src in source_priority:
        val = sources.get(src)
        if val is not None:
            return val
    return None


def apply_union(sources: dict[str, Any], source_priority: list[str]) -> Optional[list[str]]:
    result: list[str] = []
    seen: set[str] = set()
    for src in source_priority:
        val = sources.get(src)
        if val and isinstance(val, list):
            for item in val:
                low = item.lower().strip()
                if low not in seen:
                    seen.add(low)
                    result.append(item.strip())
    return result if result else None


def apply_longest(sources: dict[str, Any], source_priority: list[str]) -> Optional[str]:
    best = None
    for src in source_priority:
        val = sources.get(src)
        if val and isinstance(val, str):
            if best is None or len(val) > len(best):
                best = val
    return best


def apply_average(sources: dict[str, Any], source_priority: list[str]) -> Any:
    values = [sources[s] for s in source_priority if sources.get(s) is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    return int(round(avg)) if all(isinstance(v, int) for v in values) else round(avg, 2)


STRATEGY_FN = {
    "priority": apply_priority,
    "union": apply_union,
    "longest": apply_longest,
    "average": apply_average,
}


# ── Coverage query ───────────────────────────────────────────────────────────

async def _query_coverage(db: AsyncSession) -> dict[str, int]:
    """Count non-null values for each enrichable field on plants."""
    coverage: dict[str, int] = {}
    for field_name in ENRICHABLE_FIELDS:
        col = getattr(Plant, field_name, None)
        if col is None:
            continue
        count = await db.scalar(
            select(func.count()).select_from(Plant).where(col.isnot(None))
        )
        coverage[field_name] = count or 0
    return coverage


# ── Email report ─────────────────────────────────────────────────────────────

async def _send_enrichment_report(
    run: Any,
    stats: dict,
    plants_total: int,
    before_coverage: dict[str, int],
    after_coverage: dict[str, int],
    unmapped_values: dict[str, dict[str, int]],
) -> None:
    started = fmt(run.started_at) if run.started_at else "N/A"
    finished = fmt(run.finished_at) if run.finished_at else "N/A"

    elapsed = "N/A"
    if run.started_at and run.finished_at:
        delta = run.finished_at - run.started_at
        minutes = int(delta.total_seconds() // 60)
        seconds = int(delta.total_seconds() % 60)
        elapsed = f"{minutes}m {seconds}s"

    # Results section
    results = [
        ("Plants enriched:", stats["enriched"]),
        ("Fields updated:", stats["fields_filled"]),
        ("Unchanged:", stats["unchanged"]),
        ("Skipped (no source):", stats["skipped"]),
        ("Errors:", stats["errors"]),
    ]
    max_label = max(len(l) for l, _ in results)
    max_num = max(len(f"{v:,}") for _, v in results)
    results_section = "\n".join(
        f"  {label:<{max_label}} {val:>{max_num},}" for label, val in results
    )

    # Coverage before → after
    cov_lines = []
    for field in ENRICHABLE_FIELDS:
        b = before_coverage.get(field, 0)
        a = after_coverage.get(field, 0)
        if a == 0 and b == 0:
            continue
        pct_b = int(b * 100 / plants_total) if plants_total else 0
        pct_a = int(a * 100 / plants_total) if plants_total else 0
        cov_lines.append(
            f"  {field + ':':<30} {b:>6,} -> {a:>6,}  ({pct_b:>2}% -> {pct_a:>2}%)"
        )
    coverage_section = "\n".join(cov_lines)

    # Unmapped values
    unmapped_lines = []
    for field, vals in sorted(unmapped_values.items()):
        for raw_val, count in sorted(vals.items(), key=lambda x: -x[1])[:3]:
            s = "plant" if count == 1 else "plants"
            unmapped_lines.append(f'  {field}: "{raw_val}" ({count} {s})')
    unmapped_section = "\n".join(unmapped_lines[:20])

    body = (
        f"LoamBase Enrichment Report\n\n"
        f"Started:    {started}\n"
        f"Finished:   {finished}\n"
        f"Duration:   {elapsed}\n"
        f"Triggered:  {run.triggered_by or 'unknown'}\n\n"
        f"── Results ──────────────────────────────\n"
        f"{results_section}\n\n"
        f"── Coverage Before -> After ─────────────\n"
        f"{coverage_section}\n"
    )

    if unmapped_section:
        body += (
            f"\n── Unmapped Values (first 20) ──────────\n"
            f"{unmapped_section}\n"
        )

    subject = "LoamBase Enrichment — Complete" if stats["errors"] == 0 else "LoamBase Enrichment — Complete (with errors)"

    try:
        await send_email(subject, body)
    except Exception:
        logger.exception("enrich_plants: failed to send report email")


# ── Main task ────────────────────────────────────────────────────────────────

async def enrich_plants(ctx: dict, triggered_by: str = "manual") -> None:
    """Enrich canonical plants table from source tables using enrichment rules."""
    async with AsyncSessionLocal() as db:
        # Guard: prevent concurrent runs
        if await is_source_running(db, "enrichment"):
            logger.info("enrich_plants: already running, skipping")
            return

        run = start_run(db, "enrichment", triggered_by)
        await db.commit()
        await db.refresh(run)

        logger.info("enrich_plants: starting (run_id=%d, triggered_by=%s)", run.id, triggered_by)

        stats = {
            "enriched": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "fields_filled": 0,
        }
        error_messages: list[str] = []
        unmapped_values: dict[str, dict[str, int]] = {}

        try:
            # Load enrichment rules
            rules_result = await db.execute(select(EnrichmentRule))
            rules_list = rules_result.scalars().all()
            rules: dict[str, EnrichmentRule] = {r.field_name: r for r in rules_list}
            logger.info("enrich_plants: loaded %d enrichment rules", len(rules))

            # Before coverage
            plants_total = await db.scalar(select(func.count()).select_from(Plant)) or 0
            before_coverage = await _query_coverage(db)

            # Process plants in batches using LIMIT/OFFSET
            offset = 0
            processed = 0

            while True:
                # Query plants with at least one source match
                # LEFT JOIN both source tables, filter for at least one match
                query = (
                    select(Plant, PermapeoplePlant, PerenualPlant)
                    .outerjoin(PermapeoplePlant, PermapeoplePlant.plant_id == Plant.id)
                    .outerjoin(PerenualPlant, PerenualPlant.plant_id == Plant.id)
                    .order_by(Plant.id)
                    .limit(BATCH_SIZE)
                    .offset(offset)
                )
                result = await db.execute(query)
                rows = result.all()

                if not rows:
                    break

                for plant, permapeople_row, perenual_row in rows:
                    if permapeople_row is None and perenual_row is None:
                        stats["skipped"] += 1
                        continue

                    try:
                        changed = False
                        sources_used = set(plant.data_sources or [])

                        for field_name, rule in rules.items():
                            field_sources = SOURCE_FIELD_MAP.get(field_name)
                            if not field_sources:
                                continue

                            # Read raw values from source rows
                            raw_values: dict[str, Any] = {}
                            for source_name, source_col in field_sources.items():
                                if source_name == "permapeople" and permapeople_row:
                                    raw = getattr(permapeople_row, source_col, None)
                                    if raw is not None:
                                        raw_values[source_name] = raw
                                elif source_name == "perenual" and perenual_row:
                                    raw = getattr(perenual_row, source_col, None)
                                    if raw is not None:
                                        raw_values[source_name] = raw

                            if not raw_values:
                                continue

                            # Normalize values
                            normalizer = NORMALIZERS.get(field_name)
                            normalized: dict[str, Any] = {}
                            for src, raw in raw_values.items():
                                if normalizer:
                                    val = normalizer(raw) if isinstance(raw, str) else raw
                                    if val is None and raw:
                                        # Track unmapped value
                                        unmapped_values.setdefault(field_name, {})
                                        key = str(raw).lower().strip()
                                        unmapped_values[field_name][key] = unmapped_values[field_name].get(key, 0) + 1
                                    else:
                                        normalized[src] = val
                                else:
                                    normalized[src] = raw

                            if not normalized:
                                continue

                            # Apply strategy
                            strategy = rule.strategy
                            priority = rule.source_priority or ["permapeople", "perenual"]
                            strategy_fn = STRATEGY_FN.get(strategy, apply_priority)
                            resolved = strategy_fn(normalized, priority)

                            # Write if different from current value
                            current = getattr(plant, field_name)
                            if resolved is not None and resolved != current:
                                setattr(plant, field_name, resolved)
                                changed = True
                                stats["fields_filled"] += 1

                                for src in normalized:
                                    sources_used.add(src)

                        # Update data_sources
                        if sources_used != set(plant.data_sources or []):
                            plant.data_sources = sorted(sources_used)

                        if changed:
                            stats["enriched"] += 1
                        else:
                            stats["unchanged"] += 1

                    except Exception as exc:
                        stats["errors"] += 1
                        sci = plant.scientific_name or plant.common_name or str(plant.id)
                        error_messages.append(f"Plant {plant.id} ({sci}): {exc}")
                        logger.warning("enrich_plants: error on plant %d: %s", plant.id, exc)

                processed += len(rows)
                await db.commit()

                if processed % 2000 == 0:
                    logger.info(
                        "enrich_plants: progress — %d plants processed (enriched=%d, unchanged=%d, skipped=%d, errors=%d)",
                        processed, stats["enriched"], stats["unchanged"], stats["skipped"], stats["errors"],
                    )

                offset += BATCH_SIZE

            # Write error details
            if error_messages:
                run.error_detail = "\n".join(error_messages[:50])

            # Use new_species/updated/etc to store enrichment-specific stats
            run.new_species = stats["enriched"]
            run.updated = stats["fields_filled"]
            run.unchanged = stats["unchanged"]
            run.skipped = stats["skipped"]

            await complete_run(db, run, stats)
            await db.commit()

            # After coverage
            after_coverage = await _query_coverage(db)

            logger.info(
                "enrich_plants: complete — enriched=%d, fields_filled=%d, unchanged=%d, skipped=%d, errors=%d",
                stats["enriched"], stats["fields_filled"], stats["unchanged"], stats["skipped"], stats["errors"],
            )

            await _send_enrichment_report(
                run, stats, plants_total,
                before_coverage, after_coverage, unmapped_values,
            )

        except Exception as exc:
            logger.exception("enrich_plants: unexpected error: %s", exc)
            try:
                await db.rollback()
                await fail_run(db, run, traceback.format_exc())
                await db.commit()
            except Exception:
                logger.exception("enrich_plants: could not persist failed status for run %d", run.id)

            try:
                await send_email(
                    "LoamBase Enrichment — Error",
                    f"The enrichment engine encountered an unexpected error.\n\n"
                    f"Error: {exc}\n\n"
                    f"Started: {fmt(run.started_at) if run.started_at else 'N/A'}",
                )
            except Exception:
                logger.exception("enrich_plants: failed to send error email")
            raise
