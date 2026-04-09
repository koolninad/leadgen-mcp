"""Database CRUD operations."""

import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from ..config import settings
from .models import SCHEMA_SQL


_db: aiosqlite.Connection | None = None


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        from pathlib import Path
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(settings.db_path)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.executescript(SCHEMA_SQL)
        await _db.commit()
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


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
    db = await get_db()

    # Check for existing lead by domain
    if domain:
        row = await db.execute_fetchall(
            "SELECT id FROM leads WHERE domain = ?", (domain,)
        )
        if row:
            lead_id = row[0][0]
            await db.execute(
                """UPDATE leads SET company_name=COALESCE(?,company_name),
                   source_platform=COALESCE(?,source_platform),
                   source_url=COALESCE(?,source_url),
                   description=COALESCE(?,description),
                   budget_estimate=COALESCE(?,budget_estimate),
                   signals=COALESCE(?,signals),
                   raw_data=COALESCE(?,raw_data),
                   updated_at=? WHERE id=?""",
                (
                    company_name, source_platform, source_url, description,
                    budget_estimate, json.dumps(signals) if signals else None,
                    json.dumps(raw_data) if raw_data else None, _now(), lead_id,
                ),
            )
            await db.commit()
            return await get_lead(lead_id)

    lead_id = _uid()
    await db.execute(
        """INSERT INTO leads (id, domain, company_name, source_platform, source_url,
           description, budget_estimate, signals, raw_data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            lead_id, domain, company_name, source_platform, source_url,
            description, budget_estimate,
            json.dumps(signals or []), json.dumps(raw_data or {}),
            _now(), _now(),
        ),
    )
    await db.commit()
    return await get_lead(lead_id)


async def get_lead(lead_id: str) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not rows:
        return None
    return dict(rows[0])


async def query_leads(
    min_score: float = 0,
    source_platform: str | None = None,
    domain_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    db = await get_db()
    query = """
        SELECT l.*, COALESCE(ls.total_score, 0) as score
        FROM leads l
        LEFT JOIN lead_scores ls ON l.id = ls.lead_id
        WHERE COALESCE(ls.total_score, 0) >= ?
    """
    params: list = [min_score]

    if source_platform:
        query += " AND l.source_platform = ?"
        params.append(source_platform)
    if domain_contains:
        query += " AND l.domain LIKE ?"
        params.append(f"%{domain_contains}%")

    query += " ORDER BY score DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


# --- Scan Results ---

async def save_scan_result(
    lead_id: str, scan_type: str, result: dict, severity: str = "info"
) -> dict:
    db = await get_db()
    scan_id = _uid()
    await db.execute(
        """INSERT INTO scan_results (id, lead_id, scan_type, result, severity, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (scan_id, lead_id, scan_type, json.dumps(result), severity, _now()),
    )
    await db.commit()
    return {"id": scan_id, "lead_id": lead_id, "scan_type": scan_type, "severity": severity}


async def get_scan_results(lead_id: str) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM scan_results WHERE lead_id = ? ORDER BY scanned_at DESC",
        (lead_id,),
    )
    results = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d["result"])
        results.append(d)
    return results


# --- Contacts ---

async def save_contact(
    lead_id: str, name: str | None = None, title: str | None = None,
    email: str | None = None, email_verified: bool = False,
    phone: str | None = None, source: str = "website",
) -> dict:
    db = await get_db()
    contact_id = _uid()
    await db.execute(
        """INSERT INTO contacts (id, lead_id, name, title, email, email_verified, phone, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (contact_id, lead_id, name, title, email, int(email_verified), phone, source, _now()),
    )
    await db.commit()
    return {"id": contact_id, "lead_id": lead_id, "email": email, "name": name}


async def get_contacts(lead_id: str) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM contacts WHERE lead_id = ?", (lead_id,)
    )
    return [dict(r) for r in rows]


# --- Lead Scores ---

async def save_score(lead_id: str, scores: dict) -> dict:
    db = await get_db()
    score_id = _uid()
    total = sum(scores.values())
    await db.execute(
        """INSERT OR REPLACE INTO lead_scores
           (id, lead_id, tech_score, opportunity_score, budget_score,
            engagement_score, contact_score, total_score, scored_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            score_id, lead_id,
            scores.get("tech", 0), scores.get("opportunity", 0),
            scores.get("budget", 0), scores.get("engagement", 0),
            scores.get("contact", 0), total, _now(),
        ),
    )
    await db.commit()
    return {"lead_id": lead_id, "total_score": total, **scores}


# --- Campaigns ---

async def create_campaign(name: str, template: str, schedule: dict) -> dict:
    db = await get_db()
    campaign_id = _uid()
    await db.execute(
        """INSERT INTO campaigns (id, name, status, template, schedule, created_at, updated_at)
           VALUES (?, ?, 'draft', ?, ?, ?, ?)""",
        (campaign_id, name, template, json.dumps(schedule), _now(), _now()),
    )
    await db.commit()
    return {"id": campaign_id, "name": name, "status": "draft"}


async def update_campaign_status(campaign_id: str, status: str) -> dict:
    db = await get_db()
    await db.execute(
        "UPDATE campaigns SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), campaign_id),
    )
    await db.commit()
    return {"id": campaign_id, "status": status}


async def add_leads_to_campaign(campaign_id: str, lead_ids: list[str]) -> int:
    db = await get_db()
    count = 0
    for lid in lead_ids:
        cl_id = _uid()
        await db.execute(
            """INSERT INTO campaign_leads (id, campaign_id, lead_id, sequence_step, status)
               VALUES (?, ?, ?, 0, 'pending')""",
            (cl_id, campaign_id, lid),
        )
        count += 1
    await db.commit()
    return count


async def save_email_sent(
    campaign_lead_id: str | None, to_email: str, subject: str,
    body: str, tracking_id: str,
) -> dict:
    db = await get_db()
    email_id = _uid()
    await db.execute(
        """INSERT INTO emails_sent
           (id, campaign_lead_id, to_email, subject, body, tracking_id, sent_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (email_id, campaign_lead_id, to_email, subject, body, tracking_id, _now()),
    )
    await db.commit()
    return {"id": email_id, "tracking_id": tracking_id, "to": to_email}


async def get_campaign_stats(campaign_id: str) -> dict:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN cl.status = 'sent' THEN 1 ELSE 0 END) as sent,
            SUM(CASE WHEN cl.status = 'opened' THEN 1 ELSE 0 END) as opened,
            SUM(CASE WHEN cl.status = 'clicked' THEN 1 ELSE 0 END) as clicked,
            SUM(CASE WHEN cl.status = 'replied' THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN cl.status = 'bounced' THEN 1 ELSE 0 END) as bounced
        FROM campaign_leads cl WHERE cl.campaign_id = ?""",
        (campaign_id,),
    )
    return dict(rows[0]) if rows else {}


async def get_email_analytics(days: int = 30) -> dict:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT
            COUNT(*) as total_sent,
            SUM(CASE WHEN opened_at IS NOT NULL THEN 1 ELSE 0 END) as total_opened,
            SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) as total_clicked,
            SUM(bounced) as total_bounced
        FROM emails_sent
        WHERE sent_at >= datetime('now', ?)""",
        (f"-{days} days",),
    )
    return dict(rows[0]) if rows else {}
