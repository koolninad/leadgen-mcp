"""Sender rotation — weighted selection from active pool.

Algorithm:
1. Filter to pool='active', is_enabled=True, sent_today < daily_quota
2. If vertical specified, prefer sender domains matching the vertical
3. Avoid same sender → same recipient domain within 24h
4. Weight by: (daily_quota - sent_today) * reputation_score
5. Weighted random selection
"""

import logging
import random

from ..db.pg_repository import (
    get_pool,
    increment_sender_count,
    reset_daily_counters as _reset_counters,
)

logger = logging.getLogger("leadgen.email.rotation")


async def pick_sender(
    recipient_domain: str | None = None,
    vertical: str | None = None,
) -> dict | None:
    """Select the best sender account for the next email.

    Returns sender_accounts row as dict, or None if all exhausted.
    """
    pool = await get_pool()

    rows = await pool.fetch(
        """SELECT *,
               (daily_quota - sent_today) * reputation_score AS weight
        FROM sender_accounts
        WHERE pool = 'active'
          AND is_enabled = TRUE
          AND sent_today < daily_quota
        ORDER BY weight DESC"""
    )

    if not rows:
        logger.warning("No active senders available with remaining quota")
        return None

    candidates = [dict(r) for r in rows]

    # Filter: avoid sending from same sender to same recipient domain recently
    if recipient_domain:
        recent = await pool.fetch(
            """SELECT DISTINCT from_email FROM emails_sent
               WHERE to_email LIKE $1
                 AND sent_at > NOW() - INTERVAL '24 hours'""",
            f"%@{recipient_domain}",
        )
        recent_set = {r["from_email"] for r in recent}
        filtered = [c for c in candidates if c["email"] not in recent_set]
        if filtered:
            candidates = filtered

    # Prefer senders whose domain matches the vertical
    if vertical:
        vertical_lower = vertical.lower()
        matched = [c for c in candidates if vertical_lower in c["domain"].lower()]
        if matched:
            candidates = matched

    # Weighted random selection
    weights = [max(float(c["weight"]), 0.1) for c in candidates]
    chosen = random.choices(candidates, weights=weights, k=1)[0]

    logger.info("Selected sender: %s (quota: %d/%d, rep: %.0f)",
                chosen["email"], chosen["sent_today"], chosen["daily_quota"],
                chosen["reputation_score"])
    return chosen


async def record_send(account_id: int) -> None:
    """Increment sent_today and sent_total after a successful send."""
    await increment_sender_count(account_id)


async def reset_daily_counters() -> int:
    """Reset sent_today for all accounts. Call at midnight UTC."""
    count = await _reset_counters()
    logger.info("Reset daily counters for %d sender accounts", count)
    return count
