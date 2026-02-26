from typing import Optional
from pydantic import BaseModel


class SoilDataRead(BaseModel):
    soil_series_name: Optional[str]
    texture_class: Optional[str]
    drainage_class: Optional[str]
    ph_water: Optional[float]
    organic_matter_pct: Optional[float]
