from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.garden import Bed, Garden
from app.models.plant import Plant
from app.models.schedule import Planting, Schedule
from app.models.user import User
from app.schemas.recommendation import CompanionEntry, CompanionPlantDetail, CompanionRecommendation
from app.services.weather import get_forecast

WATER_FREQ: dict[str, int] = {"low": 14, "medium": 7, "high": 3}

SUPPRESSION_THRESHOLD_INCHES = 0.25


async def get_watering_recommendations(
    user: User, db: AsyncSession, redis: Any
) -> list[dict]:
    # ── Weather / precipitation forecast ──────────────────────────────────────
    weather_available = False
    precip_next_24h: float | None = None

    if user.latitude is not None and user.longitude is not None:
        try:
            forecast = await get_forecast(user.latitude, user.longitude, redis, db)
            weather_available = True
            # Sum today (index 0) and tomorrow (index 1)
            today_precip = forecast[0]["precip_inches"] if len(forecast) > 0 else 0.0
            tomorrow_precip = forecast[1]["precip_inches"] if len(forecast) > 1 else 0.0
            precip_next_24h = today_precip + tomorrow_precip
        except Exception:
            weather_available = False
            precip_next_24h = None

    suppressed = bool(
        weather_available
        and precip_next_24h is not None
        and precip_next_24h >= SUPPRESSION_THRESHOLD_INCHES
    )

    # ── Query active watering schedules owned by this user ────────────────────
    owned_garden_ids = (
        select(Garden.id).where(Garden.user_id == user.id).scalar_subquery()
    )
    owned_bed_ids = (
        select(Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == user.id)
        .scalar_subquery()
    )
    owned_planting_ids = (
        select(Planting.id)
        .join(Bed, Planting.bed_id == Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == user.id)
        .scalar_subquery()
    )

    q = (
        select(Schedule)
        .where(
            Schedule.schedule_type == "water",
            Schedule.is_active.is_(True),
            or_(
                and_(Schedule.garden_id.isnot(None), Schedule.garden_id.in_(owned_garden_ids)),
                and_(Schedule.bed_id.isnot(None), Schedule.bed_id.in_(owned_bed_ids)),
                and_(Schedule.planting_id.isnot(None), Schedule.planting_id.in_(owned_planting_ids)),
            ),
        )
        .options(
            joinedload(Schedule.planting).joinedload(Planting.bed).joinedload(Bed.garden)
        )
        .order_by(Schedule.next_due)
    )

    result = await db.execute(q)
    schedules = result.unique().scalars().all()

    # ── Build recommendation dicts ─────────────────────────────────────────────
    recommendations = []
    for schedule in schedules:
        skip_reason = (
            f'{precip_next_24h:.2f}" rain forecast in next 24h' if suppressed else None
        )
        recommendations.append({
            "schedule_id": schedule.id,
            "planting_id": schedule.planting_id,
            "bed_id": schedule.bed_id,
            "garden_id": schedule.garden_id,
            "next_due": schedule.next_due.isoformat() if schedule.next_due else None,
            "suppressed": suppressed,
            "skip_reason": skip_reason,
            "precip_forecast_inches": precip_next_24h,
            "weather_available": weather_available,
        })

    return recommendations


async def generate_planting_schedules(
    planting_id: int,
    db: AsyncSession,
) -> list[Schedule]:
    # Load the planting with its plant
    result = await db.execute(
        select(Planting)
        .where(Planting.id == planting_id)
        .options(selectinload(Planting.plant))
    )
    planting = result.scalar_one_or_none()
    if planting is None or planting.plant is None:
        return []

    # Skip if schedules already exist
    count_result = await db.execute(
        select(func.count(Schedule.id)).where(Schedule.planting_id == planting_id)
    )
    if (count_result.scalar() or 0) > 0:
        return []

    plant = planting.plant
    today = date.today()
    schedules: list[Schedule] = []

    # Watering
    if plant.water_needs in WATER_FREQ:
        schedules.append(Schedule(
            planting_id=planting_id,
            schedule_type="water",
            frequency_days=WATER_FREQ[plant.water_needs],
            next_due=today,
            is_active=True,
        ))

    # Fertilizing
    if plant.fertilizer_needs is not None:
        schedules.append(Schedule(
            planting_id=planting_id,
            schedule_type="fertilize",
            frequency_days=30,
            next_due=today,
            is_active=True,
        ))

    # Spraying
    has_pests = bool(plant.common_pests)
    has_diseases = bool(plant.common_diseases)
    if has_pests or has_diseases:
        schedules.append(Schedule(
            planting_id=planting_id,
            schedule_type="spray",
            frequency_days=14,
            next_due=today,
            is_active=True,
        ))

    if not schedules:
        return []

    db.add_all(schedules)
    await db.commit()
    for s in schedules:
        await db.refresh(s)
    return schedules


async def get_companion_recommendations(
    plant_id: int, db: AsyncSession
) -> Optional[CompanionRecommendation]:
    result = await db.execute(select(Plant).where(Plant.id == plant_id))
    plant = result.scalar_one_or_none()
    if plant is None:
        return None

    companion_names: list[str] = plant.companion_plants or []
    antagonist_names: list[str] = plant.antagonist_plants or []

    # Resolve names to Plant rows in a single query per list
    async def _resolve(names: list[str]) -> dict[str, Plant]:
        if not names:
            return {}
        lower_names = [n.lower() for n in names]
        rows = await db.execute(
            select(Plant).where(func.lower(Plant.common_name).in_(lower_names))
        )
        plants = rows.scalars().all()
        return {p.common_name.lower(): p for p in plants}

    companion_map = await _resolve(companion_names)
    antagonist_map = await _resolve(antagonist_names)

    def _build_entries(names: list[str], plant_map: dict[str, Plant]) -> list[CompanionEntry]:
        entries = []
        for name in names:
            matched = plant_map.get(name.lower())
            if matched:
                entries.append(CompanionEntry(
                    name=name,
                    resolved=True,
                    plant=CompanionPlantDetail(
                        id=matched.id,
                        common_name=matched.common_name,
                        plant_type=matched.plant_type,
                        sun_requirement=matched.sun_requirement,
                        water_needs=matched.water_needs,
                        image_url=matched.image_url,
                        description=matched.description,
                    ),
                ))
            else:
                entries.append(CompanionEntry(name=name, resolved=False, plant=None))
        return entries

    return CompanionRecommendation(
        plant_id=plant.id,
        plant_name=plant.common_name,
        companions=_build_entries(companion_names, companion_map),
        antagonists=_build_entries(antagonist_names, antagonist_map),
    )
