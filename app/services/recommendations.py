from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.garden import Bed, Garden
from app.models.schedule import Planting, Schedule
from app.models.user import User
from app.services.weather import get_forecast

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
