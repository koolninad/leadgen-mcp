"""PostgreSQL-based job queue using FOR UPDATE SKIP LOCKED.

No Redis needed. PG handles concurrency, retries, and dead letter natively.

Job types:
- email_generate: Generate personalized email via Gemma4 (slow, 10-30s)
- email_send: Send a generated email via SMTP (fast, 1-3s)
- enrich: Enrich a lead (find emails, contacts, company intel)
- score: Score and assign verticals to a lead

Flow:
  Crawlers → enqueue('enrich', lead_id) → Worker picks up → enqueue('score') →
  Worker picks up → enqueue('email_generate') → Worker picks up (Gemma4, slow) →
  enqueue('email_send') → Worker picks up → send via rotation → Telegram
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from .config import settings
from .db.pg_repository import get_pool

logger = logging.getLogger("leadgen.queue")

WORKER_ID = f"worker-{os.getpid()}"


# ── Queue Operations ──

async def enqueue(
    job_type: str,
    lead_id: str | None = None,
    payload: dict | None = None,
    priority: int = 0,
    delay_seconds: int = 0,
) -> int:
    """Add a job to the queue. Returns job ID."""
    pool = await get_pool()
    scheduled_at = datetime.now(timezone.utc)
    if delay_seconds:
        from datetime import timedelta
        scheduled_at += timedelta(seconds=delay_seconds)

    row = await pool.fetchrow(
        """INSERT INTO job_queue (job_type, lead_id, payload, priority, scheduled_at)
           VALUES ($1, $2, $3, $4, $5) RETURNING id""",
        job_type, lead_id, json.dumps(payload or {}), priority, scheduled_at,
    )
    return row["id"]


async def enqueue_batch(jobs: list[dict]) -> list[int]:
    """Enqueue multiple jobs at once. Each dict: {job_type, lead_id, payload, priority}."""
    pool = await get_pool()
    ids = []
    now = datetime.now(timezone.utc)
    for job in jobs:
        row = await pool.fetchrow(
            """INSERT INTO job_queue (job_type, lead_id, payload, priority, scheduled_at)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            job["job_type"], job.get("lead_id"), json.dumps(job.get("payload", {})),
            job.get("priority", 0), now,
        )
        ids.append(row["id"])
    return ids


async def claim_job(job_types: list[str] | None = None) -> dict | None:
    """Claim the next available job using SKIP LOCKED. Returns job dict or None."""
    pool = await get_pool()

    type_filter = ""
    params = [WORKER_ID, datetime.now(timezone.utc)]
    idx = 3

    if job_types:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(job_types)))
        type_filter = f"AND job_type IN ({placeholders})"
        params.extend(job_types)

    row = await pool.fetchrow(f"""
        UPDATE job_queue
        SET status = 'processing', locked_by = $1, locked_at = $2, attempts = attempts + 1
        WHERE id = (
            SELECT id FROM job_queue
            WHERE status IN ('pending', 'retry')
              AND scheduled_at <= NOW()
              AND attempts < max_attempts
              {type_filter}
            ORDER BY priority DESC, scheduled_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    """, *params)

    if row:
        d = dict(row)
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
    return None


async def complete_job(job_id: int, result: dict | None = None) -> None:
    """Mark a job as completed."""
    pool = await get_pool()
    await pool.execute(
        """UPDATE job_queue
           SET status = 'completed', result = $1, completed_at = NOW(), locked_by = NULL
           WHERE id = $2""",
        json.dumps(result or {}), job_id,
    )


async def fail_job(job_id: int, error: str) -> None:
    """Mark a job as failed. Will retry if attempts < max_attempts."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT attempts, max_attempts FROM job_queue WHERE id = $1", job_id
    )
    if row and row["attempts"] < row["max_attempts"]:
        new_status = "retry"
    else:
        new_status = "failed"

    await pool.execute(
        """UPDATE job_queue
           SET status = $1, error_message = $2, locked_by = NULL, locked_at = NULL
           WHERE id = $3""",
        new_status, error, job_id,
    )


async def queue_stats() -> dict:
    """Get queue statistics."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT status, job_type, COUNT(*) as count
           FROM job_queue
           GROUP BY status, job_type
           ORDER BY status, job_type"""
    )
    stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "retry": 0}
    by_type = {}
    for r in rows:
        stats[r["status"]] = stats.get(r["status"], 0) + r["count"]
        key = f"{r['job_type']}_{r['status']}"
        by_type[key] = r["count"]

    stats["by_type"] = by_type
    return stats


async def cleanup_stale_jobs(timeout_minutes: int = 30) -> int:
    """Reset jobs stuck in 'processing' for too long (worker crashed)."""
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE job_queue
           SET status = 'retry', locked_by = NULL, locked_at = NULL
           WHERE status = 'processing'
             AND locked_at < NOW() - INTERVAL '%s minutes'""" % timeout_minutes,
    )
    count = int(result.split()[-1]) if result else 0
    if count:
        logger.info("Reset %d stale jobs", count)
    return count


