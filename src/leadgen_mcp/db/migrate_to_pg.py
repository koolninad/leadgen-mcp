"""One-shot migration from SQLite to PostgreSQL.

Reads all data from the SQLite database and inserts into PostgreSQL,
transforming data types as needed (TEXT dates → TIMESTAMPTZ, JSON strings → JSONB,
INTEGER booleans → BOOLEAN).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import asyncpg

from .pg_schema import SCHEMA_SQL

logger = logging.getLogger("leadgen.db.migrate")


def _parse_dt(val: str | None) -> datetime | None:
    """Parse SQLite datetime string to Python datetime."""
    if not val:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f+00:00",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(val, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _parse_json(val: str | None) -> str | None:
    """Validate JSON string for JSONB column."""
    if not val:
        return None
    try:
        json.loads(val)
        return val
    except (json.JSONDecodeError, TypeError):
        return None


async def migrate_sqlite_to_pg(
    sqlite_path: str,
    pg_dsn: str,
) -> dict:
    """Migrate all data from SQLite to PostgreSQL.

    Returns {"tables": {name: row_count}, "total": int}.
    """
    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    logger.info("Connecting to PostgreSQL: %s", pg_dsn.split("@")[-1])
    pg = await asyncpg.connect(dsn=pg_dsn)

    logger.info("Creating schema...")
    await pg.execute(SCHEMA_SQL)

    logger.info("Opening SQLite: %s", sqlite_path)
    sqlite = await aiosqlite.connect(sqlite_path)
    sqlite.row_factory = aiosqlite.Row

    stats = {"tables": {}, "total": 0}

    try:
        # Migrate core tables in dependency order
        await _migrate_leads(sqlite, pg, stats)
        await _migrate_scan_results(sqlite, pg, stats)
        await _migrate_contacts(sqlite, pg, stats)
        await _migrate_lead_scores(sqlite, pg, stats)
        await _migrate_campaigns(sqlite, pg, stats)
        await _migrate_campaign_leads(sqlite, pg, stats)
        await _migrate_emails_sent(sqlite, pg, stats)

        # Migrate NRD tables if they exist
        tables = await sqlite.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'nrd%'"
        )
        nrd_tables = {r[0] for r in tables}
        if "nrd_staging" in nrd_tables:
            await _migrate_nrd_staging(sqlite, pg, stats)
        if "nrd_domains" in nrd_tables:
            await _migrate_nrd_domains(sqlite, pg, stats)
        if "nrd_domains_ref" in nrd_tables:
            await _migrate_nrd_domains_ref(sqlite, pg, stats)
        if "nrd_progress" in nrd_tables:
            await _migrate_nrd_progress(sqlite, pg, stats)

    finally:
        await sqlite.close()
        await pg.close()

    stats["total"] = sum(stats["tables"].values())
    logger.info("Migration complete: %d rows across %d tables",
                stats["total"], len(stats["tables"]))
    return stats


async def _migrate_leads(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM leads")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO leads (id, domain, company_name, source_platform, source_url,
                   description, budget_estimate, signals, raw_data, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (id) DO NOTHING""",
                d["id"], d.get("domain"), d.get("company_name"),
                d.get("source_platform"), d.get("source_url"),
                d.get("description"), d.get("budget_estimate"),
                _parse_json(d.get("signals")) or "[]",
                _parse_json(d.get("raw_data")) or "{}",
                _parse_dt(d.get("created_at")) or datetime.now(timezone.utc),
                _parse_dt(d.get("updated_at")) or datetime.now(timezone.utc),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip lead %s: %s", d.get("id"), e)
    stats["tables"]["leads"] = count
    logger.info("  leads: %d rows", count)


