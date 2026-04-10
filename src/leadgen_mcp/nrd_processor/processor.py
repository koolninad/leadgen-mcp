"""Main NRD bulk processing pipeline.

Orchestrates the full flow:
1. Fetch domain lists from cenk/nrd
2. WHOIS lookup via who-dat
3. Score and filter domains
4. Generate AI outreach emails via Ollama
5. Send emails via SMTP
6. Notify via Telegram

This is SEPARATE from the main pipeline (pipeline.py).
It shares the database file and notification/email infrastructure.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from ..config import settings
from ..ai.ollama_client import generate as ollama_generate
from ..email_sender.smtp import send_email, text_to_html
from ..notifications.telegram import send_lead_notification, flush_queue
from .models import NRD_SCHEMA_SQL
from .fetcher import fetch_domains, ingest_domains_to_db
from .whois_lookup import process_whois_batch

logger = logging.getLogger("leadgen.nrd.processor")

# ----- Scoring constants -----

# Commercial TLDs that suggest a business
COMMERCIAL_TLDS = {
    "com", "io", "ai", "dev", "co", "app", "tech", "cloud", "software",
    "digital", "agency", "studio", "design", "consulting", "solutions",
    "services", "pro", "biz", "net", "org", "shop", "store", "online",
    "site", "website", "team", "work", "tools", "platform", "systems",
    "media", "marketing", "global", "ventures", "capital", "finance",
    "health", "care", "edu", "legal", "law",
}

# TLDs to skip entirely (junk / spam heavy)
JUNK_TLDS = {
    "xyz", "top", "icu", "buzz", "click", "link", "info", "win", "bid",
    "loan", "download", "racing", "review", "stream", "date", "faith",
    "party", "science", "cricket", "accountant", "gdn", "men", "work",
    "cf", "ga", "gq", "ml", "tk",  # Free TLDs, almost all spam
}

# Patterns that suggest random/generated domain names (not real businesses)
RANDOM_PATTERNS = [
    re.compile(r"^[a-z]{20,}$"),           # Very long single word
    re.compile(r"^[a-z0-9]{2,4}-[a-z0-9]{2,4}-[a-z0-9]{2,4}"),  # x-x-x patterns
    re.compile(r"\d{5,}"),                  # 5+ consecutive digits
    re.compile(r"^[bcdfghjklmnpqrstvwxyz]{6,}$"),  # All consonants
    re.compile(r"^(xn--|\d+[a-z]\d+)"),    # Punycode or spammy
    re.compile(r"(casino|poker|slot|bet|porn|xxx|sex|dating|loan|crypto|nft|token)"),
]

# Patterns that suggest a real business name
BUSINESS_PATTERNS = [
    re.compile(r"(agency|studio|labs?|works?|tech|digital|media|group|solutions|consulting)"),
    re.compile(r"(health|care|legal|finance|capital|ventures|partners)"),
    re.compile(r"(design|creative|marketing|analytics|data|cloud|soft|dev)"),
    re.compile(r"^[a-z]{3,12}(app|hq|io|ly|ify|ful|able|ment)$"),
]


async def _get_nrd_db() -> aiosqlite.Connection:
    """Get a connection to the shared DB with NRD tables initialized."""
    db_path = settings.db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(NRD_SCHEMA_SQL)
    await db.commit()
    return db


# -----------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------

def score_domain(
    domain: str,
    tld: str,
    registered_date: str,
    whois_data: dict | None = None,
) -> tuple[int, list[str]]:
    """Score a newly registered domain for outreach potential.

    Returns (score 0-100, list of reasons).
    Higher score = more likely a real business worth reaching out to.
    """
    score = 0
    reasons = []
    name = domain.rsplit(".", 1)[0] if "." in domain else domain

    # --- TLD scoring ---
    if tld in JUNK_TLDS:
        return 0, ["junk_tld"]

    if tld in COMMERCIAL_TLDS:
        score += 15
        reasons.append(f"commercial_tld:{tld}")
    else:
        score += 5
        reasons.append(f"other_tld:{tld}")

    # Premium TLDs
    if tld in ("com", "io", "ai", "dev", "co", "app"):
        score += 5
        reasons.append("premium_tld")

    # --- Domain name quality ---
    # Check for random/junk patterns
    for pattern in RANDOM_PATTERNS:
        if pattern.search(name):
            return 0, ["random_name"]

    # Length check: too short or too long is suspicious
    if len(name) < 3:
        score -= 10
        reasons.append("too_short")
    elif 4 <= len(name) <= 15:
        score += 10
        reasons.append("good_length")
    elif len(name) > 25:
        score -= 5
        reasons.append("too_long")

    # Business-like name patterns
    for pattern in BUSINESS_PATTERNS:
        if pattern.search(name):
            score += 10
            reasons.append("business_name")
            break

    # Pronounceable / has vowels (real words vs random strings)
    vowel_ratio = sum(1 for c in name if c in "aeiou") / max(len(name), 1)
    if 0.2 <= vowel_ratio <= 0.6:
        score += 5
        reasons.append("pronounceable")
    elif vowel_ratio < 0.15:
        score -= 10
        reasons.append("not_pronounceable")

    # --- Recency scoring ---
    try:
        reg_date = datetime.strptime(registered_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        days_ago = (datetime.now(timezone.utc) - reg_date).days
        if days_ago <= 3:
            score += 15
            reasons.append("very_recent")
        elif days_ago <= 7:
            score += 10
            reasons.append("recent_7d")
        elif days_ago <= 14:
            score += 5
            reasons.append("recent_14d")
    except ValueError:
        pass

    # --- WHOIS data scoring ---
    if whois_data and isinstance(whois_data, dict) and "error" not in whois_data:
        # Has registrant email = strong signal
        email = whois_data.get("registrant_email")
        if email and "@" in str(email):
            # Skip privacy/proxy emails
            email_lower = str(email).lower()
            privacy_keywords = [
                "privacy", "proxy", "whoisguard", "protect", "redacted",
                "withheld", "gdpr", "contactprivacy", "domainsbyproxy",
                "anonymize", "whoisprotect",
            ]
            if any(kw in email_lower for kw in privacy_keywords):
                score += 5
                reasons.append("has_privacy_email")
            else:
                score += 25
                reasons.append("has_real_email")
        else:
            score -= 5
            reasons.append("no_email")

        # Has organization
        org = whois_data.get("registrant_org")
        if org and len(str(org)) > 2:
            org_lower = str(org).lower()
            if not any(kw in org_lower for kw in ["privacy", "proxy", "redacted", "withheld"]):
                score += 10
                reasons.append("has_org")

        # Has registrant name
        name_val = whois_data.get("registrant_name")
        if name_val and len(str(name_val)) > 2:
            name_lower = str(name_val).lower()
            if not any(kw in name_lower for kw in ["privacy", "redacted", "withheld", "data protected"]):
                score += 5
                reasons.append("has_name")

        # Nameservers can indicate a real setup vs parked
        ns = whois_data.get("nameservers", [])
        if ns and len(ns) >= 2:
            ns_str = " ".join(ns).lower()
            # Parked domain indicators
            if any(pk in ns_str for pk in ["parkingcrew", "bodis", "sedo", "afternic", "dan.com"]):
                score -= 20
                reasons.append("parked_domain")
            # Real hosting providers
            elif any(
                host in ns_str
                for host in [
                    "cloudflare", "aws", "google", "azure", "digitalocean",
                    "vercel", "netlify", "namecheap", "godaddy",
                ]
            ):
                score += 5
                reasons.append("real_hosting")

    # Clamp score
    score = max(0, min(100, score))
    return score, reasons


# -----------------------------------------------------------------------
# Email generation
# -----------------------------------------------------------------------

async def generate_outreach_email(
    domain: str,
    registrant_name: str | None,
    registrant_org: str | None,
    registrant_email: str | None,
    tld: str,
    score_reasons: list[str],
) -> dict:
    """Generate a personalized outreach email using Ollama.

    Returns: {"subject": str, "body": str} or {"error": str}
    """
    # Build context for AI
    company_hint = registrant_org or registrant_name or domain.rsplit(".", 1)[0]
    name_hint = registrant_name or "there"

    prompt = f"""Write a short, professional cold outreach email for a web development agency.

