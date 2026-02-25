from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class TreatmentLogCreate(BaseModel):
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    schedule_id: Optional[int] = None
    date: date
    treatment_type: Literal["herbicide", "insecticide", "fungicide", "fertilizer", "amendment"]
    product_name: Optional[str] = None
    amount: Optional[str] = None
    notes: Optional[str] = None
    weather_at_time: Optional[dict] = None

    @model_validator(mode="after")
    def check_scope(self) -> "TreatmentLogCreate":
        if not any([self.planting_id, self.bed_id]):
            raise ValueError("At least one of planting_id or bed_id must be set")
        return self


class TreatmentLogUpdate(BaseModel):
    date: Optional[date] = None
    treatment_type: Optional[Literal["herbicide", "insecticide", "fungicide", "fertilizer", "amendment"]] = None
    product_name: Optional[str] = None
    amount: Optional[str] = None
    notes: Optional[str] = None
    weather_at_time: Optional[dict] = None


class TreatmentLogRead(BaseModel):
    id: int
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    schedule_id: Optional[int] = None
    date: date
    treatment_type: str
    product_name: Optional[str] = None
    amount: Optional[str] = None
    notes: Optional[str] = None
    weather_at_time: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WateringLogCreate(BaseModel):
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    garden_id: Optional[int] = None
    schedule_id: Optional[int] = None
    date: date
    amount_inches: Optional[float] = None
    duration_minutes: Optional[int] = None
    method: Optional[Literal["drip", "hand", "sprinkler", "soaker", "other"]] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def check_scope(self) -> "WateringLogCreate":
        if not any([self.planting_id, self.bed_id, self.garden_id]):
            raise ValueError("At least one of planting_id, bed_id, or garden_id must be set")
        return self


class WateringLogUpdate(BaseModel):
    date: Optional[date] = None
    amount_inches: Optional[float] = None
    duration_minutes: Optional[int] = None
    method: Optional[Literal["drip", "hand", "sprinkler", "soaker", "other"]] = None
    notes: Optional[str] = None


class WateringLogRead(BaseModel):
    id: int
    planting_id: Optional[int] = None
    bed_id: Optional[int] = None
    garden_id: Optional[int] = None
    schedule_id: Optional[int] = None
    date: date
    amount_inches: Optional[float] = None
    duration_minutes: Optional[int] = None
    method: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
