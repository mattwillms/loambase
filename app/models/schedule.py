from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    ARRAY, Boolean, Date, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Planting(Base):
    __tablename__ = "plantings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)

    date_planted: Mapped[Optional[date]] = mapped_column(Date)
    date_transplanted: Mapped[Optional[date]] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[str] = mapped_column(
        Enum(
            "planned", "seedling", "growing", "flowering", "fruiting",
            "harvesting", "dormant", "removed",
            name="planting_status_enum",
        ),
        default="planned",
    )

    grid_x: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    grid_y: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    notes: Mapped[Optional[str]] = mapped_column(Text)
    photos: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))

    watering_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "watering_groups.id", ondelete="SET NULL",
            name="plantings_watering_group_id_fkey", use_alter=True,
        ),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    bed: Mapped["Bed"] = relationship(back_populates="plantings")
    plant: Mapped["Plant"] = relationship(back_populates="plantings")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="planting", cascade="all, delete-orphan")
    treatment_logs: Mapped[list["TreatmentLog"]] = relationship(back_populates="planting", cascade="all, delete-orphan")
    watering_logs: Mapped[list["WateringLog"]] = relationship(back_populates="planting", cascade="all, delete-orphan")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="planting")
    watering_group: Mapped[Optional["WateringGroup"]] = relationship(back_populates="plantings")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Scope — at least one must be set
    planting_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plantings.id", ondelete="CASCADE"), index=True)
    bed_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), index=True)
    garden_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gardens.id", ondelete="CASCADE"), index=True)

    schedule_type: Mapped[str] = mapped_column(
        Enum("water", "fertilize", "spray", "prune", "harvest", name="schedule_type_enum")
    )

    frequency_days: Mapped[Optional[int]] = mapped_column(Integer)
    next_due: Mapped[Optional[date]] = mapped_column(Date, index=True)
    last_completed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    auto_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    planting: Mapped[Optional["Planting"]] = relationship(back_populates="schedules")
    watering_group: Mapped[Optional["WateringGroup"]] = relationship(back_populates="schedule")
    watering_logs: Mapped[list["WateringLog"]] = relationship(back_populates="schedule")
    treatment_logs: Mapped[list["TreatmentLog"]] = relationship(back_populates="schedule")


class WateringGroup(Base):
    __tablename__ = "watering_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    garden_id: Mapped[int] = mapped_column(ForeignKey("gardens.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    schedule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("schedules.id", name="watering_groups_schedule_id_fkey", use_alter=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    garden: Mapped["Garden"] = relationship(back_populates="watering_groups")
    plantings: Mapped[list["Planting"]] = relationship(back_populates="watering_group")
    schedule: Mapped[Optional["Schedule"]] = relationship(back_populates="watering_group")


class TreatmentLog(Base):
    __tablename__ = "treatment_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    planting_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plantings.id", ondelete="CASCADE"), index=True)
    bed_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"), index=True)

    date: Mapped[date] = mapped_column(Date)
    treatment_type: Mapped[str] = mapped_column(
        Enum("herbicide", "insecticide", "fungicide", "fertilizer", "amendment", name="treatment_type_enum")
    )
    product_name: Mapped[Optional[str]] = mapped_column(String(200))
    amount: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    weather_at_time: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    planting: Mapped[Optional["Planting"]] = relationship(back_populates="treatment_logs")
    schedule: Mapped[Optional["Schedule"]] = relationship(back_populates="treatment_logs")


class WateringLog(Base):
    __tablename__ = "watering_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    planting_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plantings.id", ondelete="CASCADE"), index=True)
    bed_id: Mapped[Optional[int]] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), index=True)
    garden_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gardens.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"), index=True)

    date: Mapped[date] = mapped_column(Date)
    amount_inches: Mapped[Optional[float]] = mapped_column(Float)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    method: Mapped[Optional[str]] = mapped_column(
        Enum("drip", "hand", "sprinkler", "soaker", "other", name="watering_method_enum")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    planting: Mapped[Optional["Planting"]] = relationship(back_populates="watering_logs")
    schedule: Mapped[Optional["Schedule"]] = relationship(back_populates="watering_logs")
