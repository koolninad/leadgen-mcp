"""Telegram notification sender for new leads.

Sends formatted lead alerts to a Telegram group/channel via the Bot API.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_GROUP_ID in settings.
"""

import logging

import httpx

from ..config import settings

logger = logging.getLogger("leadgen.notifications.telegram")

TELEGRAM_API = "https://api.telegram.org"

# Platform emoji mapping
PLATFORM_EMOJI = {
    "hackernews": "\U0001f4f0",       # newspaper
    "reddit": "\U0001f916",           # robot
    "reddit_live": "\U0001f916",
    "producthunt": "\U0001f680",      # rocket
    "indiehackers": "\U0001f4a1",     # lightbulb
    "upwork": "\U0001f4bc",           # briefcase
    "clutch": "\u2b50",               # star
    "linkedin": "\U0001f465",         # people
    "wellfound": "\U0001f331",        # seedling
    "crunchbase": "\U0001f4b0",       # money bag
    "github": "\U0001f431",           # cat (octocat)
    "github_projects": "\U0001f431",
    "twitter": "\U0001f426",          # bird
    "google_maps": "\U0001f4cd",      # pin
    "goodfirms": "\U0001f3c6",        # trophy
    "g2": "\U0001f4ca",              # chart
    "quora": "\u2753",                # question mark
    "domain_intel_whois": "\U0001f50d",
    "domain_intel_dns": "\U0001f310",
    "domain_intel_ssl": "\U0001f512",
    "domain_intel_http": "\U0001f6a6",
    "domain_intel_full": "\U0001f50e",
}


def _is_configured() -> bool:
    """Check if Telegram notifications are configured."""
    return bool(settings.telegram_bot_token and settings.telegram_group_id)


def _format_lead_message(lead: dict) -> str:
    """Format a lead dict into a Telegram-friendly message (MarkdownV2-safe plain text)."""
    source = lead.get("source_platform", lead.get("source", "unknown"))
    emoji = PLATFORM_EMOJI.get(source, "\U0001f4cb")

    company = lead.get("company_name", "Unknown")
    domain = lead.get("domain", "")
    raw_url = lead.get("raw_url", lead.get("source_url", ""))
    description = lead.get("description", "")
    budget = lead.get("budget_estimate")
    score = lead.get("_score_total", lead.get("score"))
    tier = lead.get("_score_tier", lead.get("tier", ""))
    ai_assessment = lead.get("_ai_assessment", "")

    # Signals
    signals = lead.get("signals", [])
    if isinstance(signals, str):
        import json
        try:
            signals = json.loads(signals)
        except Exception:
            signals = []

    # Truncate description
    if len(description) > 200:
        description = description[:197] + "..."

    lines = [
        f"{emoji} NEW LEAD from {source.upper()}",
        "",
        f"Company: {company}",
    ]

    if description:
        lines.append(f"Details: {description}")

    if budget:
        lines.append(f"Budget: ${budget:,}")

    if signals:
        signals_str = ", ".join(str(s) for s in signals[:6])
        lines.append(f"Signals: {signals_str}")

    if domain:
        lines.append(f"Domain: {domain}")

    if raw_url:
        lines.append(f"URL: {raw_url}")

    if score is not None:
        tier_label = f" ({tier})" if tier else ""
        lines.append(f"Score: {score}{tier_label}")

    if ai_assessment:
        assessment = ai_assessment if len(ai_assessment) <= 150 else ai_assessment[:147] + "..."
        lines.append(f"AI Assessment: {assessment}")

    return "\n".join(lines)


async def send_lead_notification(lead: dict) -> dict:
    """Send a lead notification to the configured Telegram group.

    Args:
        lead: Lead dict with keys like company_name, domain, signals, etc.

    Returns:
        dict with 'success' bool and optional 'error' or 'message_id'.
    """
    if not _is_configured():
        return {"success": False, "error": "Telegram not configured"}

    text = _format_lead_message(lead)
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
                msg_id = data.get("result", {}).get("message_id")
                logger.debug("Telegram notification sent (msg_id=%s)", msg_id)
                return {"success": True, "message_id": msg_id}
            else:
                error = data.get("description", f"HTTP {resp.status_code}")
                logger.warning("Telegram send failed: %s", error)
                return {"success": False, "error": error}

    except httpx.RequestError as e:
        logger.warning("Telegram request error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.warning("Telegram unexpected error: %s", e)
        return {"success": False, "error": str(e)}


async def send_cycle_summary(stats_dict: dict) -> dict:
    """Send a pipeline cycle summary to Telegram.

    Args:
        stats_dict: The CycleStats.to_dict() output.

    Returns:
        dict with 'success' bool.
    """
    if not _is_configured():
        return {"success": False, "error": "Telegram not configured"}

    discovery = stats_dict.get("discovery", {})
    scoring = stats_dict.get("scoring", {})
    email_info = stats_dict.get("email", {})

    lines = [
        "\U0001f4ca PIPELINE CYCLE COMPLETE",
        "",
        f"Leads discovered: {discovery.get('total', 0)}",
    ]

    per_platform = discovery.get("per_platform", {})
    for plat, count in sorted(per_platform.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            lines.append(f"  {plat}: {count}")

    errors = discovery.get("errors", {})
    if errors:
        for plat, err in errors.items():
            lines.append(f"  {plat}: FAILED")

    lines.append(f"\nScored: {scoring.get('leads_scored', 0)}")
    lines.append(f"  Hot: {scoring.get('hot', 0)} / Warm: {scoring.get('warm', 0)} / Cold: {scoring.get('cold', 0)}")

    lines.append(f"\nEmails: {email_info.get('generated', 0)} generated, {email_info.get('sent', 0)} sent")
    if email_info.get("dry_run"):
        lines.append("  (DRY RUN)")

    lines.append(f"\nDuration: {stats_dict.get('duration_seconds', 0):.1f}s")

    text = "\n".join(lines)
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
                return {"success": True}
            return {"success": False, "error": data.get("description", "")}
    except Exception as e:
        logger.warning("Telegram cycle summary failed: %s", e)
        return {"success": False, "error": str(e)}
