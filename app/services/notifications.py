"""
Notification dispatch service.

Sends an email and writes a NotificationLog record. Never raises on failure —
logs the error and records "failed" status instead.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logs import NotificationLog
from app.services.email import send_email

logger = logging.getLogger(__name__)


async def dispatch_notification(
    db: AsyncSession,
    user,
    notification_type: str,
    subject: str,
    body: str,
) -> None:
    """Send an email notification and log the result to NotificationLog."""
    status = "sent"
    try:
        await send_email(subject, body)
    except Exception as exc:
        logger.error(
            "dispatch_notification: email failed for user %d: %s", user.id, exc
        )
        status = "failed"

    log = NotificationLog(
        user_id=user.id,
        notification_type=notification_type,
        channel="email",
        status=status,
        message_preview=body[:500],
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.commit()
