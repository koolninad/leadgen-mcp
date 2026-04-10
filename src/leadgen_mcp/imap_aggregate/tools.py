"""MCP tool registration for IMAP aggregate."""

import logging

from ..db.pg_repository import get_pool, get_replies

logger = logging.getLogger("leadgen.imap.tools")


def register_imap(mcp):
    """Register IMAP aggregate MCP tools."""

    @mcp.tool()
    async def inbox_stats() -> dict:
        """Get reply inbox statistics."""
        pool = await get_pool()
        row = await pool.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_auto_reply = FALSE AND is_bounce = FALSE AND is_unsubscribe = FALSE) as real_replies,
                COUNT(*) FILTER (WHERE is_bounce = TRUE) as bounces,
                COUNT(*) FILTER (WHERE is_auto_reply = TRUE) as auto_replies,
                COUNT(*) FILTER (WHERE is_unsubscribe = TRUE) as unsubscribes
            FROM reply_inbox
        """)
        return dict(row) if row else {}

    @mcp.tool()
    async def inbox_recent(limit: int = 20, only_real: bool = True) -> list[dict]:
        """Get recent replies from the inbox."""
        return await get_replies(limit=limit, only_real=only_real)
