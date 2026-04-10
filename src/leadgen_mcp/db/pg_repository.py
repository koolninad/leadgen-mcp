"""PostgreSQL CRUD operations using asyncpg.

Drop-in replacement for repository.py — same function signatures,
asyncpg internals with $N positional params.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from ..config import settings
from .pg_schema import create_schema

logger = logging.getLogger("leadgen.db.pg")

_pool: asyncpg.Pool | None = None


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.pg_pool_min,
            max_size=settings.pg_pool_max,
        )
        await create_schema(_pool)
        logger.info("PostgreSQL pool created (%d-%d connections)",
                     settings.pg_pool_min, settings.pg_pool_max)
    return _pool


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _row_to_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    # Convert JSONB columns that come back as strings
    for key in ("signals", "raw_data", "result", "schedule", "config",
                "whois_data", "score_reasons", "nameservers", "details"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# --- Leads ---

async def upsert_lead(
    domain: str | None = None,
    company_name: str | None = None,
    source_platform: str = "manual",
    source_url: str | None = None,
    description: str | None = None,
    budget_estimate: int | None = None,
    signals: list[str] | None = None,
    raw_data: dict | None = None,
) -> dict:
    pool = await get_pool()

    if domain:
        row = await pool.fetchrow(
            "SELECT id FROM leads WHERE domain = $1", domain
        )
        if row:
            lead_id = row["id"]
            await pool.execute(
                """UPDATE leads SET
                   company_name = COALESCE($1, company_name),
                   source_platform = COALESCE($2, source_platform),
                   source_url = COALESCE($3, source_url),
                   description = COALESCE($4, description),
                   budget_estimate = COALESCE($5, budget_estimate),
                   signals = COALESCE($6, signals),
                   raw_data = COALESCE($7, raw_data),
                   updated_at = $8
                   WHERE id = $9""",
                company_name, source_platform, source_url, description,
                budget_estimate,
                json.dumps(signals) if signals else None,
                json.dumps(raw_data) if raw_data else None,
                _now(), lead_id,
            )
            return await get_lead(lead_id)

    lead_id = _uid()
    await pool.execute(
        """INSERT INTO leads (id, domain, company_name, source_platform, source_url,
           description, budget_estimate, signals, raw_data, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
        lead_id, domain, company_name, source_platform, source_url,
        description, budget_estimate,
        json.dumps(signals or []), json.dumps(raw_data or {}),
        _now(), _now(),
    )
    return await get_lead(lead_id)


