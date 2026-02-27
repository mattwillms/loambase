from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.garden import Bed, Garden
from app.models.schedule import Planting, Schedule
from app.models.user import User
from app.schemas.user import UserCreate, UserStats, UserUpdate


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserCreate, role: str = "user") -> User:
    user = User(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user: User, data: UserUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


async def record_login(db: AsyncSession, user: User) -> None:
    user.last_login = datetime.now(timezone.utc)
    await db.commit()


async def get_user_stats(db: AsyncSession, user_id: int) -> UserStats:
    today = date.today()

    # gardens
    gardens_count = await db.scalar(
        select(func.count(Garden.id)).where(Garden.user_id == user_id)
    )

    # beds
    beds_count = await db.scalar(
        select(func.count(Bed.id))
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == user_id)
    )

    # active_plantings (exclude removed and dormant)
    plantings_count = await db.scalar(
        select(func.count(Planting.id))
        .join(Bed, Planting.bed_id == Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(
            Garden.user_id == user_id,
            Planting.status.not_in(["removed", "dormant"]),
        )
    )

    # tasks_due_today — scoped via any of the three scope columns
    owned_garden_ids = select(Garden.id).where(Garden.user_id == user_id).scalar_subquery()
    owned_bed_ids = (
        select(Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == user_id)
        .scalar_subquery()
    )
    owned_planting_ids = (
        select(Planting.id)
        .join(Bed, Planting.bed_id == Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == user_id)
        .scalar_subquery()
    )
    tasks_count = await db.scalar(
        select(func.count(Schedule.id)).where(
            Schedule.is_active.is_(True),
            Schedule.next_due == today,
            or_(
                and_(Schedule.garden_id.isnot(None), Schedule.garden_id.in_(owned_garden_ids)),
                and_(Schedule.bed_id.isnot(None), Schedule.bed_id.in_(owned_bed_ids)),
                and_(Schedule.planting_id.isnot(None), Schedule.planting_id.in_(owned_planting_ids)),
            ),
        )
    )

    return UserStats(
        gardens=gardens_count or 0,
        beds=beds_count or 0,
        active_plantings=plantings_count or 0,
        tasks_due_today=tasks_count or 0,
    )


async def list_users(db: AsyncSession, skip: int = 0, limit: int = 50) -> list[User]:
    result = await db.execute(select(User).offset(skip).limit(limit))
    return list(result.scalars().all())
