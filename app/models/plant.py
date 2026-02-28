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
    plant_type: Mapped[Optional[str]] = mapped_column(
        Enum("annual", "perennial", "shrub", "tree", "herb", "vegetable", "fruit", "bulb", "other",
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
