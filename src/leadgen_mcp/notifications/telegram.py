"""Telegram notification sender for leads.

Sends detailed per-lead cards + cycle summaries to a Telegram group.
Includes queue with retry mechanism for rate limit handling.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

from ..config import settings

logger = logging.getLogger("leadgen.notifications.telegram")

TELEGRAM_API = "https://api.telegram.org"

# Telegram rate limit: ~30 messages/second for groups, but we'll be conservative
MAX_MESSAGES_PER_SECOND = 1.5
MIN_DELAY_BETWEEN_MESSAGES = 1.0 / MAX_MESSAGES_PER_SECOND

PLATFORM_EMOJI = {
    "hackernews": "\U0001f4f0",
    "reddit": "\U0001f916",
    "reddit_live": "\U0001f916",
    "producthunt": "\U0001f680",
    "indiehackers": "\U0001f4a1",
    "upwork": "\U0001f4bc",
    "clutch": "\u2b50",
    "linkedin": "\U0001f465",
    "wellfound": "\U0001f331",
    "crunchbase": "\U0001f4b0",
    "github": "\U0001f431",
    "github_projects": "\U0001f431",
    "twitter": "\U0001f426",
    "google_maps": "\U0001f4cd",
    "goodfirms": "\U0001f3c6",
    "g2": "\U0001f4ca",
    "quora": "\u2753",
    "system": "\u2699\ufe0f",
    "ct_log": "\U0001f510",           # lock
    "company_registry": "\U0001f3db",  # classical building
    "yellowpages": "\U0001f4d2",       # ledger
    "accessibility_scanner": "\u267f",  # wheelchair
    "broken_sites": "\U0001f6a7",      # construction
    "tech_debt": "\U0001f9f1",         # brick
    "nrd": "\U0001f195",              # NEW
    "new_domain": "\U0001f195",
    "reply": "\U0001f4e9",            # envelope with arrow
    "gov_tenders": "\U0001f3db\ufe0f",  # classical building (government)
    "private_tenders": "\U0001f4dc",    # scroll (RFP/contract)
}

VERTICAL_EMOJI = {
    "hostingduty": "\U0001f5a5\ufe0f",    # desktop
    "chandorkar": "\U0001f4bb",           # laptop
    "nubo": "\U0001f4e8",                # incoming envelope
    "vikasit": "\U0001f916",             # robot
    "setara": "\u26d3\ufe0f",            # chains
    "staff_aug": "\U0001f465",           # people
}

VERTICAL_LABEL = {
    "hostingduty": "HostingDuty",
    "chandorkar": "Chandorkar Tech",
    "nubo": "Nubo Email",
    "vikasit": "Vikasit AI",
    "setara": "Setara Blockchain",
    "staff_aug": "Staff Aug",
}

SCORE_TIER = {
    "hot": "\U0001f525",     # fire
    "warm": "\U0001f7e1",    # yellow circle
    "cold": "\U0001f535",    # blue circle
}


def _is_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_group_id)


def _score_tier(score):
    if score is None:
        return "unscored", "\u2754"
    score = float(score)
    if score >= 70:
        return "hot", SCORE_TIER["hot"]
    if score >= 40:
        return "warm", SCORE_TIER["warm"]
    return "cold", SCORE_TIER["cold"]


def _format_lead_card(lead: dict, lead_number: int = 0) -> str:
    """Format a detailed lead card for Telegram."""
    source = lead.get("source_platform", lead.get("source", "unknown"))
    emoji = PLATFORM_EMOJI.get(source, "\U0001f4cb")

    company = lead.get("company_name", lead.get("title", "Unknown"))
    domain = lead.get("domain", "")
    source_url = lead.get("source_url", lead.get("url", lead.get("raw_url", "")))
    description = lead.get("description", "")
    budget = lead.get("budget_estimate")
    score = lead.get("_score_total", lead.get("score"))
    tier, tier_emoji = _score_tier(score)

    # Parse JSON fields
    def _parse_list(val):
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return []
        return []

    signals = _parse_list(lead.get("signals", []))
    contacts = _parse_list(lead.get("_contacts", lead.get("contacts", [])))
    emails = _parse_list(lead.get("_emails", lead.get("emails", [])))
    verticals = _parse_list(lead.get("_verticals", lead.get("vertical_match", [])))

    ai_assessment = lead.get("_ai_assessment", lead.get("ai_assessment", ""))
    email_status = lead.get("_email_status", lead.get("email_status", ""))
    email_subject = lead.get("_email_subject", lead.get("email_subject", ""))
    email_body = lead.get("_email_body", lead.get("email_body", ""))
    email_to = lead.get("_email_to", lead.get("email_to", ""))
    email_from = lead.get("_email_from", lead.get("email_from", ""))
    tech_stack = lead.get("_tech_stack", lead.get("tech_stack", ""))
    security_issues = lead.get("_security_issues", lead.get("security_issues", ""))

    # Truncate long fields
    if len(description) > 300:
        description = description[:297] + "..."
    if ai_assessment and len(ai_assessment) > 200:
        ai_assessment = ai_assessment[:197] + "..."

    # ── Build card ──
    header = f"#{lead_number}" if lead_number else ""
    lines = [
        f"{tier_emoji} {emoji} LEAD {header} — {source.upper()}",
        f"{'━' * 30}",
        f"\U0001f3e2 {company}",
    ]

    if description:
        lines.append(f"\U0001f4dd {description}")

    lines.append("")

    # Verticals
    if verticals:
        v_parts = []
        for v in verticals:
            v_emoji = VERTICAL_EMOJI.get(v, "\U0001f4cb")
            v_label = VERTICAL_LABEL.get(v, v)
            v_parts.append(f"{v_emoji} {v_label}")
        lines.append(f"\U0001f3af Pitch: {' | '.join(v_parts)}")

    if budget:
        lines.append(f"\U0001f4b0 Budget: ${budget:,}")

    if score is not None:
        lines.append(f"\U0001f4ca Score: {score}/100 ({tier.upper()})")

    if signals:
        sig_str = " | ".join(str(s) for s in signals[:6])
        lines.append(f"\U0001f6a8 Signals: {sig_str}")

    if domain:
        lines.append(f"\U0001f310 {domain}")

    if source_url:
        lines.append(f"\U0001f517 {source_url}")

    # Contacts & emails
    if contacts:
        lines.append("")
        lines.append("\U0001f464 Contacts:")
        for c in contacts[:3]:
            if isinstance(c, dict):
                name = c.get("name", "")
                title = c.get("title", "")
                c_email = c.get("email", "")
                lines.append(f"  \u2022 {name} ({title}) {c_email}")
            else:
                lines.append(f"  \u2022 {c}")

    if emails and not contacts:
        lines.append("")
        lines.append(f"\U0001f4e7 Emails: {', '.join(str(e) for e in emails[:5])}")

    # Tech & security
    if tech_stack:
        lines.append(f"\U0001f527 Tech: {tech_stack}")
    if security_issues:
        lines.append(f"\u26a0\ufe0f Security: {security_issues}")

    # AI assessment
    if ai_assessment:
        lines.append("")
        lines.append(f"\U0001f916 AI: {ai_assessment}")

    # ── Email section ──
    if email_status:
        lines.append("")
        lines.append(f"{'━' * 30}")

        status_emoji = {
            "sent": "\u2705",
            "pending": "\u23f3",
            "failed": "\u274c",
            "not_sent": "\u2796",
            "dry_run": "\U0001f6ab",
            "replied": "\U0001f4e9",
        }.get(email_status, "\u2753")

        lines.append(f"{status_emoji} EMAIL: {email_status.upper()}")

        if email_from:
            lines.append(f"\U0001f4e4 From: {email_from}")
        if email_to:
            lines.append(f"\U0001f4e5 To: {email_to}")
        if email_subject:
            lines.append(f"\U0001f4cc Subject: {email_subject}")

        if email_body:
            # Truncate body but show enough to be useful
            body_preview = email_body.strip()
            if len(body_preview) > 800:
                body_preview = body_preview[:797] + "..."
            lines.append("")
            lines.append(f"\U0001f4dd Email Body:")
            lines.append(f"{'─' * 25}")
            lines.append(body_preview)
            lines.append(f"{'─' * 25}")

    return "\n".join(lines)


def _format_cycle_summary(stats: dict) -> str:
    """Format pipeline cycle summary."""
    discovery = stats.get("discovery", {})
    scoring = stats.get("scoring", {})
    email_info = stats.get("email", {})
    duration = stats.get("duration_seconds", 0)

    lines = [
        "\U0001f4ca CYCLE COMPLETE",
        f"{'━' * 30}",
        "",
        f"Leads: {discovery.get('total', 0)} discovered",
    ]

    per_platform = discovery.get("per_platform", {})
    for plat, count in sorted(per_platform.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            e = PLATFORM_EMOJI.get(plat, "")
            lines.append(f"  {e} {plat}: {count}")

    errors = discovery.get("errors", {})
    for plat, err in errors.items():
        lines.append(f"  \u274c {plat}: FAILED")

    hot = scoring.get("hot", 0)
    warm = scoring.get("warm", 0)
    cold = scoring.get("cold", 0)
    lines.append(f"\n\U0001f525 Hot: {hot} | \U0001f7e1 Warm: {warm} | \U0001f535 Cold: {cold}")

    gen = email_info.get("generated", 0)
    sent = email_info.get("sent", 0)
    if email_info.get("dry_run"):
        lines.append(f"\U0001f4e7 Emails: {gen} generated (DRY RUN)")
    else:
        lines.append(f"\U0001f4e7 Emails: {sent}/{gen} sent")

    lines.append(f"\n\u23f1 Duration: {duration:.0f}s")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Message Queue with retry
# ---------------------------------------------------------------------------

@dataclass
class _QueuedMessage:
    text: str
    retries: int = 0
    max_retries: int = 5


class TelegramQueue:
    """Rate-limited message queue with retry for Telegram."""

    def __init__(self):
        self._queue: deque[_QueuedMessage] = deque()
        self._last_sent: float = 0
        self._running = False
        self._task: asyncio.Task | None = None

    def enqueue(self, text: str):
        self._queue.append(_QueuedMessage(text=text))
        if not self._running:
            self._task = asyncio.ensure_future(self._process_queue())

    async def _send(self, text: str) -> tuple[bool, int]:
        """Send message. Returns (success, retry_after_seconds)."""
        url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": settings.telegram_group_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(url, json=payload)
                data = resp.json()

                if resp.status_code == 200 and data.get("ok"):
                    return True, 0

                if resp.status_code == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 30)
                    logger.warning("Telegram rate limited, retry after %ds", retry_after)
                    return False, retry_after

                logger.warning("Telegram error: %s", data.get("description", resp.status_code))
                return False, 5

        except Exception as e:
            logger.warning("Telegram request error: %s", e)
            return False, 10

    async def _process_queue(self):
        self._running = True
        try:
            while self._queue:
                msg = self._queue[0]

                # Rate limit: wait between messages
                elapsed = time.monotonic() - self._last_sent
                if elapsed < MIN_DELAY_BETWEEN_MESSAGES:
                    await asyncio.sleep(MIN_DELAY_BETWEEN_MESSAGES - elapsed)

                success, retry_after = await self._send(msg.text)

                if success:
                    self._queue.popleft()
                    self._last_sent = time.monotonic()
                else:
                    msg.retries += 1
                    if msg.retries >= msg.max_retries:
                        logger.error("Telegram message dropped after %d retries", msg.max_retries)
                        self._queue.popleft()
                    else:
                        logger.info("Telegram retry %d/%d in %ds", msg.retries, msg.max_retries, retry_after)
                        await asyncio.sleep(retry_after)
        finally:
            self._running = False

    async def flush(self):
        """Wait for all queued messages to be sent."""
        if self._task and not self._task.done():
            await self._task


# Global queue instance
_queue = TelegramQueue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_lead_notification(lead: dict, lead_number: int = 0) -> dict:
    """Queue a detailed lead card notification."""
    if not _is_configured():
        return {"success": False, "error": "Telegram not configured"}

    text = _format_lead_card(lead, lead_number)
    _queue.enqueue(text)
    return {"success": True, "queued": True}


async def send_cycle_summary(stats_dict: dict) -> dict:
    """Queue a cycle summary notification."""
    if not _is_configured():
        return {"success": False, "error": "Telegram not configured"}

    text = _format_cycle_summary(stats_dict)
    _queue.enqueue(text)
    return {"success": True, "queued": True}


async def flush_queue():
    """Wait for all queued Telegram messages to be sent."""
    await _queue.flush()
