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
