from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class WeatherRead(BaseModel):
    latitude: float
    longitude: float
    date: date
    current_temp_f: Optional[float] = None
    high_temp_f: Optional[float] = None
    low_temp_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    precip_inches: Optional[float] = None
    wind_mph: Optional[float] = None
    conditions: Optional[str] = None
    uv_index: Optional[float] = None
    soil_temp_f: Optional[float] = None
    frost_warning: bool
    fetched_at: datetime
