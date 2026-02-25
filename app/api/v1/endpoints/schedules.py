from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, get_db
from app.models.garden import Bed, Garden
from app.models.schedule import Planting, Schedule, WateringGroup
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
    WateringGroupCreate,
    WateringGroupRead,
    WateringGroupUpdate,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])
watering_groups_router = APIRouter(prefix="/gardens", tags=["watering-groups"])
planting_assignment_router = APIRouter(prefix="/watering-groups", tags=["watering-groups"])


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_owned_garden(db: AsyncSession, garden_id: int, user_id: int) -> Garden:
    garden = await db.scalar(
        select(Garden).where(Garden.id == garden_id, Garden.user_id == user_id)
    )
    if not garden:
        raise HTTPException(status_code=404, detail="Garden not found")
    return garden


async def _verify_schedule_ownership(db: AsyncSession, schedule: Schedule, user_id: int) -> bool:
    if schedule.garden_id is not None:
        owned = await db.scalar(
            select(Garden.id).where(Garden.id == schedule.garden_id, Garden.user_id == user_id)
        )
        return owned is not None

    if schedule.bed_id is not None:
        owned = await db.scalar(
            select(Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Bed.id == schedule.bed_id, Garden.user_id == user_id)
        )
        return owned is not None

    if schedule.planting_id is not None:
        owned = await db.scalar(
            select(Planting.id)
            .join(Bed, Planting.bed_id == Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Planting.id == schedule.planting_id, Garden.user_id == user_id)
        )
        return owned is not None

    return False


