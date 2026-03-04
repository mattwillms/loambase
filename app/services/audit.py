"""Fire-and-forget audit log helper."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logs import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    ip: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Write an audit log entry. Never raises — failures are logged and swallowed."""
    try:
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            ip_address=ip,
            details=details,
        )
        db.add(entry)
        await db.commit()
    except Exception:
        logger.exception("Failed to write audit log: action=%s entity_type=%s", action, entity_type)
        try:
            await db.rollback()
        except Exception:
            pass