async def purge_completed(days: int = 7) -> int:
    """Delete completed jobs older than N days."""
    pool = await get_pool()
    result = await pool.execute(
        """DELETE FROM job_queue
           WHERE status = 'completed'
             AND completed_at < NOW() - INTERVAL '%s days'""" % days,
    )
    count = int(result.split()[-1]) if result else 0
    return count


# ── Worker ──

class QueueWorker:
    """Async worker that processes jobs from the queue.

    Handles job routing to the right handler function.
    Runs continuously, polling for new jobs.
    """

    def __init__(self, job_types: list[str] | None = None, poll_interval: float = 2.0):
        self._job_types = job_types
        self._poll_interval = poll_interval
        self._running = False
        self._processed = 0
        self._handlers: dict[str, callable] = {}

    def register_handler(self, job_type: str, handler: callable):
        """Register a handler function for a job type."""
        self._handlers[job_type] = handler

    async def run_forever(self):
        """Main worker loop — claim and process jobs."""
        self._running = True
        logger.info("Queue worker starting (types=%s, poll=%.1fs)",
                     self._job_types or "all", self._poll_interval)

        while self._running:
            try:
                # Cleanup stale jobs periodically
                if self._processed % 50 == 0:
                    await cleanup_stale_jobs()

                job = await claim_job(self._job_types)
                if not job:
                    await asyncio.sleep(self._poll_interval)
                    continue

                job_type = job["job_type"]
                job_id = job["id"]
                lead_id = job.get("lead_id")

                handler = self._handlers.get(job_type)
                if not handler:
                    await fail_job(job_id, f"No handler for job type: {job_type}")
                    continue

                logger.info("Processing job %d: %s (lead=%s, attempt=%d)",
                            job_id, job_type, lead_id, job["attempts"])

                try:
                    t0 = time.monotonic()
                    result = await handler(job)
                    elapsed = time.monotonic() - t0

                    await complete_job(job_id, result)
                    self._processed += 1
                    logger.info("Job %d completed in %.1fs", job_id, elapsed)

                except Exception as e:
                    logger.error("Job %d failed: %s", job_id, e)
                    await fail_job(job_id, str(e))

            except Exception as e:
                logger.error("Worker error: %s", e, exc_info=True)
                await asyncio.sleep(5)

        logger.info("Queue worker stopped after %d jobs", self._processed)

    def stop(self):
        self._running = False


# ── Default Job Handlers ──

async def handle_enrich(job: dict) -> dict:
    """Enrich a lead: find emails, contacts, company intel."""
    lead_id = job["lead_id"]
    from .db.pg_repository import get_lead, save_contact, save_scan_result
    from .enrichment.email_finder import find_emails_for_domain
    from .enrichment.contacts import find_decision_makers
    from .enrichment.company_intel import get_company_intel

    lead = await get_lead(lead_id)
    if not lead or not lead.get("domain"):
        return {"skipped": "no domain"}

    domain = lead["domain"]
    emails_found = []
    contacts_found = []

    try:
        email_results = await find_emails_for_domain(domain, lead.get("company_name"))
        emails_found = email_results.get("emails_found", [])
        for email in emails_found:
            await save_contact(lead_id, email=email, source="website_scrape")
    except Exception as e:
        logger.debug("Email finder failed for %s: %s", domain, e)

    try:
        contacts = await find_decision_makers(domain)
        contacts_found = contacts
        for c in contacts:
            await save_contact(lead_id, name=c.get("name"), title=c.get("title"), source="website")
    except Exception:
        pass

    try:
        intel = await get_company_intel(domain)
        await save_scan_result(lead_id, "company_intel", intel, "info")
    except Exception:
        pass

    # Queue scoring job
    await enqueue("score", lead_id, priority=5)

    return {"emails": len(emails_found), "contacts": len(contacts_found)}


