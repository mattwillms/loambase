"""
ARQ notification tasks.

send_daily_digest — runs daily at 07:00 UTC
    Emails each active user a list of their garden tasks due today or tomorrow.

send_frost_alerts — runs daily at 06:00 UTC
    Emails active located users when a frost warning is in effect for tonight.
    De-duplicated: skips if a frost notification was already sent today.

send_heat_alerts — runs daily at 06:00 UTC
    Emails active located users when high_temp_f >= 95°F today.
    De-duplicated: skips if a heat notification was already sent today.
"""
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.garden import Bed, Garden
from app.models.logs import NotificationLog, WeatherCache
from app.models.schedule import Planting, Schedule
from app.models.user import User
from app.services.notifications import dispatch_notification
from app.services.weather import get_weather

logger = logging.getLogger(__name__)


async def send_daily_digest(ctx: dict) -> None:
    """Email each active user their garden tasks due today or tomorrow."""
    logger.info("send_daily_digest: starting")

    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_str = today.strftime("%B %-d, %Y")
    tomorrow_str = tomorrow.strftime("%B %-d, %Y")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.email.isnot(None),
            )
        )
        users = result.scalars().all()

        for user in users:
            try:
                schedules = await _get_user_schedules_due(db, user.id, today, tomorrow)
                if not schedules:
                    logger.info("send_daily_digest: no tasks for user %d, skipping", user.id)
                    continue

                body = _build_digest_body(user, schedules, today_str, tomorrow_str, today, tomorrow)
                subject = f"Loam — Garden tasks for {today_str}"

                # Determine primary notification type
                type_counts: Counter = Counter(s.schedule_type for s in schedules)
                if type_counts.get("water", 0) > 0:
                    notif_type = "water"
                elif type_counts:
                    notif_type = type_counts.most_common(1)[0][0]
                else:
                    notif_type = "custom"

                await dispatch_notification(db, user, notif_type, subject, body)
                logger.info("send_daily_digest: sent digest to user %d (%d tasks)", user.id, len(schedules))

            except Exception as exc:
                logger.exception("send_daily_digest: failed for user %d: %s", user.id, exc)

    logger.info("send_daily_digest: complete")


async def send_frost_alerts(ctx: dict) -> None:
    """Email active located users when a frost warning is in effect tonight."""
    logger.info("send_frost_alerts: starting")

    today = date.today()
    today_midnight_utc = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.latitude.isnot(None),
                User.longitude.isnot(None),
            )
        )
        users = result.scalars().all()

        for user in users:
            try:
                # Find today's WeatherCache record near user's location
                weather_result = await db.execute(
                    select(WeatherCache).where(
                        WeatherCache.date == today,
                        func.abs(WeatherCache.latitude - user.latitude) < 0.01,
                        func.abs(WeatherCache.longitude - user.longitude) < 0.01,
                    ).limit(1)
                )
                weather = weather_result.scalar_one_or_none()

                if weather is None:
                    logger.info("send_frost_alerts: no weather record for user %d — fetching", user.id)
                    await get_weather(user.latitude, user.longitude, ctx["redis"], db)
                    weather_result2 = await db.execute(
                        select(WeatherCache).where(
                            WeatherCache.date == today,
                            func.abs(WeatherCache.latitude - user.latitude) < 0.01,
                            func.abs(WeatherCache.longitude - user.longitude) < 0.01,
                        ).limit(1)
                    )
                    weather = weather_result2.scalar_one_or_none()

                if weather is None:
                    logger.warning("send_frost_alerts: still no weather record for user %d after fetch, skipping", user.id)
                    continue

                if not weather.frost_warning:
                    continue

                # Deduplicate — skip if frost notification already sent today
                existing_result = await db.execute(
                    select(NotificationLog).where(
                        NotificationLog.user_id == user.id,
                        NotificationLog.notification_type == "frost",
                        NotificationLog.timestamp >= today_midnight_utc,
                    ).limit(1)
                )
                if existing_result.scalar_one_or_none() is not None:
                    logger.info("send_frost_alerts: frost alert already sent today for user %d, skipping", user.id)
                    continue

                low_temp = weather.low_temp_f if weather.low_temp_f is not None else "unknown"
                body = (
                    f"Hi {user.name},\n\n"
                    f"A frost warning is in effect for your location tonight.\n\n"
                    f"Forecast low: {low_temp}°F\n"
                    f"Location: ({user.latitude:.4f}, {user.longitude:.4f})\n\n"
                    f"Consider covering sensitive plants or bringing them indoors."
                )
                subject = "Loam — Frost warning for tonight"

                await dispatch_notification(db, user, "frost", subject, body)
                logger.info("send_frost_alerts: sent frost alert to user %d", user.id)

            except Exception as exc:
                logger.exception("send_frost_alerts: failed for user %d: %s", user.id, exc)

    logger.info("send_frost_alerts: complete")


