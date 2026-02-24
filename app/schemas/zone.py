from typing import Optional

from pydantic import BaseModel


class ZoneCoordinates(BaseModel):
    lat: Optional[str] = None
    lon: Optional[str] = None


class ZoneRead(BaseModel):
    zone: str
    temperature_range: Optional[str] = None
    coordinates: Optional[ZoneCoordinates] = None
