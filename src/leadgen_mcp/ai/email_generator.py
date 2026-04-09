"""Personalized email generation using Gemma 4 via Ollama."""

import json
import re

from .ollama_client import generate
from .prompts import (
    SYSTEM_PROMPT_OUTREACH,
    SYSTEM_PROMPT_FOLLOWUP,
    SYSTEM_PROMPT_REFINE,
    build_outreach_prompt,
    build_followup_prompt,
)
from .templates import get_template
from ..config import settings
from ..db.repository import get_lead, get_scan_results


async def generate_outreach_email(lead_id: str, template: str = "tech_audit") -> dict:
    """Generate a personalized outreach email for a lead."""
    lead = await get_lead(lead_id)
    if not lead:
        return {"error": f"Lead {lead_id} not found"}

    template_info = get_template(template)
    if not template_info:
        return {"error": f"Template '{template}' not found"}

    # Gather scan data
    scans = await get_scan_results(lead_id)
    scan_data = {}
    for scan in scans:
        scan_data[scan["scan_type"]] = scan["result"]

    # Parse lead data
    lead_data = dict(lead)
    if isinstance(lead_data.get("raw_data"), str):
        raw = json.loads(lead_data["raw_data"])
        lead_data.update(raw)

    # Build prompt
    prompt = build_outreach_prompt(lead_data, scan_data, template_info["focus"])

    # Generate email
    email_text = await generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT_OUTREACH,
        temperature=0.7,
        max_tokens=512,
    )

    # Parse subject and body
    subject, body = _parse_email(email_text)

    # Append CAN-SPAM footer
    body += _get_footer()

    return {
        "lead_id": lead_id,
        "template": template,
        "subject": subject,
        "body": body,
        "raw_generation": email_text,
        "personalization_notes": _extract_personalization(email_text, lead_data),
    }


async def generate_followup_sequence(lead_id: str, num_emails: int = 3) -> list[dict]:
    """Generate a multi-step follow-up email sequence."""
    lead = await get_lead(lead_id)
    if not lead:
        return [{"error": f"Lead {lead_id} not found"}]

    lead_data = dict(lead)
    if isinstance(lead_data.get("raw_data"), str):
        lead_data.update(json.loads(lead_data["raw_data"]))

    # First, generate the initial outreach
    initial = await generate_outreach_email(lead_id, "tech_audit")
    sequence = [initial]

    followup_types = ["value_add", "social_proof", "breakup"]
    previous_email = f"Subject: {initial.get('subject', '')}\n\n{initial.get('body', '')}"

    for i in range(min(num_emails - 1, len(followup_types))):
        prompt = build_followup_prompt(
            lead_data,
            previous_email,
            step_number=i + 2,
            followup_type=followup_types[i],
        )

        email_text = await generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT_FOLLOWUP,
            temperature=0.7,
            max_tokens=384,
        )

        subject, body = _parse_email(email_text)
        body += _get_footer()

        followup = {
            "lead_id": lead_id,
            "step": i + 2,
            "type": followup_types[i],
            "subject": subject,
            "body": body,
            "delay_days": (i + 1) * 3,  # 3, 6, 9 days after initial
        }
        sequence.append(followup)
        previous_email = f"Subject: {subject}\n\n{body}"

    return sequence


async def refine_email(draft: str, instructions: str) -> dict:
    """Refine an email draft based on specific instructions."""
    prompt = f"""Here is the email draft to refine:

---
{draft}
---

Instructions for refinement:
{instructions}

Output the refined email only (Subject: line first, then blank line, then body).
"""

    refined = await generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT_REFINE,
        temperature=0.5,
        max_tokens=512,
    )

    subject, body = _parse_email(refined)
    return {
        "subject": subject,
        "body": body,
        "instructions_applied": instructions,
    }


def _parse_email(text: str) -> tuple[str, str]:
    """Parse generated email text into subject and body."""
    text = text.strip()

    # Remove markdown code fences if present
    text = re.sub(r"^```.*?\n", "", text)
    text = re.sub(r"\n```$", "", text)

    # Try to extract subject line
    subject_match = re.match(r"(?:Subject:\s*)(.*?)(?:\n\n|\n)", text, re.IGNORECASE)
    if subject_match:
        subject = subject_match.group(1).strip()
        body = text[subject_match.end():].strip()
    else:
        # Fallback: first line is subject
        lines = text.split("\n", 1)
        subject = lines[0].replace("Subject:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

    return subject, body


def _get_footer() -> str:
    """Generate CAN-SPAM compliant footer."""
    return f"""

---
{settings.agency_name} | {settings.agency_website}
{settings.agency_address}
If you'd rather not hear from us, just reply "unsubscribe" and we'll remove you immediately."""


def _extract_personalization(email_text: str, lead_data: dict) -> list[str]:
    """Identify personalization elements used in the email."""
    notes = []
    company = lead_data.get("company_name", "")
    domain = lead_data.get("domain", "")

    if company and company.lower() in email_text.lower():
        notes.append(f"References company name: {company}")
    if domain and domain.lower() in email_text.lower():
        notes.append(f"References website: {domain}")

    tech_terms = ["wordpress", "react", "angular", "django", "laravel", "php",
                  "jquery", "bootstrap", "ssl", "security", "performance", "mobile"]
    for term in tech_terms:
        if term.lower() in email_text.lower():
            notes.append(f"References technology: {term}")

    return notes