async def get_lead(lead_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM leads WHERE id = $1", lead_id)
    return _row_to_dict(row)


async def query_leads(
    min_score: float = 0,
    source_platform: str | None = None,
    domain_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    query = """
        SELECT l.*, COALESCE(ls.total_score, 0) as score
        FROM leads l
        LEFT JOIN lead_scores ls ON l.id = ls.lead_id
        WHERE COALESCE(ls.total_score, 0) >= $1
    """
    params: list = [min_score]
    idx = 2

    if source_platform:
        query += f" AND l.source_platform = ${idx}"
        params.append(source_platform)
        idx += 1
    if domain_contains:
        query += f" AND l.domain LIKE ${idx}"
        params.append(f"%{domain_contains}%")
        idx += 1

    query += f" ORDER BY score DESC LIMIT ${idx} OFFSET ${idx + 1}"
    params.extend([limit, offset])

    rows = await pool.fetch(query, *params)
    return [_row_to_dict(r) for r in rows]


# --- Scan Results ---

async def save_scan_result(
    lead_id: str, scan_type: str, result: dict, severity: str = "info"
) -> dict:
    pool = await get_pool()
    scan_id = _uid()
    await pool.execute(
        """INSERT INTO scan_results (id, lead_id, scan_type, result, severity, scanned_at)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        scan_id, lead_id, scan_type, json.dumps(result), severity, _now(),
    )
    return {"id": scan_id, "lead_id": lead_id, "scan_type": scan_type, "severity": severity}


async def get_scan_results(lead_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM scan_results WHERE lead_id = $1 ORDER BY scanned_at DESC",
        lead_id,
    )
    results = []
    for r in rows:
        d = _row_to_dict(r)
        results.append(d)
    return results


# --- Contacts ---

async def save_contact(
    lead_id: str, name: str | None = None, title: str | None = None,
    email: str | None = None, email_verified: bool = False,
    phone: str | None = None, source: str = "website",
) -> dict:
    pool = await get_pool()
    contact_id = _uid()
    await pool.execute(
        """INSERT INTO contacts (id, lead_id, name, title, email, email_verified, phone, source, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        contact_id, lead_id, name, title, email, email_verified, phone, source, _now(),
    )
    return {"id": contact_id, "lead_id": lead_id, "email": email, "name": name}


async def get_contacts(lead_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM contacts WHERE lead_id = $1", lead_id,
    )
    return [_row_to_dict(r) for r in rows]


# --- Lead Scores ---

async def save_score(lead_id: str, scores: dict) -> dict:
    pool = await get_pool()
    score_id = _uid()
    total = sum(scores.values())
    await pool.execute(
        """INSERT INTO lead_scores
           (id, lead_id, tech_score, opportunity_score, budget_score,
            engagement_score, contact_score, total_score, scored_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (lead_id) DO UPDATE SET
            tech_score = EXCLUDED.tech_score,
            opportunity_score = EXCLUDED.opportunity_score,
            budget_score = EXCLUDED.budget_score,
            engagement_score = EXCLUDED.engagement_score,
            contact_score = EXCLUDED.contact_score,
            total_score = EXCLUDED.total_score,
            scored_at = EXCLUDED.scored_at""",
        score_id, lead_id,
        scores.get("tech", 0), scores.get("opportunity", 0),
        scores.get("budget", 0), scores.get("engagement", 0),
        scores.get("contact", 0), total, _now(),
    )
    return {"lead_id": lead_id, "total_score": total, **scores}


# --- Campaigns ---

async def create_campaign(name: str, template: str, schedule: dict) -> dict:
    pool = await get_pool()
    campaign_id = _uid()
    await pool.execute(
        """INSERT INTO campaigns (id, name, status, template, schedule, created_at, updated_at)
           VALUES ($1, $2, 'draft', $3, $4, $5, $6)""",
        campaign_id, name, template, json.dumps(schedule), _now(), _now(),
    )
    return {"id": campaign_id, "name": name, "status": "draft"}


async def update_campaign_status(campaign_id: str, status: str) -> dict:
    pool = await get_pool()
    await pool.execute(
        "UPDATE campaigns SET status = $1, updated_at = $2 WHERE id = $3",
        status, _now(), campaign_id,
    )
    return {"id": campaign_id, "status": status}


async def add_leads_to_campaign(campaign_id: str, lead_ids: list[str]) -> int:
    pool = await get_pool()
    count = 0
    for lid in lead_ids:
        cl_id = _uid()
        await pool.execute(
            """INSERT INTO campaign_leads (id, campaign_id, lead_id, sequence_step, status)
               VALUES ($1, $2, $3, 0, 'pending')""",
            cl_id, campaign_id, lid,
        )
        count += 1
    return count


async def save_email_sent(
    campaign_lead_id: str | None, to_email: str, subject: str,
    body: str, tracking_id: str, from_email: str | None = None,
) -> dict:
    pool = await get_pool()
    email_id = _uid()
    await pool.execute(
        """INSERT INTO emails_sent
           (id, campaign_lead_id, to_email, from_email, subject, body, tracking_id, sent_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        email_id, campaign_lead_id, to_email, from_email, subject, body, tracking_id, _now(),
    )
    return {"id": email_id, "tracking_id": tracking_id, "to": to_email}


async def get_campaign_stats(campaign_id: str) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN cl.status = 'sent' THEN 1 ELSE 0 END) as sent,
            SUM(CASE WHEN cl.status = 'opened' THEN 1 ELSE 0 END) as opened,
            SUM(CASE WHEN cl.status = 'clicked' THEN 1 ELSE 0 END) as clicked,
            SUM(CASE WHEN cl.status = 'replied' THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN cl.status = 'bounced' THEN 1 ELSE 0 END) as bounced
        FROM campaign_leads cl WHERE cl.campaign_id = $1""",
        campaign_id,
    )
    return _row_to_dict(row) if row else {}


async def get_email_analytics(days: int = 30) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT
            COUNT(*) as total_sent,
            SUM(CASE WHEN opened_at IS NOT NULL THEN 1 ELSE 0 END) as total_opened,
            SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) as total_clicked,
            SUM(CASE WHEN bounced THEN 1 ELSE 0 END) as total_bounced
        FROM emails_sent
        WHERE sent_at >= NOW() - INTERVAL '%s days'""" % days,
    )
    return _row_to_dict(row) if row else {}


# --- Sender Accounts (NEW) ---

async def add_sender_account(
    email: str, domain: str, display_name: str,
    smtp_user: str, smtp_password: str,
    smtp_host: str = "mail.nubo.email", smtp_port: int = 587,
    imap_host: str = "mail.nubo.email", imap_port: int = 993,
) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO sender_accounts
           (email, domain, display_name, smtp_host, smtp_port, smtp_user, smtp_password,
            imap_host, imap_port)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (email) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            smtp_password = EXCLUDED.smtp_password,
            updated_at = NOW()
           RETURNING *""",
        email, domain, display_name, smtp_host, smtp_port, smtp_user, smtp_password,
        imap_host, imap_port,
    )
    return _row_to_dict(row)


async def get_active_senders(pool_name: str = "active") -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT * FROM sender_accounts
           WHERE pool = $1 AND is_enabled = TRUE AND sent_today < daily_quota
           ORDER BY (daily_quota - sent_today) * reputation_score DESC""",
        pool_name,
    )
    return [_row_to_dict(r) for r in rows]


async def get_all_senders() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM sender_accounts ORDER BY pool, domain, email"
    )
    return [_row_to_dict(r) for r in rows]


async def update_sender(account_id: int, **kwargs) -> None:
    pool = await get_pool()
    sets = []
    vals = []
    idx = 1
    for k, v in kwargs.items():
        sets.append(f"{k} = ${idx}")
        vals.append(v)
        idx += 1
    sets.append(f"updated_at = ${idx}")
    vals.append(_now())
    idx += 1
    vals.append(account_id)
    await pool.execute(
        f"UPDATE sender_accounts SET {', '.join(sets)} WHERE id = ${idx}",
        *vals,
    )


async def increment_sender_count(account_id: int) -> None:
    pool = await get_pool()
    await pool.execute(
        """UPDATE sender_accounts
           SET sent_today = sent_today + 1,
               sent_total = sent_total + 1,
               last_sent_at = NOW(),
               updated_at = NOW()
           WHERE id = $1""",
        account_id,
    )


async def reset_daily_counters() -> int:
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE sender_accounts SET sent_today = 0, updated_at = NOW()"
    )
    # result is like "UPDATE N"
    return int(result.split()[-1]) if result else 0


# --- Warmup Log (NEW) ---

async def log_warmup_action(
    account_id: int, action: str, result: str | None = None, details: dict | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO warmup_log (account_id, action, result, details)
           VALUES ($1, $2, $3, $4)""",
        account_id, action, result, json.dumps(details) if details else None,
    )


