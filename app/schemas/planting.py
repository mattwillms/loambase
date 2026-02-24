from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from app.schemas.plant import PlantSummary


class PlantingStatus(str, Enum):
    planned = "planned"
    seedling = "seedling"
    growing = "growing"
    flowering = "flowering"
    fruiting = "fruiting"
    harvesting = "harvesting"
    dormant = "dormant"
    removed = "removed"


class BedRef(BaseModel):
    id: int
    name: str
    garden_id: int

    model_config = {"from_attributes": True}


class PlantingCreate(BaseModel):
    bed_id: int
    plant_id: int
    status: PlantingStatus = PlantingStatus.planned
    date_planted: Optional[date] = None
    date_transplanted: Optional[date] = None
    quantity: int = 1
    notes: Optional[str] = None
    photos: Optional[list[str]] = None


class PlantingUpdate(BaseModel):
    status: Optional[PlantingStatus] = None
    date_planted: Optional[date] = None
    date_transplanted: Optional[date] = None
    quantity: Optional[int] = None
    notes: Optional[str] = None
    photos: Optional[list[str]] = None


class PlantingRead(BaseModel):
    id: int
    bed_id: int
    plant_id: int
    status: str
    date_planted: Optional[date] = None
    date_transplanted: Optional[date] = None
    quantity: int
    notes: Optional[str] = None
    photos: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime
    plant: Optional[PlantSummary] = None
    bed: Optional[BedRef] = None

    model_config = {"from_attributes": True}
