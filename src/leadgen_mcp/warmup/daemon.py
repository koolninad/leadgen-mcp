"""Background warmup daemon — runs every N hours.

Cycle:
1. For each account in 'warming' pool: send warmup emails to seed accounts
2. Check seed inboxes for auto-replies
3. Process bounces → decrease reputation
4. Adjust quotas based on warmup_day progression
5. Graduate: warming → active when day >= 30 and bounce < 2%
6. Demote: active → cooling when bounce > 5% or reputation < 30
7. Reset sent_today counters at midnight UTC
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..config import settings
from ..db.pg_repository import (
    get_pool,
    get_all_senders,
    update_sender,
    log_warmup_action,
    reset_daily_counters,
)
from .scheduler import get_quota_for_day, should_graduate, should_demote, should_reactivate
from .seed_network import send_warmup_email, check_and_reply_seed
from .health import update_bounce_rates

logger = logging.getLogger("leadgen.warmup.daemon")


class WarmupDaemon:
    """Background task that runs the warmup cycle periodically."""

    def __init__(self):
        self._running = False
        self._cycle_count = 0

    async def run_forever(self):
        """Main loop."""
        self._running = True
        interval = settings.warmup_cycle_hours * 3600
        logger.info("Warmup daemon starting (cycle every %.1fh)", settings.warmup_cycle_hours)

        while self._running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error("Warmup cycle error: %s", e, exc_info=True)

            # Wait, checking for stop every second
            waited = 0
            while waited < interval and self._running:
                await asyncio.sleep(1)
                waited += 1

        logger.info("Warmup daemon stopped")

    def stop(self):
        self._running = False

    async def run_cycle(self) -> dict:
        """Single warmup cycle."""
        self._cycle_count += 1
        logger.info("=== Warmup cycle %d starting ===", self._cycle_count)

        stats = {
            "warmup_emails_sent": 0,
            "seed_replies": 0,
            "quotas_adjusted": 0,
            "graduated": 0,
            "demoted": 0,
            "reactivated": 0,
        }

        senders = await get_all_senders()
        seed_accounts = settings.warmup_seeds
        now = datetime.now(timezone.utc)

        # Step 1: Send warmup emails for accounts in 'warming' pool
        warming = [s for s in senders if s["pool"] == "warming" and s["is_enabled"]]
        for account in warming:
            if not seed_accounts:
                logger.warning("No seed accounts configured — skip warmup sending")
                break

            remaining = account["daily_quota"] - account["sent_today"]
            if remaining <= 0:
                continue

            # Send to random seed accounts
            sends = min(remaining, len(seed_accounts))
            targets = list(seed_accounts)
            # Don't send to self
            targets = [t for t in targets if t != account["email"]]
            if not targets:
                continue

            import random
            chosen_seeds = random.sample(targets, min(sends, len(targets)))

            for seed_email in chosen_seeds:
                ok = await send_warmup_email(
                    from_email=account["email"],
                    from_name=account["display_name"],
                    to_email=seed_email,
                    smtp_host=account["smtp_host"],
                    smtp_port=account["smtp_port"],
                    smtp_user=account["smtp_user"],
                    smtp_password=account["smtp_password"],
                )
                if ok:
                    stats["warmup_emails_sent"] += 1
                    await update_sender(account["id"],
                                        sent_today=account["sent_today"] + 1,
                                        sent_total=account["sent_total"] + 1)
                    await log_warmup_action(account["id"], "send",
                                            result="success",
                                            details={"to": seed_email})
                else:
                    await log_warmup_action(account["id"], "send",
                                            result="failure",
                                            details={"to": seed_email})

                await asyncio.sleep(2)  # Pause between sends

        # Step 2: Check seed accounts for replies (auto-reply)
        for seed_email in seed_accounts:
            try:
                replies = await check_and_reply_seed(
                    imap_host=settings.nubo_imap_host,
                    imap_port=settings.nubo_imap_port,
                    imap_user=seed_email,
                    imap_password="",  # Seed accounts need passwords configured
                    smtp_host=settings.nubo_smtp_host,
                    smtp_port=settings.nubo_smtp_port,
                )
                stats["seed_replies"] += replies
            except Exception as e:
                logger.warning("Seed reply check failed for %s: %s", seed_email, e)

        # Step 3: Update bounce rates
        await update_bounce_rates()

        # Step 4: Adjust quotas and warmup_day for warming accounts
        for account in warming:
            new_day = account["warmup_day"] + 1
            new_quota = get_quota_for_day(new_day)

            if new_quota != account["daily_quota"]:
                await update_sender(account["id"],
                                    warmup_day=new_day,
                                    daily_quota=new_quota)
                await log_warmup_action(account["id"], "quota_increase",
                                        details={"day": new_day, "quota": new_quota})
                stats["quotas_adjusted"] += 1
                logger.info("  %s: day %d, quota %d -> %d",
                            account["email"], new_day, account["daily_quota"], new_quota)
            else:
                await update_sender(account["id"], warmup_day=new_day)

        # Step 5: Graduate warming → active
        senders = await get_all_senders()  # refresh
        for account in senders:
            if account["pool"] == "warming" and should_graduate(account):
                await update_sender(account["id"], pool="active")
                await log_warmup_action(account["id"], "pool_move",
                                        details={"from": "warming", "to": "active"})
                stats["graduated"] += 1
                logger.info("  GRADUATED: %s -> active", account["email"])

            elif account["pool"] == "active" and should_demote(account):
                await update_sender(account["id"], pool="cooling")
                await log_warmup_action(account["id"], "pool_move",
                                        details={"from": "active", "to": "cooling"})
                stats["demoted"] += 1
                logger.warning("  DEMOTED: %s -> cooling", account["email"])

            elif account["pool"] == "cooling" and should_reactivate(account):
                await update_sender(account["id"], pool="warming", warmup_day=15)
                await log_warmup_action(account["id"], "pool_move",
                                        details={"from": "cooling", "to": "warming"})
                stats["reactivated"] += 1
                logger.info("  REACTIVATED: %s -> warming (day 15)", account["email"])

        # Step 6: Reset daily counters if it's a new day (roughly)
        if now.hour < 1:  # Near midnight UTC
            count = await reset_daily_counters()
            logger.info("  Reset daily counters for %d accounts", count)

        logger.info("=== Warmup cycle %d complete: sent=%d replies=%d graduated=%d ===",
                     self._cycle_count, stats["warmup_emails_sent"],
                     stats["seed_replies"], stats["graduated"])
        return stats
