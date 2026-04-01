"""
Test SMTP Email for AFL Dashboard
==================================
This script sends a test email using the same SMTP settings as the pipeline.
"""

import os
from utils.notifications import send_email_notification

if __name__ == "__main__":
    print("Sending test email using SMTP settings from .env...")
    send_email_notification(
        title="AFL Dashboard SMTP Test",
        message="This is a test email from the AFL Dashboard notification system.",
        is_error=False
    )
    print("If no errors occurred, check your inbox (and spam folder). If you see errors, check your SMTP settings and network connectivity.")
