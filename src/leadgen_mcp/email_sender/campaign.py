"""Campaign management: create, start, pause, track campaigns."""

import asyncio
import json

from ..db.repository import (
    create_campaign as db_create_campaign,
    update_campaign_status,
    add_leads_to_campaign,
    get_lead,
    get_contacts,
    get_campaign_stats as db_get_stats,
    get_email_analytics as db_get_analytics,
    save_email_sent,
)
from ..ai.email_generator import generate_outreach_email
from .smtp import send_email, text_to_html
from .rate_limiter import rate_limiter
from .tracking import generate_tracking_id


async def create_campaign(
    name: str, lead_ids: list[str], template: str = "tech_audit",
    delay_hours: int = 72, send_time: str = "09:00",
) -> dict:
    """Create a new email campaign."""
    campaign = await db_create_campaign(
        name=name,
        template=template,
        schedule={"delay_hours": delay_hours, "send_time": send_time},
    )

    count = await add_leads_to_campaign(campaign["id"], lead_ids)

    return {
        **campaign,
        "leads_added": count,
        "template": template,
        "schedule": {"delay_hours": delay_hours, "send_time": send_time},
    }


async def start_campaign(campaign_id: str) -> dict:
    """Start sending emails for a campaign."""
    await update_campaign_status(campaign_id, "active")

    stats = await db_get_stats(campaign_id)

    return {
        "campaign_id": campaign_id,
        "status": "active",
        "message": "Campaign started. Emails will be sent respecting rate limits.",
        "stats": stats,
    }


async def pause_campaign(campaign_id: str) -> dict:
    """Pause an active campaign."""
    await update_campaign_status(campaign_id, "paused")
    return {"campaign_id": campaign_id, "status": "paused"}


async def send_single_email(
    to_email: str, subject: str, body: str,
    lead_id: str | None = None, track: bool = True,
) -> dict:
    """Send a single email with rate limiting and tracking."""
    domain = to_email.split("@")[1] if "@" in to_email else "unknown"

    # Wait for rate limit
    wait_time = await rate_limiter.acquire(domain)

    tracking_id = generate_tracking_id()
    html_body = text_to_html(body)

    result = await send_email(
        to_email=to_email,
        subject=subject,
        body_html=html_body,
        tracking_id=tracking_id,
        track=track,
    )

    # Save to database
    if result.get("success"):
        await save_email_sent(
            campaign_lead_id=None,
            to_email=to_email,
            subject=subject,
            body=body,
            tracking_id=tracking_id,
        )

    result["waited_seconds"] = round(wait_time, 1)
    return result
