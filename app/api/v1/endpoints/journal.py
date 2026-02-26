from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, get_db
from app.models.garden import Bed, Garden
from app.models.logs import JournalEntry
from app.models.schedule import Planting

router = APIRouter(prefix="/journal", tags=["journal"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class JournalEntryCreate(BaseModel):
    date: date
    text: str
    garden_id: Optional[int] = None
    planting_id: Optional[int] = None
    tags: Optional[list[str]] = None
    photos: Optional[list[str]] = None


class JournalEntryUpdate(BaseModel):
    date: Optional[date] = None
    text: Optional[str] = None
    garden_id: Optional[int] = None
    planting_id: Optional[int] = None
    tags: Optional[list[str]] = None
    photos: Optional[list[str]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _entry_to_dict(entry: JournalEntry) -> dict:
    plant_name = None
    if entry.planting is not None and entry.planting.plant is not None:
        plant_name = entry.planting.plant.common_name

    garden_name = entry.garden.name if entry.garden is not None else None

    return {
        "id": entry.id,
        "date": entry.date.isoformat(),
        "text": entry.text,
        "tags": entry.tags,
        "photos": entry.photos,
        "garden_id": entry.garden_id,
        "garden_name": garden_name,
        "planting_id": entry.planting_id,
        "plant_name": plant_name,
        "created_at": entry.created_at,
    }


async def _load_entry(db: AsyncSession, entry_id: int, user_id: int) -> JournalEntry:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.user_id == user_id)
        .options(
            selectinload(JournalEntry.planting).selectinload(Planting.plant),
            selectinload(JournalEntry.garden),
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return entry


async def _validate_ownership(
    db: AsyncSession,
    user_id: int,
    garden_id: Optional[int],
    planting_id: Optional[int],
) -> None:
    if garden_id is not None:
        result = await db.execute(
            select(Garden).where(Garden.id == garden_id, Garden.user_id == user_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Garden not found or access denied")

    if planting_id is not None:
        result = await db.execute(
            select(Planting)
            .join(Bed, Planting.bed_id == Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Planting.id == planting_id, Garden.user_id == user_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Planting not found or access denied")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_journal_entries(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    garden_id: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    base = select(JournalEntry).where(JournalEntry.user_id == current_user.id)
    count_base = select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == current_user.id)

    if garden_id is not None:
        base = base.where(JournalEntry.garden_id == garden_id)
        count_base = count_base.where(JournalEntry.garden_id == garden_id)
    if tag is not None:
        base = base.where(JournalEntry.tags.contains([tag]))
        count_base = count_base.where(JournalEntry.tags.contains([tag]))

    total = await db.scalar(count_base) or 0
    offset = (page - 1) * per_page

    result = await db.execute(
        base
        .order_by(JournalEntry.date.desc(), JournalEntry.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .options(
            selectinload(JournalEntry.planting).selectinload(Planting.plant),
            selectinload(JournalEntry.garden),
        )
    )
    entries = result.scalars().all()

    return {
        "items": [_entry_to_dict(e) for e in entries],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    data: JournalEntryCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _validate_ownership(db, current_user.id, data.garden_id, data.planting_id)

    entry = JournalEntry(
        user_id=current_user.id,
        date=data.date,
        text=data.text,
        garden_id=data.garden_id,
        planting_id=data.planting_id,
        tags=data.tags,
        photos=data.photos,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # Reload with relationships
    entry = await _load_entry(db, entry.id, current_user.id)
    return _entry_to_dict(entry)


@router.get("/{entry_id}")
async def get_journal_entry(
    entry_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await _load_entry(db, entry_id, current_user.id)
    return _entry_to_dict(entry)


@router.patch("/{entry_id}")
async def update_journal_entry(
    entry_id: int,
    data: JournalEntryUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await _load_entry(db, entry_id, current_user.id)

    update_data = data.model_dump(exclude_unset=True)

    # Validate ownership for any new garden_id / planting_id
    new_garden_id = update_data.get("garden_id", entry.garden_id)
    new_planting_id = update_data.get("planting_id", entry.planting_id)
    if "garden_id" in update_data or "planting_id" in update_data:
        await _validate_ownership(db, current_user.id, new_garden_id, new_planting_id)

    for field, value in update_data.items():
        setattr(entry, field, value)

    await db.commit()

    # Reload with refreshed relationships
    entry = await _load_entry(db, entry_id, current_user.id)
    return _entry_to_dict(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(
    entry_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(JournalEntry).where(
            JournalEntry.id == entry_id,
            JournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    await db.delete(entry)
    await db.commit()
