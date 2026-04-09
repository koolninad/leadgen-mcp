"""SMTP email sending with aiosmtplib."""

import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from ..config import settings
from .tracking import inject_tracking


async def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    tracking_id: str | None = None,
    track: bool = True,
) -> dict:
    """Send an email via SMTP with optional tracking."""
    if not settings.smtp_user or not settings.smtp_password:
        return {"error": "SMTP not configured. Set SMTP_USER and SMTP_PASSWORD in .env"}

    if not tracking_id:
        tracking_id = uuid.uuid4().hex[:16]

    # Inject tracking if enabled
    if track:
        body_html = inject_tracking(body_html, tracking_id)

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email or settings.smtp_user}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = settings.smtp_from_email or settings.smtp_user

    # Plain text version (strip HTML tags for fallback)
    import re
    plain_text = re.sub(r"<[^>]+>", "", body_html)
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text)

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        return {
            "success": True,
            "to": to_email,
            "subject": subject,
            "tracking_id": tracking_id,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "to": to_email,
        }


def text_to_html(text: str) -> str:
    """Convert plain text email to basic HTML."""
    import html as html_lib
    escaped = html_lib.escape(text)
    paragraphs = escaped.split("\n\n")
    html_parts = [f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs]
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
             font-size: 14px; line-height: 1.6; color: #333; max-width: 600px;">
{''.join(html_parts)}
</body>
</html>"""