Context:
- The recipient just registered the domain: {domain}
- Their name (if known): {name_hint}
- Their company/org (if known): {company_hint}
- The domain TLD is .{tld}

Requirements:
- Subject line should be catchy but professional (NOT spammy)
- Keep the email under 150 words
- Mention that you noticed they recently registered {domain}
- Offer to help them build their website/web application
- Be conversational, not salesy
- Include a clear but soft call-to-action (reply or schedule a call)
- Sign off as: {settings.agency_name}
  Website: {settings.agency_website}

Output format (exactly):
SUBJECT: <subject line>
BODY:
<email body>
"""

    try:
        response = await ollama_generate(
            prompt=prompt,
            system_prompt=(
                "You are an expert at writing cold outreach emails that get replies. "
                "Be concise, personal, and genuine. Never use exclamation marks excessively. "
                "Never use phrases like 'I hope this email finds you well'."
            ),
            temperature=0.8,
            max_tokens=512,
        )

        # Parse subject and body from response
        lines = response.strip().split("\n")
        subject = ""
        body_lines = []
        in_body = False

        for line in lines:
            if line.upper().startswith("SUBJECT:"):
                subject = line.split(":", 1)[1].strip()
            elif line.upper().startswith("BODY:"):
                in_body = True
            elif in_body:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        if not subject:
            subject = f"Your new domain {domain} — need a website?"
        if not body:
            return {"error": "AI generated empty body"}

        return {"subject": subject, "body": body}

    except Exception as e:
        logger.error("Ollama email generation failed: %s", e)
        return {"error": str(e)}


# -----------------------------------------------------------------------
# Main processor
# -----------------------------------------------------------------------

async def run_nrd_pipeline(
    days: int = 60,
    batch_size: int = 100,
    dry_run: bool = True,
    min_score: int = 40,
    whois_concurrency: int = 5,
) -> dict:
    """Run the full NRD bulk processing pipeline.

    Steps:
    1. Fetch domain lists from cenk/nrd repo
    2. Ingest new domains to DB
    3. WHOIS lookup for unprocessed domains
    4. Score all domains
    5. For high-scoring domains: generate email + send + Telegram

    Returns summary stats dict.
    """
    stats = {
        "domains_fetched": 0,
        "domains_ingested": 0,
        "whois_lookups": 0,
        "domains_scored": 0,
        "high_score_count": 0,
        "emails_generated": 0,
        "emails_sent": 0,
        "telegram_sent": 0,
        "errors": 0,
        "start_time": time.monotonic(),
    }

    logger.info("=" * 60)
    logger.info("NRD BULK PROCESSOR — Starting")
    logger.info("  Days: %d | Batch: %d | Dry run: %s | Min score: %d",
                days, batch_size, dry_run, min_score)
    logger.info("=" * 60)

    # --- Step 1: Fetch domain lists ---
    logger.info("[Step 1/5] Fetching domain lists from cenk/nrd...")
    try:
        domains_by_date = await fetch_domains(days=days)
        total_domains = sum(len(d) for d in domains_by_date.values())
        stats["domains_fetched"] = total_domains
        logger.info("Fetched %d domains across %d dates", total_domains, len(domains_by_date))
    except Exception as e:
        logger.error("Failed to fetch NRD data: %s", e)
        stats["errors"] += 1
        return stats

    if not domains_by_date:
        logger.info("No new domains to process")
        return stats

    # --- Step 2: Ingest to DB ---
    logger.info("[Step 2/5] Ingesting domains to database...")
    try:
        ingest_stats = await ingest_domains_to_db(domains_by_date)
        stats["domains_ingested"] = sum(ingest_stats.values())
        logger.info("Ingested %d new domains", stats["domains_ingested"])
    except Exception as e:
        logger.error("Failed to ingest domains: %s", e)
        stats["errors"] += 1
        return stats

    # --- Steps 3-5: WHOIS → Score → Email in rolling batches ---
    # Instead of doing ALL WHOIS first, process in chunks:
    # Every N WHOIS batches, score what we have and email high-scorers
    logger.info("[Steps 3-5] WHOIS → Score → Email (rolling batches)...")
    SCORE_EVERY_N_BATCHES = 10  # Score + email after every 10 WHOIS batches

    db = await _get_nrd_db()
    batch_count = 0
    try:
        while True:
            rows = await db.execute_fetchall(
                """SELECT domain, registered_date FROM nrd_staging
                   WHERE processed = 0
                   ORDER BY registered_date DESC
                   LIMIT ?""",
                (batch_size,),
            )
            if not rows:
                break

            domains = [dict(r)["domain"] for r in rows]
            logger.info("  WHOIS batch: %d domains", len(domains))

            try:
                await process_whois_batch(domains, concurrency=whois_concurrency)
                stats["whois_lookups"] += len(domains)
            except Exception as e:
                logger.error("  WHOIS batch error: %s", e)
                stats["errors"] += 1

            for d in domains:
                await db.execute(
                    "UPDATE nrd_staging SET processed = 1 WHERE domain = ?",
                    (d,),
                )
            await db.commit()

            batch_count += 1

            # Every N batches: score + email what we have so far
            if batch_count % SCORE_EVERY_N_BATCHES == 0:
                logger.info("  -- Interim score + email pass (after %d batches) --", batch_count)
                await _score_domains(stats)
                await _process_high_score_domains(min_score, dry_run, stats)
                await flush_queue()

            await asyncio.sleep(0.5)
    finally:
        await db.close()

    logger.info("  WHOIS lookups done: %d total in %d batches", stats["whois_lookups"], batch_count)

    # Final score + email pass for any remaining
    logger.info("[Step 4/5] Final scoring pass...")
    await _score_domains(stats)

    logger.info("[Step 5/5] Final email pass (>= %d)...", min_score)
    await _process_high_score_domains(min_score, dry_run, stats)

    # Flush Telegram queue
    await flush_queue()

    # --- Summary ---
    elapsed = time.monotonic() - stats["start_time"]
    logger.info("=" * 60)
    logger.info("NRD PIPELINE COMPLETE in %.1fs", elapsed)
    logger.info("  Fetched: %d | Ingested: %d | WHOIS: %d",
                stats["domains_fetched"], stats["domains_ingested"], stats["whois_lookups"])
    logger.info("  Scored: %d | High-score: %d | Emails: %d/%d | Telegram: %d",
                stats["domains_scored"], stats["high_score_count"],
                stats["emails_sent"], stats["emails_generated"], stats["telegram_sent"])
    logger.info("  Errors: %d", stats["errors"])
    logger.info("=" * 60)

    return stats


async def _process_whois_batches(
    batch_size: int,
    concurrency: int,
    stats: dict,
) -> None:
    """Process WHOIS lookups in batches for unprocessed domains."""
    db = await _get_nrd_db()
    try:
        while True:
            # Get a batch of unprocessed domains from staging
            rows = await db.execute_fetchall(
                """SELECT domain, registered_date FROM nrd_staging
                   WHERE processed = 0
                   ORDER BY registered_date DESC
                   LIMIT ?""",
                (batch_size,),
            )
            if not rows:
                break

            domains = [dict(r)["domain"] for r in rows]
            logger.info("  WHOIS batch: %d domains", len(domains))

            try:
                await process_whois_batch(domains, concurrency=concurrency)
                stats["whois_lookups"] += len(domains)
            except Exception as e:
                logger.error("  WHOIS batch error: %s", e)
                stats["errors"] += 1

            # Mark as processed in staging regardless of outcome
            for d in domains:
                await db.execute(
                    "UPDATE nrd_staging SET processed = 1 WHERE domain = ?",
                    (d,),
                    )
                await db.commit()

            # Brief pause between batches
            await asyncio.sleep(0.5)

    finally:
        await db.close()

    logger.info("  WHOIS lookups done: %d total", stats["whois_lookups"])


async def _score_domains(stats: dict) -> None:
    """Score all domains that have WHOIS data but no score yet."""
    db = await _get_nrd_db()
    try:
        batch_size = 500
        offset = 0

        while True:
            rows = await db.execute_fetchall(
                """SELECT id, domain, tld, registered_date, whois_data,
                          registrant_email, registrant_name, registrant_org, registrar, nameservers
                   FROM nrd_domains
                   WHERE score = 0
                   LIMIT ? OFFSET ?""",
                (batch_size, offset),
            )
            if not rows:
                break

            for row in rows:
                r = dict(row)
                whois = None
                if r.get("whois_data"):
                    try:
                        whois = json.loads(r["whois_data"])
                    except json.JSONDecodeError:
                        pass

                # Re-parse whois for scoring if we have raw data
                whois_parsed = None
                if whois:
                    # The whois_data column stores raw JSON; reconstruct parsed fields
                    whois_parsed = {
                        "registrant_email": r.get("registrant_email"),
                        "registrant_name": r.get("registrant_name"),
                        "registrant_org": r.get("registrant_org"),
                        "nameservers": json.loads(r.get("nameservers", "[]")) if r.get("nameservers") else [],
                    }

                score, reasons = score_domain(
                    domain=r["domain"],
                    tld=r["tld"],
                    registered_date=r["registered_date"],
                    whois_data=whois_parsed,
                )

                await db.execute(
                    """UPDATE nrd_domains
                       SET score = ?, score_reasons = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (score, json.dumps(reasons), r["id"]),
                )
                stats["domains_scored"] += 1

            await db.commit()
            offset += batch_size

    finally:
        await db.close()

    logger.info("  Scored %d domains", stats["domains_scored"])