async def send_heat_alerts(ctx: dict) -> None:
    """Email active located users when a heat advisory is in effect today."""
    logger.info("send_heat_alerts: starting")

    today = date.today()
    today_midnight_utc = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.latitude.isnot(None),
                User.longitude.isnot(None),
            )
        )
        users = result.scalars().all()

        for user in users:
            try:
                # Find today's WeatherCache record near user's location
                weather_result = await db.execute(
                    select(WeatherCache).where(
                        WeatherCache.date == today,
                        func.abs(WeatherCache.latitude - user.latitude) < 0.01,
                        func.abs(WeatherCache.longitude - user.longitude) < 0.01,
                    ).limit(1)
                )
                weather = weather_result.scalar_one_or_none()

                if weather is None:
                    logger.info("send_heat_alerts: no weather record for user %d — fetching", user.id)
                    await get_weather(user.latitude, user.longitude, ctx["redis"], db)
                    weather_result2 = await db.execute(
                        select(WeatherCache).where(
                            WeatherCache.date == today,
                            func.abs(WeatherCache.latitude - user.latitude) < 0.01,
                            func.abs(WeatherCache.longitude - user.longitude) < 0.01,
                        ).limit(1)
                    )
                    weather = weather_result2.scalar_one_or_none()

                if weather is None:
                    logger.warning("send_heat_alerts: still no weather record for user %d after fetch, skipping", user.id)
                    continue

                if weather.high_temp_f is None or weather.high_temp_f < 95.0:
                    continue

                # Deduplicate — skip if heat notification already sent today
                existing_result = await db.execute(
                    select(NotificationLog).where(
                        NotificationLog.user_id == user.id,
                        NotificationLog.notification_type == "heat",
                        NotificationLog.timestamp >= today_midnight_utc,
                    ).limit(1)
                )
                if existing_result.scalar_one_or_none() is not None:
                    logger.info("send_heat_alerts: heat alert already sent today for user %d, skipping", user.id)
                    continue

                body = (
                    f"Hi {user.name},\n\n"
                    f"A heat advisory is in effect for your area today.\n\n"
                    f"Forecast high: {weather.high_temp_f}°F\n"
                    f"Location: ({user.latitude:.4f}, {user.longitude:.4f})\n\n"
                    f"Consider watering early in the morning and providing shade for sensitive plants."
                )
                subject = "Loam — Heat advisory for today"

                await dispatch_notification(db, user, "heat", subject, body)
                logger.info("send_heat_alerts: sent heat alert to user %d", user.id)

            except Exception as exc:
                logger.exception("send_heat_alerts: failed for user %d: %s", user.id, exc)

    logger.info("send_heat_alerts: complete")


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_user_schedules_due(
    db,
    user_id: int,
    today: date,
    tomorrow: date,
) -> list[Schedule]:
    """Return active schedules due today or tomorrow belonging to the given user."""
    due_dates = (today, tomorrow)
    schedule_types = ("water", "fertilize", "spray", "prune", "harvest")

    # Planting-scoped schedules
    planting_result = await db.execute(
        select(Schedule)
        .join(Schedule.planting)
        .join(Planting.bed)
        .join(Bed.garden)
        .where(
            Garden.user_id == user_id,
            Schedule.is_active == True,
            Schedule.schedule_type.in_(schedule_types),
            Schedule.next_due.in_(due_dates),
        )
    )
    planting_schedules = planting_result.scalars().all()

    # Bed-scoped schedules
    bed_result = await db.execute(
        select(Schedule)
        .join(Bed, Schedule.bed_id == Bed.id)
        .join(Bed.garden)
        .where(
            Garden.user_id == user_id,
            Schedule.is_active == True,
            Schedule.schedule_type.in_(schedule_types),
            Schedule.next_due.in_(due_dates),
        )
    )
    bed_schedules = bed_result.scalars().all()

    # Garden-scoped schedules
    garden_result = await db.execute(
        select(Schedule)
        .join(Garden, Schedule.garden_id == Garden.id)
        .where(
            Garden.user_id == user_id,
            Schedule.is_active == True,
            Schedule.schedule_type.in_(schedule_types),
            Schedule.next_due.in_(due_dates),
        )
    )
    garden_schedules = garden_result.scalars().all()

    # Merge and deduplicate by id
    seen: set[int] = set()
    merged: list[Schedule] = []
    for s in (*planting_schedules, *bed_schedules, *garden_schedules):
        if s.id not in seen:
            seen.add(s.id)
            merged.append(s)

    return merged


def _scope_label(schedule: Schedule) -> str:
    if schedule.planting_id is not None:
        return f"Planting #{schedule.planting_id}"
    if schedule.bed_id is not None:
        return f"Bed #{schedule.bed_id}"
    if schedule.garden_id is not None:
        return f"Garden #{schedule.garden_id}"
    return "—"


def _build_digest_body(
    user,
    schedules: list[Schedule],
    today_str: str,
    tomorrow_str: str,
    today: date,
    tomorrow: date,
) -> str:
    today_tasks = [s for s in schedules if s.next_due == today]
    tomorrow_tasks = [s for s in schedules if s.next_due == tomorrow]

    lines = [f"Hi {user.name},", "", "Here are your upcoming garden tasks:", ""]

    if today_tasks:
        lines.append(f"Today ({today_str}):")
        for s in today_tasks:
            lines.append(f"  - {s.schedule_type} — {_scope_label(s)}")
            if s.notes:
                lines.append(f"    Notes: {s.notes}")
        lines.append("")

    if tomorrow_tasks:
        lines.append(f"Tomorrow ({tomorrow_str}):")
        for s in tomorrow_tasks:
            lines.append(f"  - {s.schedule_type} — {_scope_label(s)}")
            if s.notes:
                lines.append(f"    Notes: {s.notes}")
        lines.append("")

    lines.append("Log in to review and complete your tasks.")

    return "\n".join(lines)
