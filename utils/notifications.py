"""
Notification Utilities for AFL Dashboard Pipeline
===================================================
Provides macOS and email notification helpers.
Email is optional — if ALERT_EMAIL is not set in .env, email calls
are a silent no-op.

Usage:
    from utils.notifications import notify

    notify("AFL Dashboard Update", "✅ All steps completed!")
"""

import os
import smtplib
import subprocess
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

logger = logging.getLogger(__name__)

# Load .env lazily (python-dotenv may not be installed in all envs)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()


# ============================================================================
# macOS Notification
# ============================================================================

def send_macos_notification(title: str, message: str, sound: str = "Basso"):
    """Send a macOS notification via osascript. Silent no-op on non-Mac."""
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'display notification "{message}" with title "{title}" sound name "{sound}"',
            ],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass  # Best-effort


# ============================================================================
# Email Notification
# ============================================================================

def send_email_notification(title: str, message: str, is_error: bool = False):
    """
    Send an email notification via SMTP.

    Requires ALERT_EMAIL in .env.  Silent no-op if not configured.
    If SMTP_USER and SMTP_PASSWORD are set, authenticates via STARTTLS.
    Otherwise, falls back to macOS 'mailx' (local delivery).

    Args:
        title: Email subject line.
        message: Body text.
        is_error: If True, prefix subject with ❌; otherwise ✅.
    """
    if not ALERT_EMAIL:
        return  # Not configured — skip silently

    icon = "❌" if is_error else "✅"
    subject = f"{icon} {title}"

    # ── Try SMTP if credentials provided ──────────────────────
    if SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_USER
            msg["To"] = ALERT_EMAIL

            # Plain text body
            msg.attach(MIMEText(message, "plain"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())

            logger.info(f"Email sent to {ALERT_EMAIL}")
            return
        except Exception as e:
            logger.warning(f"SMTP email failed: {e}")
            # Fall through to mailx fallback

    # ── Fallback: macOS mailx (uses local MTA) ────────────────
    try:
        subprocess.run(
            ["mailx", "-s", subject, ALERT_EMAIL],
            input=message.encode(),
            timeout=10,
            capture_output=True,
        )
        logger.info(f"Email sent via mailx to {ALERT_EMAIL}")
    except Exception as e:
        logger.warning(f"Email notification failed: {e}")


# ============================================================================
# Unified notify()
# ============================================================================

def notify(title: str, message: str, is_error: bool = False):
    """
    Send a notification via all configured channels.

    Currently supports:
      - macOS native notifications (always)
      - Email (if ALERT_EMAIL is set in .env)
    """
    send_macos_notification(title, message)
    send_email_notification(title, message, is_error=is_error)
