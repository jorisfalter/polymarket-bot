"""
Email alert channel — sends to a single inbox via Gmail SMTP. Uses the
same App Password as the IMAP newsletter reader. Designed for low-volume
high-signal alerts (politician watchlist trades, etc.) — not for the
firehose stuff that goes to Telegram.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from loguru import logger

from .config import settings


def send_email(subject: str, html_body: str, to: Optional[str] = None) -> bool:
    """Send an HTML email via Gmail SMTP using the existing App Password.
    `to` defaults to ALERT_EMAIL env var, falls back to GMAIL_ADDRESS."""
    to = to or settings.alert_email or settings.gmail_address
    if not settings.gmail_address or not settings.gmail_app_password or not to:
        logger.debug("Email alerts: no credentials configured, skipping")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.gmail_address
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(settings.gmail_address, settings.gmail_app_password)
            s.send_message(msg)
        logger.info(f"Email sent: {subject[:60]} → {to}")
        return True
    except Exception as e:
        logger.warning(f"Email send failed: {e}")
        return False
