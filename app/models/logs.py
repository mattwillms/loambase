from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    ARRAY, Boolean, Date, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SeederRun(Base):
    __tablename__ = "seeder_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("running", "complete", "failed", "budget_reached", name="seeder_status_enum")
    )
    current_page: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[Optional[int]] = mapped_column(Integer)
    records_synced: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)


class WeatherCache(Base):
    __tablename__ = "weather_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    date: Mapped[date] = mapped_column(Date, index=True)

    high_temp_f: Mapped[Optional[float]] = mapped_column(Float)
    low_temp_f: Mapped[Optional[float]] = mapped_column(Float)
    humidity_pct: Mapped[Optional[float]] = mapped_column(Float)
    precip_inches: Mapped[Optional[float]] = mapped_column(Float)
    wind_mph: Mapped[Optional[float]] = mapped_column(Float)
    conditions: Mapped[Optional[str]] = mapped_column(String(100))
    uv_index: Mapped[Optional[float]] = mapped_column(Float)
    soil_temp_f: Mapped[Optional[float]] = mapped_column(Float)
    frost_warning: Mapped[bool] = mapped_column(Boolean, default=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    garden_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gardens.id", ondelete="SET NULL"), index=True)
    planting_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plantings.id", ondelete="SET NULL"))

    date: Mapped[date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    photos: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="journal_entries")
    garden: Mapped[Optional["Garden"]] = relationship(back_populates="journal_entries")
    planting: Mapped[Optional["Planting"]] = relationship(back_populates="journal_entries")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(
        Enum("create", "update", "delete", "login", "export", name="audit_action_enum")
    )
    entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    details: Mapped[Optional[dict]] = mapped_column(JSON)

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(
        Enum("running", "success", "failed", "skipped", name="pipeline_status_enum")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    records_processed: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


class ApiRequestLog(Base):
    __tablename__ = "api_request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    method: Mapped[str] = mapped_column(String(10))
    endpoint: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(
        Enum("water", "fertilize", "frost", "heat", "spray", "harvest", "custom",
             name="notification_type_enum")
    )
    channel: Mapped[str] = mapped_column(
        Enum("email", name="notification_channel_enum"), default="email"
    )
    status: Mapped[str] = mapped_column(
        Enum("sent", "delivered", "failed", name="notification_status_enum")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    message_preview: Mapped[Optional[str]] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="notification_logs")
