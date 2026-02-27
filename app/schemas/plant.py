from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PlantSummary(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    plant_type: Optional[str] = None
    sun_requirement: Optional[str] = None
    water_needs: Optional[str] = None
    hardiness_zones: Optional[list[str]] = None
    spacing_inches: Optional[float] = None
    image_url: Optional[str] = None
    source: str

    model_config = {"from_attributes": True}


class PlantRead(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    plant_type: Optional[str] = None
    hardiness_zones: Optional[list[str]] = None
    sun_requirement: Optional[str] = None
    water_needs: Optional[str] = None
    days_to_maturity: Optional[int] = None
    spacing_inches: Optional[float] = None
    planting_depth_inches: Optional[float] = None
    fertilizer_needs: Optional[str] = None
    bloom_season: Optional[str] = None
    harvest_window: Optional[str] = None
    companion_plants: Optional[list[str]] = None
    antagonist_plants: Optional[list[str]] = None
    common_pests: Optional[list[str]] = None
    common_diseases: Optional[list[str]] = None
    source: str
    external_id: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    is_user_defined: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlantListResponse(BaseModel):
    items: list[PlantSummary]
    total: int
    page: int
    per_page: int
