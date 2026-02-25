from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_db
from app.models.garden import Bed, Garden
from app.models.schedule import Planting, TreatmentLog, WateringLog
from app.schemas.treatment import (
    TreatmentLogCreate,
    TreatmentLogRead,
    TreatmentLogUpdate,
    WateringLogCreate,
    WateringLogRead,
    WateringLogUpdate,
)

router = APIRouter(tags=["treatments"])
watering_router = APIRouter(tags=["watering"])


# ── Ownership helpers ──────────────────────────────────────────────────────────


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


async def _get_owned_bed(db: AsyncSession, bed_id: int, user_id: int) -> Bed:
    bed = await db.scalar(
        select(Bed)
        .join(Garden, Bed.garden_id == Garden.id)
        .where(Bed.id == bed_id, Garden.user_id == user_id)
    )
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    return bed


async def _get_owned_garden(db: AsyncSession, garden_id: int, user_id: int) -> Garden:
    garden = await db.scalar(
        select(Garden).where(Garden.id == garden_id, Garden.user_id == user_id)
    )
    if not garden:
        raise HTTPException(status_code=404, detail="Garden not found")
    return garden


async def _verify_treatment_ownership(db: AsyncSession, log: TreatmentLog, user_id: int) -> bool:
    if log.planting_id is not None:
        owned = await db.scalar(
            select(Planting.id)
            .join(Bed, Planting.bed_id == Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Planting.id == log.planting_id, Garden.user_id == user_id)
        )
        return owned is not None
    if log.bed_id is not None:
        owned = await db.scalar(
            select(Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Bed.id == log.bed_id, Garden.user_id == user_id)
        )
        return owned is not None
    return False


async def _get_owned_treatment(db: AsyncSession, log_id: int, user_id: int) -> TreatmentLog:
    log = await db.scalar(select(TreatmentLog).where(TreatmentLog.id == log_id))
    if not log:
        raise HTTPException(status_code=404, detail="Treatment log not found")
    if not await _verify_treatment_ownership(db, log, user_id):
        raise HTTPException(status_code=404, detail="Treatment log not found")
    return log


async def _verify_watering_ownership(db: AsyncSession, log: WateringLog, user_id: int) -> bool:
    if log.planting_id is not None:
        owned = await db.scalar(
            select(Planting.id)
            .join(Bed, Planting.bed_id == Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Planting.id == log.planting_id, Garden.user_id == user_id)
        )
        return owned is not None
    if log.bed_id is not None:
        owned = await db.scalar(
            select(Bed.id)
            .join(Garden, Bed.garden_id == Garden.id)
            .where(Bed.id == log.bed_id, Garden.user_id == user_id)
        )
        return owned is not None
    if log.garden_id is not None:
        owned = await db.scalar(
            select(Garden.id).where(Garden.id == log.garden_id, Garden.user_id == user_id)
        )
        return owned is not None
    return False


async def _get_owned_watering(db: AsyncSession, log_id: int, user_id: int) -> WateringLog:
    log = await db.scalar(select(WateringLog).where(WateringLog.id == log_id))
    if not log:
        raise HTTPException(status_code=404, detail="Watering log not found")
    if not await _verify_watering_ownership(db, log, user_id):
        raise HTTPException(status_code=404, detail="Watering log not found")
    return log


# ── TreatmentLog endpoints ─────────────────────────────────────────────────────


@router.post("/treatments", response_model=TreatmentLogRead, status_code=status.HTTP_201_CREATED)
async def create_treatment(
    data: TreatmentLogCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    if data.planting_id:
        await _get_owned_planting(db, data.planting_id, current_user.id)
    elif data.bed_id:
        await _get_owned_bed(db, data.bed_id, current_user.id)

    log = TreatmentLog(**data.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/treatments/{log_id}", response_model=TreatmentLogRead)
async def get_treatment(
    log_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    return await _get_owned_treatment(db, log_id, current_user.id)


@router.patch("/treatments/{log_id}", response_model=TreatmentLogRead)
async def update_treatment(
    log_id: int,
    data: TreatmentLogUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    log = await _get_owned_treatment(db, log_id, current_user.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    await db.commit()
    await db.refresh(log)
    return log


@router.delete("/treatments/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_treatment(
    log_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    log = await _get_owned_treatment(db, log_id, current_user.id)
    await db.delete(log)
    await db.commit()


@router.get("/plantings/{planting_id}/treatments", response_model=list[TreatmentLogRead])
async def list_planting_treatments(
    planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_planting(db, planting_id, current_user.id)
    result = await db.execute(
        select(TreatmentLog)
        .where(TreatmentLog.planting_id == planting_id)
        .order_by(TreatmentLog.date.desc())
    )
    return result.scalars().all()


@router.get("/beds/{bed_id}/treatments", response_model=list[TreatmentLogRead])
async def list_bed_treatments(
    bed_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_bed(db, bed_id, current_user.id)
    result = await db.execute(
        select(TreatmentLog)
        .where(TreatmentLog.bed_id == bed_id)
        .order_by(TreatmentLog.date.desc())
    )
    return result.scalars().all()


# ── WateringLog endpoints ──────────────────────────────────────────────────────


@watering_router.post("/watering-logs", response_model=WateringLogRead, status_code=status.HTTP_201_CREATED)
async def create_watering_log(
    data: WateringLogCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    if data.planting_id:
        await _get_owned_planting(db, data.planting_id, current_user.id)
    elif data.bed_id:
        await _get_owned_bed(db, data.bed_id, current_user.id)
    elif data.garden_id:
        await _get_owned_garden(db, data.garden_id, current_user.id)

    log = WateringLog(**data.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


@watering_router.get("/watering-logs/{log_id}", response_model=WateringLogRead)
async def get_watering_log(
    log_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    return await _get_owned_watering(db, log_id, current_user.id)


@watering_router.patch("/watering-logs/{log_id}", response_model=WateringLogRead)
async def update_watering_log(
    log_id: int,
    data: WateringLogUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    log = await _get_owned_watering(db, log_id, current_user.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    await db.commit()
    await db.refresh(log)
    return log


@watering_router.delete("/watering-logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watering_log(
    log_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    log = await _get_owned_watering(db, log_id, current_user.id)
    await db.delete(log)
    await db.commit()


@watering_router.get("/plantings/{planting_id}/watering-logs", response_model=list[WateringLogRead])
async def list_planting_watering_logs(
    planting_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_planting(db, planting_id, current_user.id)
    result = await db.execute(
        select(WateringLog)
        .where(WateringLog.planting_id == planting_id)
        .order_by(WateringLog.date.desc())
    )
    return result.scalars().all()


@watering_router.get("/beds/{bed_id}/watering-logs", response_model=list[WateringLogRead])
async def list_bed_watering_logs(
    bed_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_bed(db, bed_id, current_user.id)
    result = await db.execute(
        select(WateringLog)
        .where(WateringLog.bed_id == bed_id)
        .order_by(WateringLog.date.desc())
    )
    return result.scalars().all()


@watering_router.get("/gardens/{garden_id}/watering-logs", response_model=list[WateringLogRead])
async def list_garden_watering_logs(
    garden_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_garden(db, garden_id, current_user.id)
    result = await db.execute(
        select(WateringLog)
        .where(WateringLog.garden_id == garden_id)
        .order_by(WateringLog.date.desc())
    )
    return result.scalars().all()
