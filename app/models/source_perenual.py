from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PerenualPlant(Base):
    __tablename__ = "perenual_plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    perenual_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    plant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plants.id", ondelete="SET NULL"))

    common_name: Mapped[Optional[str]] = mapped_column(String(200))
    scientific_name: Mapped[Optional[str]] = mapped_column(String(200))
    image_url: Mapped[Optional[str]] = mapped_column(Text)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    plant: Mapped[Optional["Plant"]] = relationship()
