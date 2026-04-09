"""MCP tool definitions for the Email Sender module."""

from .campaign import (
    create_campaign,
    start_campaign,
    pause_campaign,
    send_single_email,
)
from .rate_limiter import rate_limiter
from ..db.repository import get_campaign_stats, get_email_analytics


def register(mcp):
    """Register all email sender tools with the MCP server."""

    @mcp.tool()
    async def send_email(
        to: str, subject: str, body: str, track: bool = True
    ) -> dict:
        """Send a single email with optional open/click tracking and rate limiting.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Email body text (will be converted to HTML)
            track: Whether to add open/click tracking (default: True)
        """
        return await send_single_email(
            to_email=to,
            subject=subject,
            body=body,
            track=track,
        )

    @mcp.tool()
    async def create_email_campaign(
        name: str, lead_ids: list[str], template: str = "tech_audit",
        delay_hours: int = 72,
    ) -> dict:
        """Create a drip email campaign targeting a list of leads.

        Args:
            name: Campaign name
            lead_ids: List of lead IDs to include in the campaign
            template: Email template to use (tech_audit, project_match, growth_partner, etc.)
            delay_hours: Hours between follow-up emails (default: 72 = 3 days)
        """
        return await create_campaign(
            name=name,
            lead_ids=lead_ids,
            template=template,
            delay_hours=delay_hours,
        )

    @mcp.tool()
    async def start_email_campaign(campaign_id: str) -> dict:
        """Start or resume an email campaign.

        Args:
            campaign_id: The campaign ID to start
        """
        return await start_campaign(campaign_id)

    @mcp.tool()
    async def pause_email_campaign(campaign_id: str) -> dict:
        """Pause an active email campaign.

        Args:
            campaign_id: The campaign ID to pause
        """
        return await pause_campaign(campaign_id)

    @mcp.tool()
    async def get_campaign_statistics(campaign_id: str) -> dict:
        """Get campaign statistics: sent, opened, clicked, replied, bounced counts.

        Args:
            campaign_id: The campaign ID to get stats for
        """
        stats = await get_campaign_stats(campaign_id)
        rate_stats = rate_limiter.get_stats()
        return {
            "campaign_id": campaign_id,
            "stats": stats,
            "rate_limiter": rate_stats,
        }

    @mcp.tool()
    async def get_email_stats(days: int = 30) -> dict:
        """Get aggregate email analytics across all campaigns.

        Args:
            days: Number of days to look back (default: 30)
        """
        analytics = await get_email_analytics(days)
        rate_stats = rate_limiter.get_stats()

        total_sent = analytics.get("total_sent", 0) or 0
        total_opened = analytics.get("total_opened", 0) or 0
        total_clicked = analytics.get("total_clicked", 0) or 0

        return {
            "period_days": days,
            "total_sent": total_sent,
            "total_opened": total_opened,
            "total_clicked": total_clicked,
            "total_bounced": analytics.get("total_bounced", 0) or 0,
            "open_rate": f"{(total_opened / total_sent * 100):.1f}%" if total_sent else "N/A",
            "click_rate": f"{(total_clicked / total_sent * 100):.1f}%" if total_sent else "N/A",
            "rate_limiter": rate_stats,
        }