async def handle_score(job: dict) -> dict:
    """Score a lead and assign verticals."""
    lead_id = job["lead_id"]
    from .enrichment.scoring import score_lead
    from .enrichment.vertical import assign_vertical
    from .db.pg_repository import get_lead

    result = await score_lead(lead_id)
    total = result.get("total_score", 0)

    lead = await get_lead(lead_id)
    signals = lead.get("signals", []) if lead else []
    if isinstance(signals, str):
        try:
            signals = json.loads(signals)
        except (json.JSONDecodeError, TypeError):
            signals = []

    verticals = assign_vertical(
        signals=signals,
        description=lead.get("description", "") if lead else "",
        source_platform=lead.get("source_platform", "") if lead else "",
    )

    # Save verticals
    pool = await get_pool()
    await pool.execute(
        "UPDATE leads SET vertical_match = $1 WHERE id = $2",
        verticals, lead_id,
    )

    # Queue email generation if score is high enough
    min_score = job.get("payload", {}).get("min_score", 40)
    if total >= min_score:
        await enqueue("email_generate", lead_id, payload={"verticals": verticals}, priority=10)

    return {"score": total, "verticals": verticals, "queued_email": total >= min_score}


async def handle_email_generate(job: dict) -> dict:
    """Generate a personalized email via Gemma4/Ollama. This is the SLOW job."""
    lead_id = job["lead_id"]
    payload = job.get("payload", {})
    verticals = payload.get("verticals", ["chandorkar"])
    template = payload.get("template", "tech_audit")

    from .ai.email_generator import generate_outreach_email
    from .db.pg_repository import get_lead, get_contacts

    lead = await get_lead(lead_id)
    if not lead:
        return {"skipped": "lead not found"}

    # Find recipient email
    contacts = await get_contacts(lead_id)
    emails = [c["email"] for c in contacts if c.get("email")]
    if not emails:
        return {"skipped": "no email"}

    to_email = emails[0]

    # Generate via AI
    email_data = await generate_outreach_email(lead_id, template)
    if "error" in email_data:
        raise Exception(f"AI generation failed: {email_data['error']}")

    # Queue sending job
    await enqueue("email_send", lead_id, payload={
        "to_email": to_email,
        "subject": email_data["subject"],
        "body": email_data["body"],
        "verticals": verticals,
    }, priority=15)

    return {"subject": email_data["subject"], "to": to_email}


async def handle_email_send(job: dict) -> dict:
    """Send an email using sender rotation."""
    lead_id = job["lead_id"]
    payload = job.get("payload", {})
    to_email = payload["to_email"]
    subject = payload["subject"]
    body = payload["body"]
    verticals = payload.get("verticals", ["chandorkar"])

    from .email_sender.rotation import pick_sender, record_send
    from .email_sender.smtp import send_email, text_to_html
    from .notifications.telegram import send_lead_notification
    from .db.pg_repository import get_lead

    # Pick sender
    recipient_domain = to_email.split("@")[1] if "@" in to_email else None
    sender = await pick_sender(recipient_domain=recipient_domain, vertical=verticals[0] if verticals else None)

    if not sender:
        raise Exception("No active sender accounts available")

    # Send
    body_html = text_to_html(body)
    result = await send_email(
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        from_email=sender["email"],
        from_name=sender["display_name"],
        smtp_host=sender["smtp_host"],
        smtp_port=sender["smtp_port"],
        smtp_user=sender["smtp_user"],
        smtp_password=sender["smtp_password"],
        track=True,
    )

    if not result.get("success"):
        raise Exception(f"SMTP failed: {result.get('error')}")

    await record_send(sender["id"])

    # Send Telegram notification
    lead = await get_lead(lead_id)
    if lead:
        lead["_email_status"] = "sent"
        lead["_email_from"] = sender["email"]
        lead["_email_to"] = to_email
        lead["_email_subject"] = subject
        lead["_email_body"] = body
        lead["_verticals"] = verticals
        try:
            await send_lead_notification(lead)
        except Exception:
            pass

    return {"sent": True, "from": sender["email"], "to": to_email}


def create_default_worker() -> QueueWorker:
    """Create a worker with all default handlers registered."""
    worker = QueueWorker(poll_interval=2.0)
    worker.register_handler("enrich", handle_enrich)
    worker.register_handler("score", handle_score)
    worker.register_handler("email_generate", handle_email_generate)
    worker.register_handler("email_send", handle_email_send)
    return worker
