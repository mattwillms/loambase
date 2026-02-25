from datetime import date, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class ScheduleCreate(BaseModel):
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    garden_id: Optional[int] = None
    watering_group_id: Optional[int] = None
    schedule_type: Literal["water", "fertilize", "spray", "prune", "harvest"]
    frequency_days: Optional[int] = None
    next_due: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def check_scope(self) -> "ScheduleCreate":
        if not any([self.planting_id, self.bed_id, self.garden_id, self.watering_group_id]):
            raise ValueError(
                "At least one of planting_id, bed_id, garden_id, watering_group_id must be set"
            )
        return self


class ScheduleUpdate(BaseModel):
    frequency_days: Optional[int] = None
    next_due: Optional[date] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ScheduleRead(BaseModel):
    id: int
    planting_id: Optional[int]
    bed_id: Optional[int]
    garden_id: Optional[int]
    schedule_type: str
    frequency_days: Optional[int]
    next_due: Optional[date]
    last_completed: Optional[datetime]
    notes: Optional[str]
    auto_adjusted: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WateringGroupCreate(BaseModel):
    garden_id: int
    name: str
    frequency_days: Optional[int] = None
    next_due: Optional[date] = None
    notes: Optional[str] = None


class WateringGroupUpdate(BaseModel):
    name: Optional[str] = None
    frequency_days: Optional[int] = None
    next_due: Optional[date] = None
    notes: Optional[str] = None


class WateringGroupRead(BaseModel):
    id: int
    garden_id: int
    name: str
    schedule_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    planting_ids: list[int] = []

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def extract_planting_ids(cls, data):
        """Convert ORM object → dict, deriving planting_ids from the relationship."""
        if hasattr(data, "plantings"):
            return {
                "id": data.id,
                "garden_id": data.garden_id,
                "name": data.name,
                "schedule_id": data.schedule_id,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
                "planting_ids": [p.id for p in data.plantings],
            }
        return data
