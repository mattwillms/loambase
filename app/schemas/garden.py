from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class GardenCreate(BaseModel):
    name: str
    description: Optional[str] = None
    square_footage: Optional[float] = None
    sun_exposure: Optional[str] = None
    soil_type: Optional[str] = None
    irrigation_type: Optional[str] = None


class GardenUpdate(GardenCreate):
    name: Optional[str] = None


class GardenRead(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str]
    square_footage: Optional[float]
    sun_exposure: Optional[str]
    soil_type: Optional[str]
    irrigation_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BedCreate(BaseModel):
    name: str
    width_ft: Optional[float] = None
    length_ft: Optional[float] = None
    sun_exposure_override: Optional[str] = None
    soil_amendments: Optional[str] = None
    notes: Optional[str] = None


class BedUpdate(BedCreate):
    name: Optional[str] = None


class BedRead(BaseModel):
    id: int
    garden_id: int
    name: str
    width_ft: Optional[float]
    length_ft: Optional[float]
    sun_exposure_override: Optional[str]
    soil_amendments: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
