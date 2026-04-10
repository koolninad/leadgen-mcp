"""MCP tool registration for warmup module."""

import logging

from ..db.pg_repository import get_all_senders, get_pool

logger = logging.getLogger("leadgen.warmup.tools")


def register_warmup(mcp):
    """Register warmup MCP tools."""

    @mcp.tool()
    async def warmup_status() -> dict:
        """Show warmup status for all sender accounts."""
        senders = await get_all_senders()
        pools = {"warming": [], "active": [], "cooling": [], "disabled": []}
        for s in senders:
            pools.setdefault(s["pool"], []).append({
                "email": s["email"],
                "domain": s["domain"],
                "warmup_day": s["warmup_day"],
                "daily_quota": s["daily_quota"],
                "sent_today": s["sent_today"],
                "sent_total": s["sent_total"],
                "reputation": s["reputation_score"],
                "bounce_rate": s["bounce_rate"],
            })
        return {
            "total_accounts": len(senders),
            "pools": {k: len(v) for k, v in pools.items()},
            "accounts": pools,
        }

    @mcp.tool()
    async def warmup_history(account_email: str, limit: int = 20) -> list[dict]:
        """Show recent warmup activity for an account."""
        pool = await get_pool()
        rows = await pool.fetch(
            """SELECT wl.*, sa.email
               FROM warmup_log wl
               JOIN sender_accounts sa ON sa.id = wl.account_id
               WHERE sa.email = $1
               ORDER BY wl.created_at DESC
               LIMIT $2""",
            account_email, limit,
        )
        return [dict(r) for r in rows]
