"""Tender Telegram notifier — sends structured cards + PDF to tender group."""

import io
import logging

import httpx

from ..config import settings
from .models import Tender, COMPANIES

logger = logging.getLogger("tenders.notifier")

TENDER_GROUP_ID = "-5135934153"
TELEGRAM_API = "https://api.telegram.org"


def _format_tender_card(tender: Tender) -> str:
    """Format a tender notification card."""
    company_key = tender.recommended_company or "ct_india"
    company = COMPANIES.get(company_key, COMPANIES["ct_india"])

    source_emoji = {
        "sam_gov": "\U0001f1fa\U0001f1f8",
        "uk_contracts": "\U0001f1ec\U0001f1e7",
        "cppp_india": "\U0001f1ee\U0001f1f3",
        "gem_india": "\U0001f1ee\U0001f1f3",
        "eu_ted": "\U0001f1ea\U0001f1fa",
        "world_bank": "\U0001f30d",
        "ungm": "\U0001f1fa\U0001f1f3",
    }.get(tender.source, "\U0001f3db\ufe0f")

    complexity_emoji = {
        "low": "\U0001f7e2",
        "medium": "\U0001f7e1",
        "high": "\U0001f534",
    }.get(tender.complexity, "\u26aa")

    lines = [
        f"\U0001f3db\ufe0f TENDER ALERT {source_emoji}",
        f"{'━' * 30}",
        f"\U0001f4cb {tender.title}",
        f"\U0001f3e2 {tender.organization}",
        f"\U0001f30d {tender.country}",
    ]

    if tender.technology:
        lines.append(f"\U0001f4bb Tech: {tender.technology}")

    if tender.amount:
        lines.append(f"\U0001f4b0 Amount: {tender.amount}")

    if tender.emd:
        lines.append(f"\U0001f4c4 EMD: {tender.emd}")

    if tender.deadline:
        lines.append(f"\U0001f4c5 Deadline: {tender.deadline}")

    lines.append(f"\U0001f517 {tender.source_url}")

    # AI Analysis section
    lines.append("")
    lines.append(f"{'━' * 30}")
    lines.append(f"\U0001f916 AI ANALYSIS")

    lines.append(f"\U0001f3e2 Recommended: {company['short']}")
    lines.append(f"{complexity_emoji} Complexity: {tender.complexity or 'Medium'}")
    lines.append(f"\U0001f4b0 Est. Cost: {tender.estimated_cost or 'TBD'}")
    lines.append(f"\u23f0 Est. Timeline: {tender.estimated_timeline or 'TBD'}")

    if tender.tech_stack_required:
        lines.append(f"\U0001f527 Stack: {', '.join(tender.tech_stack_required[:5])}")

    # Team
    if tender.team_composition:
        team_summary = ", ".join(f"{m['role']}×{m['count']}" for m in tender.team_composition[:4])
        lines.append(f"\U0001f465 Team: {team_summary}")

    # Risks
    if tender.risk_factors:
        lines.append(f"\u26a0\ufe0f Risks: {'; '.join(tender.risk_factors[:3])}")

    # Contact
    if tender.contact_name or tender.contact_email or tender.contact_phone:
        lines.append("")
        lines.append(f"\U0001f4de Contact:")
        if tender.contact_name:
            lines.append(f"  \u2022 {tender.contact_name}")
        if tender.contact_email:
            lines.append(f"  \u2022 {tender.contact_email}")
        if tender.contact_phone:
            lines.append(f"  \u2022 {tender.contact_phone}")

    # Documents
    if tender.documents_needed:
        lines.append("")
        lines.append(f"\U0001f4ce Attach {len(tender.documents_needed)} documents (see PDF)")

    lines.append("")
    lines.append(f"\U0001f4c4 Proposal PDF attached below \u2193")

    return "\n".join(lines)


async def send_tender_notification(tender: Tender, pdf_bytes: bytes | None = None) -> dict:
    """Send tender card + PDF to the Tender Telegram group."""
    if not settings.telegram_bot_token:
        return {"error": "Telegram not configured"}

    bot_token = settings.telegram_bot_token
    results = {"card": False, "pdf": False}

    # Send text card
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            text = _format_tender_card(tender)
            resp = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={
                    "chat_id": TENDER_GROUP_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                results["card"] = True
                logger.info("Tender card sent: %s", tender.title[:50])
            else:
                logger.warning("Tender card failed: %s", resp.text[:100])
    except Exception as e:
        logger.error("Telegram card error: %s", e)

    # Send PDF
    if pdf_bytes:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in tender.title[:50])
                filename = f"Proposal_{safe_title}.pdf"

                resp = await client.post(
                    f"{TELEGRAM_API}/bot{bot_token}/sendDocument",
                    data={
                        "chat_id": TENDER_GROUP_ID,
                        "caption": f"\U0001f4c4 Proposal: {tender.title[:100]}",
                    },
                    files={"document": (filename, io.BytesIO(pdf_bytes), "application/pdf")},
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    results["pdf"] = True
                    logger.info("Tender PDF sent: %s", filename)
                else:
                    logger.warning("Tender PDF failed: %s", resp.text[:100])
        except Exception as e:
            logger.error("Telegram PDF error: %s", e)

    return results
