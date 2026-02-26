from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, get_db
from app.models.garden import Bed, Garden
from app.models.schedule import Planting
from app.schemas.garden import BedCreate, BedRead, BedUpdate, GardenCreate, GardenRead, GardenUpdate

router = APIRouter(prefix="/gardens", tags=["gardens"])
beds_router = APIRouter(prefix="/beds", tags=["beds"])


# ── Gardens ──────────────────────────────────────────────────────────────────


@router.get("", response_model=list[GardenRead])
async def list_gardens(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Garden).where(Garden.user_id == current_user.id))
    return result.scalars().all()


@router.post("", response_model=GardenRead, status_code=status.HTTP_201_CREATED)
async def create_garden(data: GardenCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    garden = Garden(**data.model_dump(), user_id=current_user.id)
    db.add(garden)
    await db.commit()
    await db.refresh(garden)
    return garden


@router.get("/{garden_id}", response_model=GardenRead)
async def get_garden(garden_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    garden = await _get_owned_garden(db, garden_id, current_user.id)
    return garden


@router.patch("/{garden_id}", response_model=GardenRead)
async def update_garden(
    garden_id: int, data: GardenUpdate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    garden = await _get_owned_garden(db, garden_id, current_user.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(garden, field, value)
    await db.commit()
    await db.refresh(garden)
    return garden


@router.delete("/{garden_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_garden(garden_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    garden = await _get_owned_garden(db, garden_id, current_user.id)
    await db.delete(garden)
    await db.commit()


# ── Beds ─────────────────────────────────────────────────────────────────────


@router.get("/{garden_id}/beds", response_model=list[BedRead])
async def list_beds(garden_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_garden(db, garden_id, current_user.id)
    result = await db.execute(select(Bed).where(Bed.garden_id == garden_id))
    return result.scalars().all()


@router.get("/{garden_id}/plantings")
async def list_garden_plantings(
    garden_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_owned_garden(db, garden_id, current_user.id)
    result = await db.execute(
        select(Planting)
        .join(Bed, Planting.bed_id == Bed.id)
        .where(Bed.garden_id == garden_id)
        .options(
            selectinload(Planting.plant),
            selectinload(Planting.bed),
        )
    )
    plantings = result.scalars().all()
    return [
        {
            "id": p.id,
            "bed_id": p.bed_id,
            "bed_name": p.bed.name,
            "plant_id": p.plant_id,
            "common_name": p.plant.common_name if p.plant else None,
            "status": p.status,
            "date_planted": p.date_planted.isoformat() if p.date_planted else None,
        }
        for p in plantings
    ]


@router.post("/{garden_id}/beds", response_model=BedRead, status_code=status.HTTP_201_CREATED)
async def create_bed(
    garden_id: int, data: BedCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_garden(db, garden_id, current_user.id)
    bed = Bed(**data.model_dump(), garden_id=garden_id)
    db.add(bed)
    await db.commit()
    await db.refresh(bed)
    return bed


# ── Bed routes (prefix /beds) ─────────────────────────────────────────────────


@beds_router.get("/{bed_id}", response_model=BedRead)
async def get_bed(bed_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await _get_owned_bed(db, bed_id, current_user.id)


@beds_router.patch("/{bed_id}", response_model=BedRead)
async def update_bed(
    bed_id: int, data: BedUpdate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    bed = await _get_owned_bed(db, bed_id, current_user.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(bed, field, value)
    await db.commit()
    await db.refresh(bed)
    return bed


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_owned_garden(db: AsyncSession, garden_id: int, user_id: int) -> Garden:
    result = await db.execute(
        select(Garden).where(Garden.id == garden_id, Garden.user_id == user_id)
    )
    garden = result.scalar_one_or_none()
    if not garden:
        raise HTTPException(status_code=404, detail="Garden not found")
    return garden


async def _get_owned_bed(db: AsyncSession, bed_id: int, user_id: int) -> Bed:
    result = await db.execute(
        select(Bed).join(Garden, Bed.garden_id == Garden.id).where(Bed.id == bed_id, Garden.user_id == user_id)
    )
    bed = result.scalar_one_or_none()
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    return bed
