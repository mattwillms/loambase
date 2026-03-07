from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, get_db
from app.models.garden import Bed, Garden
from app.models.schedule import Planting
from app.schemas.planting import PlantingCreate, PlantingRead, PlantingUpdate
from app.services.recommendations import generate_planting_schedules

router = APIRouter(tags=["plantings"])


# ── Plantings ─────────────────────────────────────────────────────────────────


@router.post("/plantings", response_model=PlantingRead, status_code=status.HTTP_201_CREATED)
async def create_planting(
    data: PlantingCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    if data.bed_id:
        await _get_owned_bed(db, data.bed_id, current_user.id)
    elif data.garden_id:
        result = await db.execute(
            select(Garden).where(Garden.id == data.garden_id, Garden.user_id == current_user.id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Garden not found")
    else:
        raise HTTPException(status_code=400, detail="Either bed_id or garden_id is required")
    planting = Planting(**data.model_dump())
    if planting.date_planted is None:
        planting.date_planted = date.today()
    db.add(planting)
    await db.commit()
    # Auto-generate schedules from plant data (best-effort)
    try:
        await generate_planting_schedules(planting.id, db)
    except Exception:
        pass
    return await _load_planting(db, planting.id)


@router.get("/plantings/{planting_id}", response_model=PlantingRead)
async def get_planting(
    planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    return await _get_owned_planting(db, planting_id, current_user.id)


@router.patch("/plantings/{planting_id}", response_model=PlantingRead)
async def update_planting(
    planting_id: int,
    data: PlantingUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    planting = await _get_owned_planting(db, planting_id, current_user.id)
    updates = data.model_dump(exclude_unset=True)
    if "bed_id" in updates and updates["bed_id"] is not None:
        await _get_owned_bed(db, updates["bed_id"], current_user.id)
        planting.garden_id = None
    elif "bed_id" in updates and updates["bed_id"] is None:
        # Moving to open canvas — derive garden_id from current bed
        if planting.bed_id:
            current_bed = await db.get(Bed, planting.bed_id)
            if current_bed:
                planting.garden_id = current_bed.garden_id
    for field, value in updates.items():
        setattr(planting, field, value)
    await db.commit()
    return await _load_planting(db, planting.id)


@router.delete("/plantings/{planting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_planting(
    planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    planting = await _get_owned_planting(db, planting_id, current_user.id)
    await db.delete(planting)
    await db.commit()


# ── Generate schedules ────────────────────────────────────────────────────────


@router.post("/plantings/{planting_id}/generate-schedules")
async def generate_schedules(
    planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_planting(db, planting_id, current_user.id)
    schedules = await generate_planting_schedules(planting_id, db)
    return {"generated": len(schedules), "schedule_ids": [s.id for s in schedules]}


# ── Bed plantings list ────────────────────────────────────────────────────────


@router.get("/beds/{bed_id}/plantings", response_model=list[PlantingRead])
async def list_bed_plantings(
    bed_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_bed(db, bed_id, current_user.id)
    result = await db.execute(
        select(Planting)
        .where(Planting.bed_id == bed_id)
        .options(selectinload(Planting.plant), selectinload(Planting.bed))
        .order_by(Planting.created_at)
    )
    return result.scalars().all()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_owned_bed(db: AsyncSession, bed_id: int, user_id: int) -> Bed:
    result = await db.execute(
        select(Bed)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Bed.id == bed_id, Garden.user_id == user_id)
    )
    bed = result.scalar_one_or_none()
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    return bed


async def _get_owned_planting(
    db: AsyncSession, planting_id: int, user_id: int
) -> Planting:
    # Planting may belong to a bed (bed → garden → user) or directly to a garden
    result = await db.execute(
        select(Planting)
        .outerjoin(Bed, Planting.bed_id == Bed.id)
        .outerjoin(Garden, or_(Bed.garden_id == Garden.id, Planting.garden_id == Garden.id))
        .where(Planting.id == planting_id, Garden.user_id == user_id)
        .options(selectinload(Planting.plant), selectinload(Planting.bed))
    )
    planting = result.scalar_one_or_none()
    if not planting:
        raise HTTPException(status_code=404, detail="Planting not found")
    return planting


async def _load_planting(db: AsyncSession, planting_id: int) -> Planting:
    result = await db.execute(
        select(Planting)
        .where(Planting.id == planting_id)
        .options(selectinload(Planting.plant), selectinload(Planting.bed))
    )
    return result.scalar_one()
