"""Email template definitions for different outreach scenarios."""

TEMPLATES = {
    "tech_audit": {
        "name": "Tech Audit Outreach",
        "description": "Reference specific technical issues found on their website (outdated tech, security, performance)",
        "type": "intro",
        "focus": "website_issues",
        "best_for": "Leads with scan results showing tech problems",
    },
    "project_match": {
        "name": "Project Match Outreach",
        "description": "Reference their project posting on platforms like Upwork, Clutch, etc.",
        "type": "intro",
        "focus": "project_need",
        "best_for": "Leads found on project platforms (Upwork, Clutch)",
    },
    "growth_partner": {
        "name": "Growth Partner Outreach",
        "description": "Position as a development partner for their growing business",
        "type": "intro",
        "focus": "business_growth",
        "best_for": "Startups, recently funded companies, ProductHunt launches",
    },
    "modernization": {
        "name": "Modernization Outreach",
        "description": "Focus on modernizing their outdated tech stack",
        "type": "intro",
        "focus": "tech_modernization",
        "best_for": "Companies with outdated frameworks or CMS",
    },
    "security_alert": {
        "name": "Security-First Outreach",
        "description": "Lead with security findings to create urgency",
        "type": "intro",
        "focus": "security",
        "best_for": "Leads with critical security issues found",
    },
    "followup_value": {
        "name": "Value-Add Follow-up",
        "description": "Share a case study or insight relevant to their industry",
        "type": "followup",
        "focus": "value_add",
        "step": 1,
    },
    "followup_social_proof": {
        "name": "Social Proof Follow-up",
        "description": "Mention similar companies helped or achievements",
        "type": "followup",
        "focus": "social_proof",
        "step": 2,
    },
    "followup_breakup": {
        "name": "Breakup Email",
        "description": "Final respectful follow-up before closing the lead",
        "type": "followup",
        "focus": "breakup",
        "step": 3,
    },
}


def get_template(template_name: str) -> dict | None:
    return TEMPLATES.get(template_name)


def list_templates() -> list[dict]:
    return [{"id": k, **v} for k, v in TEMPLATES.items()]
