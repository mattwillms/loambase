"""
Async email sender using aiosmtplib with STARTTLS.

Reads EMAIL_HOST, EMAIL_PORT, EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_FROM,
EMAIL_TO from environment via Settings. If EMAIL_HOST is not configured,
send_email() logs a warning and returns without raising.
"""
import logging
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(subject: str, body: str) -> None:
    if not settings.EMAIL_HOST:
        logger.warning("email: EMAIL_HOST not configured — skipping send")
        return

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = settings.EMAIL_TO

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.EMAIL_USERNAME,
            password=settings.EMAIL_PASSWORD,
            start_tls=True,
        )
        logger.info("email: sent '%s' to %s", subject, settings.EMAIL_TO)
    except Exception as exc:
        logger.exception("email: failed to send '%s': %s", subject, exc)
