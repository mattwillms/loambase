from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class AdminPlantSummary(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    cultivar_name: Optional[str] = None
    plant_type: Optional[str] = None
    source: str
    data_sources: Optional[list[str]] = None
    has_perenual: bool
    has_permapeople: bool
    field_count: int
    image_url: Optional[str] = None

    model_config = {"from_attributes": True}


class AdminPlantListResponse(BaseModel):
    items: list[AdminPlantSummary]
    total: int
    page: int
    per_page: int


class PerenualSourceData(BaseModel):
    perenual_id: int
    common_name: Optional[str] = None
    scientific_name: Optional[str] = None
    image_url: Optional[str] = None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class PermapeopleSourceData(BaseModel):
    permapeople_id: int
    scientific_name: Optional[str] = None
    common_name: Optional[str] = None
    description: Optional[str] = None
    water_requirement: Optional[str] = None
    light_requirement: Optional[str] = None
    hardiness_zone: Optional[str] = None
    growth: Optional[str] = None
    soil_type: Optional[str] = None
    layer: Optional[str] = None
    edible: Optional[str] = None
    edible_parts: Optional[str] = None
    family: Optional[str] = None
    height: Optional[str] = None
    width: Optional[str] = None
    spacing: Optional[str] = None
    life_cycle: Optional[str] = None
    days_to_harvest: Optional[str] = None
    days_to_maturity: Optional[str] = None
    soil_ph: Optional[str] = None
    propagation_method: Optional[str] = None
    propagation_cuttings: Optional[str] = None
    propagation_direct_sowing: Optional[str] = None
    propagation_transplanting: Optional[str] = None
    germination_time: Optional[str] = None
    germination_temperature: Optional[str] = None
    sow_outdoors: Optional[str] = None
    sow_indoors: Optional[str] = None
    start_indoors_weeks: Optional[str] = None
    start_outdoors_weeks: Optional[str] = None
    plant_transplant: Optional[str] = None
    plant_cuttings: Optional[str] = None
    plant_division: Optional[str] = None
    seed_planting_depth: Optional[str] = None
    seed_viability: Optional[str] = None
    seed_weight_per_1000_g: Optional[str] = None
    nitrogen_fixing: Optional[str] = None
    nitrogen_usage: Optional[str] = None
    drought_resistant: Optional[str] = None
    native_to: Optional[str] = None
    introduced_into: Optional[str] = None
    habitat: Optional[str] = None
    root_type: Optional[str] = None
    root_depth: Optional[str] = None
    leaves: Optional[str] = None
    pests: Optional[str] = None
    diseases: Optional[str] = None
    pollination: Optional[str] = None
    medicinal: Optional[str] = None
    medicinal_parts: Optional[str] = None
    edible_uses: Optional[str] = None
    utility: Optional[str] = None
    warning: Optional[str] = None
    alternate_name: Optional[str] = None
    genus: Optional[str] = None
    wikipedia_url: Optional[str] = None
    pfaf_url: Optional[str] = None
    powo_url: Optional[str] = None
    image_url: Optional[str] = None
    slug: Optional[str] = None
    version: Optional[int] = None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class PlantSourcesResponse(BaseModel):
    plant_id: int
    common_name: str
    scientific_name: Optional[str] = None
    perenual: Optional[PerenualSourceData] = None
    permapeople: Optional[PermapeopleSourceData] = None


# ── Coverage ─────────────────────────────────────────────────────

class FieldCoverageItem(BaseModel):
    field_name: str
    populated: int
    total: int
    pct: float


class PlantCoverageResponse(BaseModel):
    total_plants: int
    fields: list[FieldCoverageItem]


# ── Enrichment Rules ─────────────────────────────────────────────

class EnrichmentRuleRead(BaseModel):
    id: int
    field_name: str
    strategy: str
    source_priority: Optional[list[str]] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnrichmentRulesResponse(BaseModel):
    items: list[EnrichmentRuleRead]


VALID_STRATEGIES = {"priority", "union", "longest", "average"}


class EnrichmentRuleUpdate(BaseModel):
    strategy: Optional[str] = None
    source_priority: Optional[list[str]] = None

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of: {', '.join(sorted(VALID_STRATEGIES))}")
        return v
