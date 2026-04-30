"""
Email alert channel — sends to a single inbox via Gmail SMTP. Uses the
same App Password as the IMAP newsletter reader. Designed for low-volume
high-signal alerts (politician watchlist trades, etc.) — not for the
firehose stuff that goes to Telegram.

Tries ports in order: 465 (SSL), 587 (STARTTLS). Hetzner sometimes blocks
465 outbound; 587 usually works. Forces IPv4 because Docker IPv6 to Gmail
can fail with ENETUNREACH on this host.
"""
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from loguru import logger

from .config import settings


def _resolve_ipv4(host: str) -> Optional[str]:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        return infos[0][4][0] if infos else None
    except Exception:
        return None


def send_email(subject: str, html_body: str, to: Optional[str] = None) -> bool:
    """Send an HTML email via Gmail SMTP using the existing App Password.
    `to` defaults to ALERT_EMAIL env var, falls back to GMAIL_ADDRESS."""
    to = to or settings.alert_email or settings.gmail_address
    if not settings.gmail_address or not settings.gmail_app_password or not to:
        logger.debug("Email alerts: no credentials configured, skipping")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_address
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    # Force IPv4 — Hetzner Docker → Gmail over IPv6 fails ENETUNREACH
    ipv4 = _resolve_ipv4("smtp.gmail.com") or "smtp.gmail.com"

    last_err = None
    # Try STARTTLS on 587 first (Hetzner-friendly)
    try:
        with smtplib.SMTP(ipv4, 587, timeout=20) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(settings.gmail_address, settings.gmail_app_password)
            s.send_message(msg)
        logger.info(f"Email sent (587): {subject[:60]} → {to}")
        return True
    except Exception as e:
        last_err = e
        logger.debug(f"SMTP 587 failed, trying 465: {e}")

    # Fallback to SSL 465
    try:
        with smtplib.SMTP_SSL(ipv4, 465, timeout=20) as s:
            s.login(settings.gmail_address, settings.gmail_app_password)
            s.send_message(msg)
        logger.info(f"Email sent (465): {subject[:60]} → {to}")
        return True
    except Exception as e:
        logger.warning(f"Email send failed (587 err: {last_err}; 465 err: {e})")
        return False
