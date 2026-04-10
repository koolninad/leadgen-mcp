"""Vertical matching — assign leads to business verticals.

Maps lead signals, scan data, and descriptions to the 6 verticals:
- hostingduty: Web Hosting & Domain Service
- chandorkar: Custom Software Development
- nubo: Storage-based Email Solution
- vikasit: Open Source AI Models & CLI Tools
- setara: Document Blockchain
- staff_aug: Staff Augmentation
"""

import re

from ..config import settings

# Signal → vertical mapping (direct matches)
SIGNAL_VERTICAL_MAP = {
    # HostingDuty signals
    "no_website": "hostingduty",
    "needs_web_presence": "hostingduty",
    "ssl_expired": "hostingduty",
    "site_timeout": "hostingduty",
    "server_errors": "hostingduty",
    "no_https": "hostingduty",
    "shared_hosting": "hostingduty",

    # Chandorkar Technologies signals
    "hiring": "chandorkar",
    "needs_developer": "chandorkar",
    "broken_website": "chandorkar",
    "outdated_wordpress": "chandorkar",
    "outdated_jquery": "chandorkar",
    "outdated_php": "chandorkar",
    "legacy_stack": "chandorkar",
    "accessibility_violations": "chandorkar",
    "ada_non_compliant": "chandorkar",
    "wcag_failures": "chandorkar",
    "uses_flash": "chandorkar",
    "not_mobile_friendly": "chandorkar",
    "new_product": "chandorkar",
    "show_hn_launch": "chandorkar",

    # Nubo signals
    "email_deliverability_issues": "nubo",
    "no_spf": "nubo",
    "no_dkim": "nubo",
    "no_dmarc": "nubo",

    # Vikasit AI signals
    "ai_product": "vikasit",

    # Setara signals
    "crypto_project": "setara",
    "blockchain": "setara",
    "needs_smart_contract_dev": "setara",

    # Tender signals
    "tender": "chandorkar",
    "government_contract": "chandorkar",
    "software_rfp": "chandorkar",
    "it_procurement": "chandorkar",
    "private_tender": "chandorkar",
    "rfp": "chandorkar",

    # Staff Augmentation signals
    "job_posting_expired": "staff_aug",
    "needs_technical_cofounder": "staff_aug",
    "looking_for_developer": "staff_aug",
}

# Description keyword patterns for each vertical
DESCRIPTION_PATTERNS = {
    "hostingduty": [
        re.compile(r"\b(hosting|domain|dns|ssl|server|vps|cloud\s+hosting|cpanel|whm)\b", re.I),
    ],
    "chandorkar": [
        re.compile(r"\b(software|develop|app|web\s*site|mobile|custom|build|code|program|fullstack|backend|frontend)\b", re.I),
        re.compile(r"\b(tender|rfp|procurement|contract|bid|proposal)\b", re.I),
    ],
    "nubo": [
        re.compile(r"\b(email|mail|smtp|deliverability|inbox|newsletter)\b", re.I),
    ],
    "vikasit": [
        re.compile(r"\b(ai|machine\s+learning|llm|gpt|model|automation|artificial\s+intelligence|chatbot)\b", re.I),
    ],
    "setara": [
        re.compile(r"\b(blockchain|smart\s+contract|crypto|token|nft|defi|web3|decentralized|document\s+verification)\b", re.I),
    ],
    "staff_aug": [
        re.compile(r"\b(hire|hiring|recruit|developer|engineer|team|augment|freelance|contract|talent)\b", re.I),
    ],
}

# Scan result signals → verticals
SCAN_VERTICAL_MAP = {
    "security_critical": "chandorkar",
    "performance_critical": "chandorkar",
    "missing_features": "chandorkar",
    "outdated_tech": "chandorkar",
}


def assign_vertical(
    signals: list[str] | None = None,
    description: str | None = None,
    scan_data: dict | None = None,
    source_platform: str | None = None,
) -> list[str]:
    """Determine which verticals match a lead.

    Returns a list of matching vertical names (can be multiple).
    Always returns at least one — defaults to 'chandorkar' (software dev).
    """
    matched = set()

    # 1. Match from signals
    if signals:
        for signal in signals:
            vertical = SIGNAL_VERTICAL_MAP.get(signal)
            if vertical:
                matched.add(vertical)

    # 2. Match from description keywords
    if description:
        for vertical, patterns in DESCRIPTION_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(description):
                    matched.add(vertical)
                    break

    # 3. Match from scan results
    if scan_data:
        for scan_type, results in scan_data.items():
            if isinstance(results, dict):
                severity = results.get("severity", "")
                if severity in ("critical", "warning"):
                    vertical = SCAN_VERTICAL_MAP.get(f"{scan_type}_{severity}")
                    if vertical:
                        matched.add(vertical)

    # 4. Source platform hints
    if source_platform:
        platform_hints = {
            "google_maps": "hostingduty",  # Local businesses need websites
            "yellowpages": "hostingduty",
            "upwork": "chandorkar",
            "github_projects": "chandorkar",
            "ct_log": "hostingduty",
            "company_registry": "chandorkar",
            "gov_tenders": "chandorkar",
            "private_tenders": "chandorkar",
        }
        vertical = platform_hints.get(source_platform)
        if vertical:
            matched.add(vertical)

    # Always include staff_aug if hiring/dev-need signals present
    if signals and any(s in signals for s in [
        "hiring", "needs_developer", "looking_for_developer",
        "needs_smart_contract_dev", "needs_technical_cofounder",
        "crypto_project",
    ]):
        matched.add("staff_aug")

    # Default to chandorkar if nothing matched
    if not matched:
        matched.add("chandorkar")

    return sorted(matched)
