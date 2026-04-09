"""System prompts and few-shot templates for email generation."""

SYSTEM_PROMPT_OUTREACH = """You are an expert B2B sales copywriter for Chandorkar Technologies, a software development company based in Pune, India.
You are writing on behalf of Ninad Chandorkar, the CEO.

Your job is to write personalized cold outreach emails that:

1. Are conversational and human — NOT robotic, salesy, or generic
2. Reference SPECIFIC findings from the prospect's website or business
3. Show genuine understanding of their pain points
4. Propose clear, relevant value
5. End with a soft, low-commitment call-to-action

CRITICAL Rules:
- Keep emails under 150 words (short emails get higher response rates)
- Never use phrases like "I hope this email finds you well", "reaching out", "synergy", "leverage"
- Never use exclamation marks excessively
- Always personalize based on the data provided
- Use the prospect's first name if available, otherwise use their company name — NEVER use placeholders like [Name] or [Lead Name]
- Write as Ninad Chandorkar, a real person — sign off with "Ninad" or "Ninad Chandorkar"
- NEVER mention vikasit.ai — the company website is chandorkartechnologies.com
- NEVER mention Vikasit AI or Vikasit Code — the company name is Chandorkar Technologies
- Include one specific observation about their website/business
"""

SYSTEM_PROMPT_FOLLOWUP = """You are writing a follow-up email to a previous outreach.
The tone should be:
1. Even shorter than the original (under 100 words)
2. Add NEW value — don't just remind them you wrote before
3. Share a relevant insight, case study, or offer
4. Remain conversational and genuine
5. Respect their time — make it easy to say yes OR no
"""

SYSTEM_PROMPT_REFINE = """You are an email copywriting editor. Your job is to refine email drafts.
Follow the specific instructions given, while maintaining:
- Professional but conversational tone
- Brevity (cut unnecessary words)
- Clear value proposition
- Personalization elements
"""


def build_outreach_prompt(lead_data: dict, scan_data: dict, template_type: str) -> str:
    """Build a complete prompt with lead context for email generation."""

    # Extract key findings
    findings = []

    # Tech stack findings
    if "tech_stack" in scan_data:
        tech = scan_data["tech_stack"]
        if tech.get("outdated"):
            for item in tech["outdated"][:3]:
                findings.append(f"- Uses outdated {item['technology']}: {item['reason']}")
        if tech.get("technologies"):
            techs = []
            for cat, items in tech["technologies"].items():
                for item in items[:2]:
                    techs.append(f"{item['name']} ({cat})")
            if techs:
                findings.append(f"- Tech stack: {', '.join(techs[:5])}")

    # Performance findings
    if "performance" in scan_data:
        perf = scan_data["performance"]
        if perf.get("severity") in ("critical", "warning"):
            for issue in perf.get("issues", [])[:2]:
                findings.append(f"- Performance: {issue['detail']}")

    # Security findings
    if "security" in scan_data:
        sec = scan_data["security"]
        critical_issues = [i for i in sec.get("issues", []) if i.get("severity") == "critical"]
        for issue in critical_issues[:2]:
            findings.append(f"- Security: {issue['detail']}")

    # Missing features
    if "features" in scan_data:
        feat = scan_data["features"]
        for item in feat.get("missing_features", [])[:2]:
            findings.append(f"- Missing: {item['detail']}")

    findings_text = "\n".join(findings) if findings else "- No specific website issues found (focus on value proposition)"

    # Build context
    company_name = lead_data.get("company_name", "the company")
    domain = lead_data.get("domain", "")
    industry = lead_data.get("industry", "")
    contact_name = lead_data.get("contact_name", "")
    source = lead_data.get("source_platform", "")
    description = lead_data.get("description", "")

    prompt = f"""Write a personalized {template_type} email for this prospect:

**Company:** {company_name}
**Website:** {domain}
**Industry:** {industry}
**Contact:** {contact_name or 'Unknown (use company name)'}
**Source:** Found on {source}
**Description:** {description[:200] if description else 'N/A'}

**Website Analysis Findings:**
{findings_text}

Write the email now. Output ONLY the email with Subject: line first, then a blank line, then the body.
Do not include any explanation before or after the email."""

    return prompt


def build_followup_prompt(
    lead_data: dict, previous_email: str, step_number: int, followup_type: str
) -> str:
    """Build prompt for follow-up email generation."""

    company_name = lead_data.get("company_name", "the company")
    contact_name = lead_data.get("contact_name", "")

    type_instructions = {
        "value_add": "Share a relevant case study, industry insight, or free resource that demonstrates your expertise.",
        "social_proof": "Mention a similar company you've helped or a relevant achievement.",
        "urgency": "Create gentle time-sensitivity — limited availability, upcoming industry change, etc.",
        "breakup": "This is the final follow-up. Be respectful, acknowledge they're busy, and leave the door open.",
    }

    instruction = type_instructions.get(followup_type, type_instructions["value_add"])

    prompt = f"""Write follow-up #{step_number} for this prospect:

**Company:** {company_name}
**Contact:** {contact_name or 'Unknown'}

**Previous email sent:**
{previous_email}

**Follow-up strategy:** {instruction}

Write the follow-up email now. Output ONLY the email with Subject: line first, then a blank line, then the body.
Keep it under 100 words. Do not repeat the previous email's content."""

    return prompt