async def _get_owned_schedule(db: AsyncSession, schedule_id: int, user_id: int) -> Schedule:
    schedule = await db.scalar(select(Schedule).where(Schedule.id == schedule_id))
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if not await _verify_schedule_ownership(db, schedule, user_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


async def _get_owned_watering_group(
    db: AsyncSession, garden_id: int, group_id: int, user_id: int
) -> WateringGroup:
    await _get_owned_garden(db, garden_id, user_id)
    group = await db.scalar(
        select(WateringGroup)
        .options(selectinload(WateringGroup.plantings))
        .where(WateringGroup.id == group_id, WateringGroup.garden_id == garden_id)
    )
    if not group:
        raise HTTPException(status_code=404, detail="Watering group not found")
    return group


async def _get_owned_watering_group_by_id(
    db: AsyncSession, group_id: int, user_id: int
) -> WateringGroup:
    group = await db.scalar(
        select(WateringGroup)
        .join(Garden, WateringGroup.garden_id == Garden.id)
        .options(selectinload(WateringGroup.plantings))
        .where(WateringGroup.id == group_id, Garden.user_id == user_id)
    )
    if not group:
        raise HTTPException(status_code=404, detail="Watering group not found")
    return group


async def _get_owned_planting(db: AsyncSession, planting_id: int, user_id: int) -> Planting:
    planting = await db.scalar(
        select(Planting)
        .join(Bed, Planting.bed_id == Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Planting.id == planting_id, Garden.user_id == user_id)
    )
    if not planting:
        raise HTTPException(status_code=404, detail="Planting not found")
    return planting


async def _fetch_watering_group(db: AsyncSession, group_id: int) -> WateringGroup:
    """Re-fetch a watering group with plantings loaded (use after commit)."""
    return await db.scalar(
        select(WateringGroup)
        .options(selectinload(WateringGroup.plantings))
        .where(WateringGroup.id == group_id)
    )


# ── Schedule endpoints ─────────────────────────────────────────────────────────


@router.get("", response_model=list[ScheduleRead])
async def list_schedules(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    type: Optional[str] = Query(None, description="Filter by schedule_type"),
    due_before: Optional[str] = Query(None, description="ISO date — return schedules due on or before this date"),
    planting_id: Optional[int] = Query(None),
    garden_id: Optional[int] = Query(None),
    include_inactive: bool = Query(False),
):
    owned_garden_ids = select(Garden.id).where(Garden.user_id == current_user.id).scalar_subquery()
    owned_bed_ids = (
        select(Bed.id).join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == current_user.id).scalar_subquery()
    )
    owned_planting_ids = (
        select(Planting.id)
        .join(Bed, Planting.bed_id == Bed.id)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Garden.user_id == current_user.id).scalar_subquery()
    )

    q = select(Schedule).where(
        or_(
            and_(Schedule.garden_id.isnot(None), Schedule.garden_id.in_(owned_garden_ids)),
            and_(Schedule.bed_id.isnot(None), Schedule.bed_id.in_(owned_bed_ids)),
            and_(Schedule.planting_id.isnot(None), Schedule.planting_id.in_(owned_planting_ids)),
        )
    )

    if not include_inactive:
        q = q.where(Schedule.is_active.is_(True))
    if type:
        q = q.where(Schedule.schedule_type == type)
    if due_before:
        from datetime import date as date_type
        q = q.where(Schedule.next_due <= date_type.fromisoformat(due_before))
    if planting_id:
        q = q.where(Schedule.planting_id == planting_id)
    if garden_id:
        q = q.where(Schedule.garden_id == garden_id)

    result = await db.execute(q.order_by(Schedule.next_due))
    return result.scalars().all()


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    data: ScheduleCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    # Validate ownership of the scoped entity
    if data.planting_id:
        await _get_owned_planting(db, data.planting_id, current_user.id)
    elif data.bed_id:
        owned = await db.scalar(
            select(Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Bed.id == data.bed_id, Garden.user_id == current_user.id)
        )
        if not owned:
            raise HTTPException(status_code=404, detail="Bed not found")
    elif data.garden_id:
        await _get_owned_garden(db, data.garden_id, current_user.id)
    elif data.watering_group_id:
        wg = await _get_owned_watering_group_by_id(db, data.watering_group_id, current_user.id)
        # Scope the schedule to the group's garden; link group → schedule
        schedule = Schedule(
            garden_id=wg.garden_id,
            schedule_type=data.schedule_type,
            frequency_days=data.frequency_days,
            next_due=data.next_due,
            notes=data.notes,
        )
        db.add(schedule)
        await db.flush()
        wg.schedule_id = schedule.id
        await db.commit()
        await db.refresh(schedule)
        return schedule

    schedule = Schedule(
        planting_id=data.planting_id,
        bed_id=data.bed_id,
        garden_id=data.garden_id,
        schedule_type=data.schedule_type,
        frequency_days=data.frequency_days,
        next_due=data.next_due,
        notes=data.notes,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    return await _get_owned_schedule(db, schedule_id, current_user.id)


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    schedule = await _get_owned_schedule(db, schedule_id, current_user.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    await db.commit()
    await db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    schedule = await _get_owned_schedule(db, schedule_id, current_user.id)
    await db.delete(schedule)
    await db.commit()


@router.post("/{schedule_id}/complete", response_model=ScheduleRead)
async def complete_schedule(
    schedule_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    schedule = await _get_owned_schedule(db, schedule_id, current_user.id)
    now = datetime.now(timezone.utc)
    schedule.last_completed = now
    schedule.auto_adjusted = False
    if schedule.frequency_days:
        schedule.next_due = now.date() + timedelta(days=schedule.frequency_days)
    await db.commit()
    await db.refresh(schedule)
    return schedule


# ── Watering group endpoints (/gardens/{id}/watering-groups) ──────────────────


@watering_groups_router.get("/{garden_id}/watering-groups", response_model=list[WateringGroupRead])
async def list_watering_groups(
    garden_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_garden(db, garden_id, current_user.id)
    result = await db.execute(
        select(WateringGroup)
        .options(selectinload(WateringGroup.plantings))
        .where(WateringGroup.garden_id == garden_id)
        .order_by(WateringGroup.name)
    )
    return result.scalars().all()


@watering_groups_router.post(
    "/{garden_id}/watering-groups", response_model=WateringGroupRead, status_code=status.HTTP_201_CREATED
)
async def create_watering_group(
    garden_id: int,
    data: WateringGroupCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_garden(db, garden_id, current_user.id)

    group = WateringGroup(garden_id=garden_id, name=data.name)
    db.add(group)
    await db.flush()  # obtain group.id before creating schedule

    if data.frequency_days is not None:
        schedule = Schedule(
            garden_id=garden_id,
            schedule_type="water",
            frequency_days=data.frequency_days,
            next_due=data.next_due,
            notes=data.notes,
        )
        db.add(schedule)
        await db.flush()  # obtain schedule.id
        group.schedule_id = schedule.id

    await db.commit()
    return await _fetch_watering_group(db, group.id)


@watering_groups_router.get(
    "/{garden_id}/watering-groups/{group_id}", response_model=WateringGroupRead
)
async def get_watering_group(
    garden_id: int, group_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    return await _get_owned_watering_group(db, garden_id, group_id, current_user.id)


@watering_groups_router.patch(
    "/{garden_id}/watering-groups/{group_id}", response_model=WateringGroupRead
)
async def update_watering_group(
    garden_id: int,
    group_id: int,
    data: WateringGroupUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    group = await _get_owned_watering_group(db, garden_id, group_id, current_user.id)

    if data.name is not None:
        group.name = data.name

    # Update or create the linked schedule if schedule fields are present
    update_data = data.model_dump(exclude_unset=True)
    schedule_fields = {k: v for k, v in update_data.items() if k in ("frequency_days", "next_due", "notes")}

    if schedule_fields:
        if group.schedule_id:
            schedule = await db.scalar(select(Schedule).where(Schedule.id == group.schedule_id))
            if schedule:
                for field, value in schedule_fields.items():
                    setattr(schedule, field, value)
        else:
            schedule = Schedule(
                garden_id=garden_id,
                schedule_type="water",
                **schedule_fields,
            )
            db.add(schedule)
            await db.flush()
            group.schedule_id = schedule.id

    await db.commit()
    return await _fetch_watering_group(db, group.id)


@watering_groups_router.delete(
    "/{garden_id}/watering-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_watering_group(
    garden_id: int, group_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    group = await _get_owned_watering_group(db, garden_id, group_id, current_user.id)
    await db.delete(group)
    await db.commit()


# ── Planting assignment endpoints (/watering-groups/{id}/plantings/{id}) ──────


@planting_assignment_router.post(
    "/{group_id}/plantings/{planting_id}", response_model=WateringGroupRead
)
async def assign_planting_to_group(
    group_id: int, planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    group = await _get_owned_watering_group_by_id(db, group_id, current_user.id)
    planting = await _get_owned_planting(db, planting_id, current_user.id)

    # Verify the planting's bed belongs to the same garden as the group
    bed = await db.scalar(select(Bed).where(Bed.id == planting.bed_id))
    if not bed or bed.garden_id != group.garden_id:
        raise HTTPException(
            status_code=400,
            detail="Planting must belong to the same garden as the watering group",
        )

    planting.watering_group_id = group_id
    await db.commit()
    return await _fetch_watering_group(db, group_id)


@planting_assignment_router.delete(
    "/{group_id}/plantings/{planting_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_planting_from_group(
    group_id: int, planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_watering_group_by_id(db, group_id, current_user.id)
    planting = await _get_owned_planting(db, planting_id, current_user.id)
    if planting.watering_group_id != group_id:
        raise HTTPException(status_code=400, detail="Planting is not in this group")
    planting.watering_group_id = None
    await db.commit()
