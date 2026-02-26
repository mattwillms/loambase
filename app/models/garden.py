from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Garden(Base):
    __tablename__ = "gardens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    square_footage: Mapped[Optional[float]] = mapped_column(Float)
    sun_exposure: Mapped[Optional[str]] = mapped_column(
        Enum("full", "partial", "shade", name="sun_exposure_type")
    )
    soil_type: Mapped[Optional[str]] = mapped_column(String(100))
    irrigation_type: Mapped[Optional[str]] = mapped_column(String(100))
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="gardens")
    beds: Mapped[list["Bed"]] = relationship(back_populates="garden", cascade="all, delete-orphan")
    watering_groups: Mapped[list["WateringGroup"]] = relationship(back_populates="garden", cascade="all, delete-orphan")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="garden")


class Bed(Base):
    __tablename__ = "beds"

    id: Mapped[int] = mapped_column(primary_key=True)
    garden_id: Mapped[int] = mapped_column(ForeignKey("gardens.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    width_ft: Mapped[Optional[float]] = mapped_column(Float)
    length_ft: Mapped[Optional[float]] = mapped_column(Float)
    sun_exposure_override: Mapped[Optional[str]] = mapped_column(
        Enum("full", "partial", "shade", name="sun_exposure_type"),
        name="bed_sun_exposure",
    )
    soil_amendments: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    garden: Mapped["Garden"] = relationship(back_populates="beds")
    plantings: Mapped[list["Planting"]] = relationship(back_populates="bed", cascade="all, delete-orphan")
