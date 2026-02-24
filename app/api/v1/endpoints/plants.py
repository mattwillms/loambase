from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_db
from app.models.plant import Plant
from app.schemas.plant import PlantListResponse, PlantRead, PlantSummary

router = APIRouter(prefix="/plants", tags=["plants"])


@router.get("", response_model=PlantListResponse)
async def list_plants(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    name: str | None = Query(None, description="Partial match on common_name"),
    cycle: str | None = Query(None, description="Filter by plant_type (annual, perennial, shrub, tree, herb, vegetable, fruit, bulb, other)"),
    watering: str | None = Query(None, description="Filter by water_needs (low, medium, high)"),
    sunlight: str | None = Query(None, description="Filter by sun_requirement (full_sun, partial_shade, full_shade)"),
    hardiness_zone: str | None = Query(None, description="Filter by hardiness zone (e.g. '8a')"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    query = select(Plant)

    if name:
        query = query.where(Plant.common_name.ilike(f"%{name}%"))
    if cycle:
        query = query.where(Plant.plant_type == cycle)
    if watering:
        query = query.where(Plant.water_needs == watering)
    if sunlight:
        query = query.where(Plant.sun_requirement == sunlight)
    if hardiness_zone:
        query = query.where(Plant.hardiness_zones.contains([hardiness_zone]))

    count_result = await db.scalar(select(func.count()).select_from(query.subquery()))
    total = count_result or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Plant.common_name).offset(offset).limit(per_page))
    plants = result.scalars().all()

    return PlantListResponse(items=plants, total=total, page=page, per_page=per_page)


@router.get("/{plant_id}", response_model=PlantRead)
async def get_plant(plant_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Plant).where(Plant.id == plant_id))
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant
