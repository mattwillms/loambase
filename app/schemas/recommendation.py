from typing import Optional

from pydantic import BaseModel


class WateringRecommendation(BaseModel):
    schedule_id: int
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    garden_id: Optional[int] = None
    next_due: Optional[str] = None
    suppressed: bool
    skip_reason: Optional[str] = None
    precip_forecast_inches: Optional[float] = None
    weather_available: bool


class CompanionPlantDetail(BaseModel):
    id: int
    common_name: str
    plant_type: Optional[str] = None
    sun_requirement: Optional[str] = None
    water_needs: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None


class CompanionEntry(BaseModel):
    name: str
    resolved: bool
    plant: Optional[CompanionPlantDetail] = None


class CompanionRecommendation(BaseModel):
    plant_id: int
    plant_name: str
    companions: list[CompanionEntry]
    antagonists: list[CompanionEntry]


class SeasonalTaskItem(BaseModel):
    title: str
    description: str
    task_type: str
    urgency: str


class SeasonalTaskResponse(BaseModel):
    zone: Optional[str] = None
    month: int
    zone_missing: bool
    tasks: list[SeasonalTaskItem]