async def _process_high_score_domains(
    min_score: int,
    dry_run: bool,
    stats: dict,
) -> None:
    """Generate emails and send notifications for high-scoring domains."""
    db = await _get_nrd_db()
    try:
        # Get high-scoring domains that haven't been emailed yet
        rows = await db.execute_fetchall(
            """SELECT id, domain, tld, registered_date, registrant_email,
                      registrant_name, registrant_org, score, score_reasons
               FROM nrd_domains
               WHERE score >= ? AND email_sent = 0 AND registrant_email IS NOT NULL
               ORDER BY score DESC, registered_date DESC
               LIMIT 200""",
            (min_score,),
        )

        if not rows:
            logger.info("  No high-score domains pending outreach")
            return

        high_score_domains = [dict(r) for r in rows]
        stats["high_score_count"] = len(high_score_domains)
        logger.info("  Found %d high-score domains for outreach", len(high_score_domains))

        for i, domain_data in enumerate(high_score_domains, 1):
            domain = domain_data["domain"]
            email_to = domain_data["registrant_email"]

            if not email_to or "@" not in email_to:
                continue

            # Skip privacy/proxy/registrar/hosting emails
            email_lower = email_to.lower()
            if any(kw in email_lower for kw in [
                "privacy", "proxy", "whoisguard", "protect", "redacted",
                "domainsbyproxy", "contactprivacy", "anonymize", "whoisprotect",
                "hugedomains", "wix-domains", "xserver", "apiname", "wdp.services",
                "namecheap", "godaddy", "domaincontrol", "networksolutions",
                "tucows", "enom", "register.com", "wild-west", "dreamhost",
                "hostgator", "bluehost", "ionos", "ovh.net", "gandi.net",
                "dropcatch", "afternic", "sedo", "dan.com", "whoisblind",
                "whoistrustee", "withheld", "abuse@", "noreply", "no-reply",
                "postmaster", "hostmaster", "webmaster",
            ]):
                continue

            logger.info("  [%d/%d] Processing %s (score: %d) -> %s",
                        i, len(high_score_domains), domain,
                        domain_data["score"], email_to)

            # Generate email via Ollama
            try:
                score_reasons = json.loads(domain_data.get("score_reasons", "[]"))
            except (json.JSONDecodeError, TypeError):
                score_reasons = []

            email_result = await generate_outreach_email(
                domain=domain,
                registrant_name=domain_data.get("registrant_name"),
                registrant_org=domain_data.get("registrant_org"),
                registrant_email=email_to,
                tld=domain_data["tld"],
                score_reasons=score_reasons,
            )

            if "error" in email_result:
                logger.warning("  Email generation failed for %s: %s", domain, email_result["error"])
                stats["errors"] += 1
                continue

            stats["emails_generated"] += 1

            # Mark email as generated
            await db.execute(
                """UPDATE nrd_domains
                   SET email_generated = 1, email_subject = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (email_result["subject"], domain_data["id"]),
            )
            await db.commit()

            # Send email (with sender rotation if PG available)
            if not dry_run:
                try:
                    sender = None
                    sender_email = settings.smtp_from_email or settings.smtp_user

                    # Try sender rotation
                    if settings.database_url:
                        try:
                            from ..email_sender.rotation import pick_sender, record_send
                            recipient_domain = email_to.split("@")[1] if "@" in email_to else None
                            sender = await pick_sender(recipient_domain=recipient_domain, vertical="hostingduty")
                        except Exception:
                            pass

                    if sender:
                        sender_email = sender["email"]
                        body_html = text_to_html(email_result["body"])
                        send_result = await send_email(
                            to_email=email_to,
                            subject=email_result["subject"],
                            body_html=body_html,
                            from_email=sender["email"],
                            from_name=sender["display_name"],
                            smtp_host=sender["smtp_host"],
                            smtp_port=sender["smtp_port"],
                            smtp_user=sender["smtp_user"],
                            smtp_password=sender["smtp_password"],
                            track=True,
                        )
                        if send_result.get("success"):
                            await record_send(sender["id"])
                    else:
                        body_html = text_to_html(email_result["body"])
                        send_result = await send_email(
                            to_email=email_to,
                            subject=email_result["subject"],
                            body_html=body_html,
                            track=True,
                        )

                    if send_result.get("success"):
                        stats["emails_sent"] += 1
                        await db.execute(
                            """UPDATE nrd_domains
                               SET email_sent = 1, updated_at = datetime('now')
                               WHERE id = ?""",
                            (domain_data["id"],),
                        )
                        await db.commit()
                        logger.info("  Sent email to %s for %s (from: %s)", email_to, domain, sender_email)
                    else:
                        logger.warning("  Email send failed: %s", send_result.get("error"))
                        stats["errors"] += 1

                except Exception as e:
                    logger.error("  Email send error for %s: %s", domain, e)
                    stats["errors"] += 1

                # Rate limit: pause between emails
                await asyncio.sleep(3.0)
            else:
                logger.info("  [DRY RUN] Would send email to %s: %s",
                            email_to, email_result["subject"])

            # Send Telegram notification
            try:
                lead_card = {
                    "source_platform": "nrd",
                    "company_name": domain_data.get("registrant_org") or domain,
                    "domain": domain,
                    "description": f"Newly registered domain ({domain_data['registered_date']})",
                    "score": domain_data["score"],
                    "_score_total": domain_data["score"],
                    "signals": score_reasons,
                    "_emails": [email_to],
                    "_verticals": ["hostingduty", "chandorkar"],
                    "_email_status": "dry_run" if dry_run else "sent",
                    "_email_to": email_to,
                    "_email_from": sender_email if not dry_run else (settings.smtp_from_email or settings.smtp_user),
                    "_email_subject": email_result.get("subject", ""),
                    "_email_body": email_result.get("body", ""),
                }
                await send_lead_notification(lead_card, lead_number=i)
                stats["telegram_sent"] += 1

                await db.execute(
                    """UPDATE nrd_domains
                       SET telegram_sent = 1, updated_at = datetime('now')
                       WHERE id = ?""",
                    (domain_data["id"],),
                )
                await db.commit()

            except Exception as e:
                logger.warning("  Telegram notification failed: %s", e)

    finally:
        await db.close()