async def _migrate_scan_results(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM scan_results")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO scan_results (id, lead_id, scan_type, result, severity, scanned_at)
                   VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (id) DO NOTHING""",
                d["id"], d["lead_id"], d["scan_type"],
                _parse_json(d.get("result")) or "{}",
                d.get("severity"),
                _parse_dt(d.get("scanned_at")) or datetime.now(timezone.utc),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip scan_result %s: %s", d.get("id"), e)
    stats["tables"]["scan_results"] = count
    logger.info("  scan_results: %d rows", count)


async def _migrate_contacts(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM contacts")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO contacts (id, lead_id, name, title, email, email_verified, phone, source, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (id) DO NOTHING""",
                d["id"], d["lead_id"], d.get("name"), d.get("title"),
                d.get("email"), bool(d.get("email_verified", 0)),
                d.get("phone"), d.get("source"),
                _parse_dt(d.get("created_at")) or datetime.now(timezone.utc),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip contact %s: %s", d.get("id"), e)
    stats["tables"]["contacts"] = count
    logger.info("  contacts: %d rows", count)


async def _migrate_lead_scores(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM lead_scores")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO lead_scores (id, lead_id, tech_score, opportunity_score,
                   budget_score, engagement_score, contact_score, total_score, scored_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (id) DO NOTHING""",
                d["id"], d["lead_id"],
                d.get("tech_score", 0), d.get("opportunity_score", 0),
                d.get("budget_score", 0), d.get("engagement_score", 0),
                d.get("contact_score", 0), d.get("total_score", 0),
                _parse_dt(d.get("scored_at")) or datetime.now(timezone.utc),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip lead_score %s: %s", d.get("id"), e)
    stats["tables"]["lead_scores"] = count
    logger.info("  lead_scores: %d rows", count)


async def _migrate_campaigns(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM campaigns")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO campaigns (id, name, status, template, schedule, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO NOTHING""",
                d["id"], d["name"], d.get("status", "draft"),
                d.get("template"), _parse_json(d.get("schedule")),
                _parse_dt(d.get("created_at")) or datetime.now(timezone.utc),
                _parse_dt(d.get("updated_at")) or datetime.now(timezone.utc),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip campaign %s: %s", d.get("id"), e)
    stats["tables"]["campaigns"] = count
    logger.info("  campaigns: %d rows", count)


async def _migrate_campaign_leads(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM campaign_leads")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO campaign_leads (id, campaign_id, lead_id, sequence_step, status,
                   next_send_at, sent_at, opened_at, clicked_at, replied_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (id) DO NOTHING""",
                d["id"], d["campaign_id"], d["lead_id"],
                d.get("sequence_step", 0), d.get("status", "pending"),
                _parse_dt(d.get("next_send_at")), _parse_dt(d.get("sent_at")),
                _parse_dt(d.get("opened_at")), _parse_dt(d.get("clicked_at")),
                _parse_dt(d.get("replied_at")),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip campaign_lead %s: %s", d.get("id"), e)
    stats["tables"]["campaign_leads"] = count
    logger.info("  campaign_leads: %d rows", count)


async def _migrate_emails_sent(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM emails_sent")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO emails_sent (id, campaign_lead_id, to_email, subject, body,
                   tracking_id, sent_at, opened_at, clicked_at, bounced, bounce_type)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT (id) DO NOTHING""",
                d["id"], d.get("campaign_lead_id"), d["to_email"],
                d["subject"], d["body"], d.get("tracking_id"),
                _parse_dt(d.get("sent_at")) or datetime.now(timezone.utc),
                _parse_dt(d.get("opened_at")), _parse_dt(d.get("clicked_at")),
                bool(d.get("bounced", 0)), d.get("bounce_type"),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip email %s: %s", d.get("id"), e)
    stats["tables"]["emails_sent"] = count
    logger.info("  emails_sent: %d rows", count)


async def _migrate_nrd_staging(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM nrd_staging")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO nrd_staging (domain, tld, registered_date, processed)
                   VALUES ($1,$2,$3,$4) ON CONFLICT (domain) DO NOTHING""",
                d["domain"], d["tld"], d["registered_date"], bool(d.get("processed", 0)),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip nrd_staging %s: %s", d.get("domain"), e)
    stats["tables"]["nrd_staging"] = count
    logger.info("  nrd_staging: %d rows", count)


async def _migrate_nrd_domains(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM nrd_domains")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO nrd_domains (domain, tld, registered_date, whois_data,
                   registrant_email, registrant_name, registrant_org, registrar,
                   creation_date, expiry_date, nameservers, score, score_reasons,
                   email_generated, email_sent, email_subject, telegram_sent)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                   ON CONFLICT (domain) DO NOTHING""",
                d["domain"], d["tld"], d["registered_date"],
                _parse_json(d.get("whois_data")),
                d.get("registrant_email"), d.get("registrant_name"),
                d.get("registrant_org"), d.get("registrar"),
                d.get("creation_date"), d.get("expiry_date"),
                _parse_json(d.get("nameservers")),
                d.get("score", 0), _parse_json(d.get("score_reasons")),
                bool(d.get("email_generated", 0)), bool(d.get("email_sent", 0)),
                d.get("email_subject"), bool(d.get("telegram_sent", 0)),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip nrd_domain %s: %s", d.get("domain"), e)
    stats["tables"]["nrd_domains"] = count
    logger.info("  nrd_domains: %d rows", count)


async def _migrate_nrd_domains_ref(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM nrd_domains_ref")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO nrd_domains_ref (domain, tld, registered_date,
                   registrant_email, registrar, nameservers)
                   VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (domain) DO NOTHING""",
                d["domain"], d["tld"], d["registered_date"],
                d.get("registrant_email"), d.get("registrar"),
                _parse_json(d.get("nameservers")),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip nrd_ref %s: %s", d.get("domain"), e)
    stats["tables"]["nrd_domains_ref"] = count
    logger.info("  nrd_domains_ref: %d rows", count)


async def _migrate_nrd_progress(sqlite, pg, stats):
    rows = await sqlite.execute_fetchall("SELECT * FROM nrd_progress")
    count = 0
    for r in rows:
        d = dict(r)
        try:
            await pg.execute(
                """INSERT INTO nrd_progress (date, total_domains, processed_count,
                   whois_done, scored_count, emailed_count, status, error_message,
                   started_at, completed_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (date) DO NOTHING""",
                d["date"], d.get("total_domains", 0), d.get("processed_count", 0),
                d.get("whois_done", 0), d.get("scored_count", 0),
                d.get("emailed_count", 0), d.get("status", "pending"),
                d.get("error_message"),
                _parse_dt(d.get("started_at")), _parse_dt(d.get("completed_at")),
            )
            count += 1
        except Exception as e:
            logger.warning("Skip nrd_progress %s: %s", d.get("date"), e)
    stats["tables"]["nrd_progress"] = count
    logger.info("  nrd_progress: %d rows", count)
