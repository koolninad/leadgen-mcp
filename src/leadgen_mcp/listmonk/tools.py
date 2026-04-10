"""MCP tool registration for Listmonk."""

import logging

from .client import ListmonkClient
from .sync import sync_leads_to_listmonk, create_campaign_for_vertical

logger = logging.getLogger("leadgen.listmonk.tools")


def register_listmonk(mcp):
    """Register Listmonk MCP tools."""

    @mcp.tool()
    async def listmonk_sync(min_score: float = 40.0, vertical: str | None = None) -> dict:
        """Sync scored leads to Listmonk as subscribers."""
        return await sync_leads_to_listmonk(min_score=min_score, vertical=vertical)

    @mcp.tool()
    async def listmonk_create_campaign(
        vertical: str, subject: str, body: str, from_email: str | None = None,
    ) -> dict:
        """Create a Listmonk campaign for a vertical."""
        client = ListmonkClient()
        return await create_campaign_for_vertical(
            client, vertical, subject, body, from_email,
        )

    @mcp.tool()
    async def listmonk_campaign_status(campaign_id: int) -> dict:
        """Get campaign status from Listmonk."""
        client = ListmonkClient()
        return await client.get_campaign(campaign_id)

    @mcp.tool()
    async def listmonk_start_campaign(campaign_id: int) -> dict:
        """Start a Listmonk campaign."""
        client = ListmonkClient()
        return await client.start_campaign(campaign_id)

    @mcp.tool()
    async def listmonk_lists() -> dict:
        """List all Listmonk lists."""
        client = ListmonkClient()
        return await client.get_lists()