# --- Reply Inbox (NEW) ---

async def save_reply(
    from_email: str, to_account: str, subject: str | None, body: str | None,
    message_id: str | None = None, lead_id: str | None = None,
    is_auto_reply: bool = False, is_bounce: bool = False, is_unsubscribe: bool = False,
) -> dict | None:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """INSERT INTO reply_inbox
               (from_email, to_account, subject, body, lead_id, message_id,
                is_auto_reply, is_bounce, is_unsubscribe)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (message_id) DO NOTHING
               RETURNING *""",
            from_email, to_account, subject, body, lead_id, message_id,
            is_auto_reply, is_bounce, is_unsubscribe,
        )
        return _row_to_dict(row) if row else None
    except asyncpg.UniqueViolationError:
        return None


async def get_replies(limit: int = 50, only_real: bool = True) -> list[dict]:
    pool = await get_pool()
    query = "SELECT * FROM reply_inbox"
    if only_real:
        query += " WHERE is_auto_reply = FALSE AND is_bounce = FALSE"
    query += " ORDER BY received_at DESC LIMIT $1"
    rows = await pool.fetch(query, limit)
    return [_row_to_dict(r) for r in rows]


# --- Crawler Runs (NEW) ---

async def start_crawler_run(crawler_name: str, config: dict | None = None) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO crawler_runs (crawler_name, config)
           VALUES ($1, $2) RETURNING id""",
        crawler_name, json.dumps(config) if config else None,
    )
    return row["id"]


async def finish_crawler_run(
    run_id: int, leads_found: int = 0, error_message: str | None = None,
) -> None:
    pool = await get_pool()
    status = "failed" if error_message else "completed"
    await pool.execute(
        """UPDATE crawler_runs
           SET status = $1, leads_found = $2, error_message = $3, completed_at = NOW()
           WHERE id = $4""",
        status, leads_found, error_message, run_id,
    )
