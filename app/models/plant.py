from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ARRAY, Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    common_name: Mapped[str] = mapped_column(String(200), index=True)
    scientific_name: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    cultivar_name: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    plant_type: Mapped[Optional[str]] = mapped_column(
        Enum("annual", "perennial", "shrub", "tree", "herb", "vegetable", "fruit", "bulb", "other", "biennial",
             name="plant_type_enum")
    )

    # Zone / environment
    hardiness_zones: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    sun_requirement: Mapped[Optional[str]] = mapped_column(
        Enum("full_sun", "partial_shade", "full_shade", name="sun_req_enum")
    )
    water_needs: Mapped[Optional[str]] = mapped_column(
        Enum("low", "medium", "high", name="water_needs_enum")
    )

    # Spacing / planting
    days_to_maturity: Mapped[Optional[int]] = mapped_column(Integer)
    spacing_inches: Mapped[Optional[float]] = mapped_column(Float)
    planting_depth_inches: Mapped[Optional[float]] = mapped_column(Float)

    # Care
    fertilizer_needs: Mapped[Optional[str]] = mapped_column(Text)
    bloom_season: Mapped[Optional[str]] = mapped_column(String(100))
    harvest_window: Mapped[Optional[str]] = mapped_column(String(100))

    # Companion info (stored as arrays of plant IDs or names)
    companion_plants: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    antagonist_plants: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    common_pests: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    common_diseases: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))

    # Physical / Growing
    height_inches: Mapped[Optional[float]] = mapped_column(Float)
    width_inches: Mapped[Optional[float]] = mapped_column(Float)
    soil_type: Mapped[Optional[str]] = mapped_column(Text)
    soil_ph_min: Mapped[Optional[float]] = mapped_column(Float)
    soil_ph_max: Mapped[Optional[float]] = mapped_column(Float)
    growth_rate: Mapped[Optional[str]] = mapped_column(Text)
    life_cycle: Mapped[Optional[str]] = mapped_column(Text)
    drought_resistant: Mapped[Optional[bool]] = mapped_column(Boolean)
    days_to_harvest: Mapped[Optional[int]] = mapped_column(Integer)

    # Propagation / Germination
    propagation_method: Mapped[Optional[str]] = mapped_column(Text)
    germination_days_min: Mapped[Optional[int]] = mapped_column(Integer)
    germination_days_max: Mapped[Optional[int]] = mapped_column(Integer)
    germination_temp_min_f: Mapped[Optional[float]] = mapped_column(Float)
    germination_temp_max_f: Mapped[Optional[float]] = mapped_column(Float)
    sow_outdoors: Mapped[Optional[str]] = mapped_column(Text)
    sow_indoors: Mapped[Optional[str]] = mapped_column(Text)
    start_indoors_weeks: Mapped[Optional[int]] = mapped_column(Integer)
    start_outdoors_weeks: Mapped[Optional[int]] = mapped_column(Integer)
    plant_transplant: Mapped[Optional[str]] = mapped_column(Text)
    plant_cuttings: Mapped[Optional[str]] = mapped_column(Text)
    plant_division: Mapped[Optional[str]] = mapped_column(Text)

    # Geographic / Taxonomy
    native_to: Mapped[Optional[str]] = mapped_column(Text)
    habitat: Mapped[Optional[str]] = mapped_column(Text)
    family: Mapped[Optional[str]] = mapped_column(Text)
    genus: Mapped[Optional[str]] = mapped_column(Text)

    # Edible / Medicinal
    edible: Mapped[Optional[bool]] = mapped_column(Boolean)
    edible_parts: Mapped[Optional[str]] = mapped_column(Text)
    edible_uses: Mapped[Optional[str]] = mapped_column(Text)
    medicinal: Mapped[Optional[str]] = mapped_column(Text)
    medicinal_parts: Mapped[Optional[str]] = mapped_column(Text)
    utility: Mapped[Optional[str]] = mapped_column(Text)
    warning: Mapped[Optional[str]] = mapped_column(Text)

    # Other
    pollination: Mapped[Optional[str]] = mapped_column(Text)
    nitrogen_fixing: Mapped[Optional[bool]] = mapped_column(Boolean)
    root_type: Mapped[Optional[str]] = mapped_column(Text)
    root_depth: Mapped[Optional[str]] = mapped_column(Text)

    # Links
    wikipedia_url: Mapped[Optional[str]] = mapped_column(Text)
    pfaf_url: Mapped[Optional[str]] = mapped_column(Text)
    powo_url: Mapped[Optional[str]] = mapped_column(Text)

    # Source tracking
    source: Mapped[str] = mapped_column(
        Enum("perenual", "trefle", "usda", "user", "permapeople", name="plant_source_enum"), default="user"
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(100))  # ID in source system
    data_sources: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))  # APIs that contributed data
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)

    is_user_defined: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    plantings: Mapped[list["Planting"]] = relationship(back_populates="plant")
