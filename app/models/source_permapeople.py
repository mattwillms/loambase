from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PermapeoplePlant(Base):
    __tablename__ = "permapeople_plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    permapeople_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    plant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plants.id", ondelete="SET NULL"))

    scientific_name: Mapped[Optional[str]] = mapped_column(Text)
    common_name: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Core characteristics
    water_requirement: Mapped[Optional[str]] = mapped_column(String(100))
    light_requirement: Mapped[Optional[str]] = mapped_column(String(100))
    hardiness_zone: Mapped[Optional[str]] = mapped_column(String(20))
    growth: Mapped[Optional[str]] = mapped_column(String(100))
    soil_type: Mapped[Optional[str]] = mapped_column(String(100))
    layer: Mapped[Optional[str]] = mapped_column(String(100))

    edible: Mapped[Optional[str]] = mapped_column(String(100))
    edible_parts: Mapped[Optional[str]] = mapped_column(Text)
    family: Mapped[Optional[str]] = mapped_column(String(100))

    # Size and spacing
    height: Mapped[Optional[str]] = mapped_column(String(50))
    width: Mapped[Optional[str]] = mapped_column(String(50))
    spacing: Mapped[Optional[str]] = mapped_column(String(50))
    life_cycle: Mapped[Optional[str]] = mapped_column(String(50))
    days_to_harvest: Mapped[Optional[str]] = mapped_column(String(50))
    days_to_maturity: Mapped[Optional[str]] = mapped_column(String(50))
    soil_ph: Mapped[Optional[str]] = mapped_column(String(50))

    # Propagation
    propagation_method: Mapped[Optional[str]] = mapped_column(Text)
    propagation_cuttings: Mapped[Optional[str]] = mapped_column(Text)
    propagation_direct_sowing: Mapped[Optional[str]] = mapped_column(Text)
    propagation_transplanting: Mapped[Optional[str]] = mapped_column(Text)

    # Germination
    germination_time: Mapped[Optional[str]] = mapped_column(String(100))
    germination_temperature: Mapped[Optional[str]] = mapped_column(String(100))

    # Sowing
    sow_outdoors: Mapped[Optional[str]] = mapped_column(Text)
    sow_indoors: Mapped[Optional[str]] = mapped_column(Text)
    start_indoors_weeks: Mapped[Optional[str]] = mapped_column(String(50))
    start_outdoors_weeks: Mapped[Optional[str]] = mapped_column(String(50))

    # Planting
    plant_transplant: Mapped[Optional[str]] = mapped_column(Text)
    plant_cuttings: Mapped[Optional[str]] = mapped_column(Text)
    plant_division: Mapped[Optional[str]] = mapped_column(Text)

    # Seed
    seed_planting_depth: Mapped[Optional[str]] = mapped_column(String(50))
    seed_viability: Mapped[Optional[str]] = mapped_column(String(100))
    seed_weight_per_1000_g: Mapped[Optional[str]] = mapped_column(String(50))

    # Soil/nitrogen
    nitrogen_fixing: Mapped[Optional[str]] = mapped_column(String(100))
    nitrogen_usage: Mapped[Optional[str]] = mapped_column(String(100))
    drought_resistant: Mapped[Optional[str]] = mapped_column(String(50))

    # Geographic
    native_to: Mapped[Optional[str]] = mapped_column(Text)
    introduced_into: Mapped[Optional[str]] = mapped_column(Text)
    habitat: Mapped[Optional[str]] = mapped_column(Text)

    # Root
    root_type: Mapped[Optional[str]] = mapped_column(String(100))
    root_depth: Mapped[Optional[str]] = mapped_column(String(50))

    # Other
    leaves: Mapped[Optional[str]] = mapped_column(Text)
    pests: Mapped[Optional[str]] = mapped_column(Text)
    diseases: Mapped[Optional[str]] = mapped_column(Text)
    pollination: Mapped[Optional[str]] = mapped_column(String(100))

    # Medicinal / utility
    medicinal: Mapped[Optional[str]] = mapped_column(Text)
    medicinal_parts: Mapped[Optional[str]] = mapped_column(Text)
    edible_uses: Mapped[Optional[str]] = mapped_column(Text)
    utility: Mapped[Optional[str]] = mapped_column(Text)
    warning: Mapped[Optional[str]] = mapped_column(Text)

    # Naming / taxonomy
    alternate_name: Mapped[Optional[str]] = mapped_column(Text)
    genus: Mapped[Optional[str]] = mapped_column(String(100))

    # External links
    wikipedia_url: Mapped[Optional[str]] = mapped_column(Text)
    pfaf_url: Mapped[Optional[str]] = mapped_column(Text)
    powo_url: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text)

    # Versioning
    slug: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[Optional[int]] = mapped_column(Integer)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    plant: Mapped[Optional["Plant"]] = relationship()
