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
    from_email: str | None = None,
    from_name: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> dict:
    """Send an email via SMTP with optional tracking.

    If from_email/smtp_* are provided, uses those credentials (sender rotation).
    Otherwise falls back to settings.smtp_* defaults.
    """
    _user = smtp_user or settings.smtp_user
    _password = smtp_password or settings.smtp_password
    _host = smtp_host or settings.smtp_host
    _port = smtp_port or settings.smtp_port
    _from_email = from_email or settings.smtp_from_email or _user
    _from_name = from_name or settings.smtp_from_name

    if not _user or not _password:
        return {"error": "SMTP not configured. Set SMTP_USER and SMTP_PASSWORD in .env"}

    if not tracking_id:
        tracking_id = uuid.uuid4().hex[:16]

    # Inject tracking if enabled
    if track:
        body_html = inject_tracking(body_html, tracking_id)

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{_from_name} <{_from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = _from_email

    # Plain text version (strip HTML tags for fallback)
    import re
    plain_text = re.sub(r"<[^>]+>", "", body_html)
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text)

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=_host,
            port=_port,
            username=_user,
            password=_password,
            start_tls=True,
        )
        return {
            "success": True,
            "to": to_email,
            "from": _from_email,
            "subject": subject,
            "tracking_id": tracking_id,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "to": to_email,
            "from": _from_email,
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
