from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ARRAY, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnrichmentRule(Base):
    __tablename__ = "enrichment_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    strategy: Mapped[str] = mapped_column(
        Enum("priority", "union", "longest", "average", name="enrichment_strategy_enum")
    )
    source_priority: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
