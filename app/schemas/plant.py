from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PlantSummary(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    cultivar_name: Optional[str] = None
    plant_type: Optional[str] = None
    sun_requirement: Optional[str] = None
    water_needs: Optional[str] = None
    hardiness_zones: Optional[list[str]] = None
    spacing_inches: Optional[float] = None
    image_url: Optional[str] = None
    source: str
    edible: Optional[bool] = None
    family: Optional[str] = None
    life_cycle: Optional[str] = None
    is_favorite: bool = False

    model_config = {"from_attributes": True}


class PlantRead(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    cultivar_name: Optional[str] = None
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
    data_sources: Optional[list[str]] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    is_user_defined: bool
    created_at: datetime
    updated_at: datetime

    # Physical / Growing
    height_inches: Optional[float] = None
    width_inches: Optional[float] = None
    soil_type: Optional[str] = None
    soil_ph_min: Optional[float] = None
    soil_ph_max: Optional[float] = None
    growth_rate: Optional[str] = None
    life_cycle: Optional[str] = None
    drought_resistant: Optional[bool] = None
    days_to_harvest: Optional[int] = None

    # Propagation / Germination
    propagation_method: Optional[str] = None
    germination_days_min: Optional[int] = None
    germination_days_max: Optional[int] = None
    germination_temp_min_f: Optional[float] = None
    germination_temp_max_f: Optional[float] = None
    sow_outdoors: Optional[str] = None
    sow_indoors: Optional[str] = None
    start_indoors_weeks: Optional[int] = None
    start_outdoors_weeks: Optional[int] = None
    plant_transplant: Optional[str] = None
    plant_cuttings: Optional[str] = None
    plant_division: Optional[str] = None

    # Geographic / Taxonomy
    native_to: Optional[str] = None
    habitat: Optional[str] = None
    family: Optional[str] = None
    genus: Optional[str] = None

    # Edible / Medicinal
    edible: Optional[bool] = None
    edible_parts: Optional[str] = None
    edible_uses: Optional[str] = None
    medicinal: Optional[str] = None
    medicinal_parts: Optional[str] = None
    utility: Optional[str] = None
    warning: Optional[str] = None

    # Other
    pollination: Optional[str] = None
    nitrogen_fixing: Optional[bool] = None
    root_type: Optional[str] = None
    root_depth: Optional[str] = None

    # Links
    wikipedia_url: Optional[str] = None
    pfaf_url: Optional[str] = None
    powo_url: Optional[str] = None

    is_favorite: bool = False

    model_config = {"from_attributes": True}


class PlantListResponse(BaseModel):
    items: list[PlantSummary]
    total: int
    page: int
    per_page: int
