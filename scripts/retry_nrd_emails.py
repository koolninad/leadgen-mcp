#!/usr/bin/env python3
"""Retry sending emails for NRD leads that were scored but not emailed.

Uses sender rotation across active pool accounts.
Respects rate limits (3s between emails, checks daily quota).

Usage:
    PYTHONPATH=./src python3 scripts/retry_nrd_emails.py [--limit 200] [--min-score 30]
"""

import asyncio
import json
import logging
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retry_nrd")

# Junk email patterns to skip
JUNK_PATTERNS = [
    "privacy", "proxy", "whoisguard", "protect", "redacted",
    "domainsbyproxy", "contactprivacy", "anonymize", "whoisprotect",
    "hugedomains", "wix-domains", "xserver", "apiname", "wdp.services",
    "namecheap", "godaddy", "domaincontrol", "networksolutions",
    "tucows", "enom", "register.com", "wild-west", "dreamhost",
    "hostgator", "bluehost", "ionos", "ovh.net", "gandi.net",
    "dropcatch", "afternic", "sedo", "dan.com", "whoisblind",
    "whoistrustee", "withheld", "abuse@", "noreply", "no-reply",
    "postmaster", "hostmaster", "webmaster",
]


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200, help="Max emails to send")
    parser.add_argument("--min-score", type=int, default=30)
    args = parser.parse_args()

    from leadgen_mcp.db.pg_repository import get_pool
    from leadgen_mcp.email_sender.rotation import pick_sender, record_send
    from leadgen_mcp.email_sender.smtp import send_email, text_to_html
    from leadgen_mcp.ai.ollama_client import generate as ollama_generate
    from leadgen_mcp.nrd_processor.processor import generate_outreach_email
    from leadgen_mcp.notifications.telegram import send_lead_notification, flush_queue
    from leadgen_mcp.config import settings

    pool = await get_pool()

    # Get eligible leads
    rows = await pool.fetch(f"""
        SELECT id, domain, tld, registered_date, registrant_email,
               registrant_name, registrant_org, score, score_reasons
        FROM nrd_domains
        WHERE score >= $1 AND email_sent = FALSE AND registrant_email IS NOT NULL
        ORDER BY score DESC
        LIMIT $2
    """, args.min_score, args.limit * 3)  # fetch extra to account for filtered

    logger.info(f"Found {len(rows)} candidates (filtering junk emails...)")

    sent = 0
    skipped = 0
    failed = 0

    for i, r in enumerate(rows):
        if sent >= args.limit:
            break

        email_to = r["registrant_email"]
        if not email_to or "@" not in email_to:
            continue

        # Skip junk emails
        email_lower = email_to.lower()
        if any(p in email_lower for p in JUNK_PATTERNS):
            skipped += 1
            continue

        domain = r["domain"]
        logger.info(f"[{sent+1}/{args.limit}] {domain} (score={r['score']}) -> {email_to}")

        # Pick a sender
        recipient_domain = email_to.split("@")[1] if "@" in email_to else None
        sender = await pick_sender(recipient_domain=recipient_domain, vertical="hostingduty")

        if not sender:
            logger.warning("No active senders with remaining quota — stopping")
            break

        # Generate email
        try:
            score_reasons = json.loads(r["score_reasons"]) if r["score_reasons"] else []
        except (json.JSONDecodeError, TypeError):
            score_reasons = []

        email_data = await generate_outreach_email(
            domain=domain,
            registrant_name=r.get("registrant_name"),
            registrant_org=r.get("registrant_org"),
            registrant_email=email_to,
            tld=r["tld"],
            score_reasons=score_reasons,
        )

        if "error" in email_data:
            logger.warning(f"  AI generation failed: {email_data['error']}")
            failed += 1
            continue

        # Send email
        body_html = text_to_html(email_data["body"])
        result = await send_email(
            to_email=email_to,
            subject=email_data["subject"],
            body_html=body_html,
            from_email=sender["email"],
            from_name=sender["display_name"],
            smtp_host=sender["smtp_host"],
            smtp_port=sender["smtp_port"],
            smtp_user=sender["smtp_user"],
            smtp_password=sender["smtp_password"],
            track=True,
        )

        if result.get("success"):
            sent += 1
            await record_send(sender["id"])
            await pool.execute(
                "UPDATE nrd_domains SET email_sent = TRUE, email_generated = TRUE, email_subject = $1 WHERE id = $2",
                email_data["subject"], r["id"],
            )
            logger.info(f"  SENT via {sender['email']}")

            # Telegram notification
            try:
                lead_card = {
                    "source_platform": "nrd",
                    "company_name": r.get("registrant_org") or domain,
                    "domain": domain,
                    "description": f"Newly registered domain ({r['registered_date']})",
                    "score": r["score"],
                    "_score_total": r["score"],
                    "signals": score_reasons,
                    "_verticals": ["hostingduty", "chandorkar"],
                    "_email_status": "sent",
                    "_email_to": email_to,
                    "_email_from": sender["email"],
                    "_email_subject": email_data["subject"],
                    "_email_body": email_data["body"],
                }
                await send_lead_notification(lead_card, lead_number=sent)
            except Exception:
                pass
        else:
            failed += 1
            logger.warning(f"  FAILED: {result.get('error')}")

        # Rate limit
        await asyncio.sleep(3)

    await flush_queue()
    await pool.close()

    logger.info(f"\n=== DONE: Sent={sent} | Skipped={skipped} | Failed={failed} ===")


if __name__ == "__main__":
    asyncio.run(main())
