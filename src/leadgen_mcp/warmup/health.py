"""Reputation monitoring and health checks for sender accounts."""

import logging

from ..db.pg_repository import get_pool, update_sender, log_warmup_action

logger = logging.getLogger("leadgen.warmup.health")


async def update_bounce_rates() -> dict:
    """Recalculate bounce rates for all active/warming sender accounts.

    Returns {account_email: bounce_rate}.
    """
    pool = await get_pool()

    rows = await pool.fetch(
        """SELECT sa.id, sa.email, sa.sent_total,
                  COUNT(es.id) FILTER (WHERE es.bounced = TRUE) as bounces
           FROM sender_accounts sa
           LEFT JOIN emails_sent es ON es.from_email = sa.email
           WHERE sa.pool IN ('active', 'warming')
           GROUP BY sa.id, sa.email, sa.sent_total"""
    )

    results = {}
    for r in rows:
        sent = r["sent_total"] or 1
        bounces = r["bounces"] or 0
        rate = (bounces / sent) * 100 if sent > 0 else 0.0

        await update_sender(r["id"], bounce_rate=round(rate, 2))
        results[r["email"]] = rate

        if rate > 5.0:
            logger.warning("High bounce rate for %s: %.1f%%", r["email"], rate)

    return results


async def update_reputation(account_id: int, delta: float, reason: str) -> float:
    """Adjust reputation score for a sender account.

    Positive delta = good (reply received, email opened).
    Negative delta = bad (bounce, spam report).
    Clamped to 0-100.
    """
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT reputation_score FROM sender_accounts WHERE id = $1", account_id
    )
    if not row:
        return 0.0

    new_score = max(0.0, min(100.0, row["reputation_score"] + delta))
    await update_sender(account_id, reputation_score=round(new_score, 1))

    await log_warmup_action(
        account_id, "reputation_change",
        result=f"{row['reputation_score']:.1f} -> {new_score:.1f}",
        details={"delta": delta, "reason": reason},
    )

    return new_score
