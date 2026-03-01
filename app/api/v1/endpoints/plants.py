from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_db
from app.models.favorite import UserPlantFavorite
from app.models.plant import Plant
from app.schemas.plant import PlantListResponse, PlantRead, PlantSummary
from app.services.image_proxy import get_plant_image

router = APIRouter(prefix="/plants", tags=["plants"])


async def _get_favorite_ids(user_id: int, db: AsyncSession) -> set[int]:
    result = await db.execute(
        select(UserPlantFavorite.plant_id).where(UserPlantFavorite.user_id == user_id)
    )
    return set(result.scalars().all())


def _plant_to_summary(plant: Plant, favorite_ids: set[int]) -> PlantSummary:
    summary = PlantSummary.model_validate(plant)
    summary.is_favorite = plant.id in favorite_ids
    return summary


def _plant_to_read(plant: Plant, is_favorite: bool) -> PlantRead:
    read = PlantRead.model_validate(plant)
    read.is_favorite = is_favorite
    return read


@router.get("/favorites", response_model=PlantListResponse)
async def list_favorite_plants(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    fav_subq = (
        select(UserPlantFavorite.plant_id)
        .where(UserPlantFavorite.user_id == current_user.id)
        .subquery()
    )
    query = select(Plant).where(Plant.id.in_(select(fav_subq)))

    count_result = await db.scalar(select(func.count()).select_from(query.subquery()))
    total = count_result or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Plant.common_name).offset(offset).limit(per_page))
    plants = result.scalars().all()

    favorite_ids = await _get_favorite_ids(current_user.id, db)
    items = [_plant_to_summary(p, favorite_ids) for p in plants]

    return PlantListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("", response_model=PlantListResponse)
async def list_plants(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    name: str | None = Query(None, description="Partial match on common_name"),
    cycle: str | None = Query(None, description="Filter by plant_type (annual, perennial, shrub, tree, herb, vegetable, fruit, bulb, other)"),
    watering: str | None = Query(None, description="Filter by water_needs (low, medium, high)"),
    sunlight: str | None = Query(None, description="Filter by sun_requirement (full_sun, partial_shade, full_shade)"),
    hardiness_zone: str | None = Query(None, description="Filter by hardiness zone (e.g. '8a')"),
    favorites_only: bool = Query(False, description="Only show plants the user has favorited"),
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
    if favorites_only:
        fav_subq = (
            select(UserPlantFavorite.plant_id)
            .where(UserPlantFavorite.user_id == current_user.id)
            .subquery()
        )
        query = query.where(Plant.id.in_(select(fav_subq)))

    count_result = await db.scalar(select(func.count()).select_from(query.subquery()))
    total = count_result or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Plant.common_name).offset(offset).limit(per_page))
    plants = result.scalars().all()

    favorite_ids = await _get_favorite_ids(current_user.id, db)
    items = [_plant_to_summary(p, favorite_ids) for p in plants]

    return PlantListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{plant_id}/image", include_in_schema=True)
async def get_plant_image_endpoint(plant_id: int, db: AsyncSession = Depends(get_db)):
    """Proxy and cache a plant's image. No auth required — images are public data."""
    result = await db.execute(select(Plant).where(Plant.id == plant_id))
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    if not plant.image_url:
        raise HTTPException(status_code=404, detail="No image for this plant")
    content, content_type = await get_plant_image(plant_id, plant.image_url)
    return Response(content=content, media_type=content_type)


@router.get("/{plant_id}", response_model=PlantRead)
async def get_plant(plant_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Plant).where(Plant.id == plant_id))
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    fav_result = await db.scalar(
        select(UserPlantFavorite.id).where(
            UserPlantFavorite.user_id == current_user.id,
            UserPlantFavorite.plant_id == plant_id,
        )
    )
    return _plant_to_read(plant, is_favorite=fav_result is not None)


@router.post("/{plant_id}/favorite")
async def favorite_plant(plant_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Plant.id).where(Plant.id == plant_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Plant not found")

    existing = await db.scalar(
        select(UserPlantFavorite.id).where(
            UserPlantFavorite.user_id == current_user.id,
            UserPlantFavorite.plant_id == plant_id,
        )
    )
    if not existing:
        db.add(UserPlantFavorite(user_id=current_user.id, plant_id=plant_id))
        await db.commit()

    return {"status": "ok"}


@router.delete("/{plant_id}/favorite")
async def unfavorite_plant(plant_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserPlantFavorite).where(
            UserPlantFavorite.user_id == current_user.id,
            UserPlantFavorite.plant_id == plant_id,
        )
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()

    return {"status": "ok"}
