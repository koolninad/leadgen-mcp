"""Common utilities for tender source crawlers."""

# Expanded IT/Tech keywords — covers all verticals
IT_KEYWORDS = [
    # Software Development
    "software", "web application", "mobile app", "portal", "application development",
    "custom software", "web development", "app development",
    # IT Services
    "it services", "it service", "ict", "information technology", "digital",
    "e-governance", "e-government", "digital transformation",
    # Hosting & Cloud & DevOps
    "hosting", "cloud", "server", "data center", "data centre", "infrastructure",
    "aws", "azure", "devops", "kubernetes", "containerization", "virtualization",
    "managed hosting", "cloud migration", "iaas", "paas", "saas",
    # Cybersecurity
    "cybersecurity", "cyber security", "information security", "network security",
    "penetration testing", "security audit", "vapt", "soc",
    # Database & Analytics
    "database", "data analytics", "big data", "data warehouse", "business intelligence",
    # Blockchain
    "blockchain", "smart contract", "distributed ledger", "web3", "cryptocurrency",
    # Email & Communication
    "email solution", "email service", "messaging", "communication platform",
    "unified communication", "collaboration",
    # ERP & Enterprise
    "erp", "enterprise resource", "crm", "hrms", "human resource management",
    # Network & Telecom
    "network", "networking", "firewall", "lan", "wan", "wifi", "wireless",
    "telecommunications", "telecom",
    # General Tech
    "technology", "computer", "system integrator", "technical support",
    "help desk", "service desk", "maintenance",
    "artificial intelligence", "machine learning", "ai ", "ml ",
]

# Shorter list for quick filtering (title matching)
IT_KEYWORDS_SHORT = [
    "software", "it ", "ict", "digital", "web", "cloud", "data", "cyber",
    "network", "system", "application", "portal", "server", "hosting",
    "erp", "database", "mobile", "app", "technology", "computer",
    "blockchain", "devops", "email", "security", "infrastructure",
    "ai ", "saas", "analytics", "telecom",
]


def is_it_tender(text: str) -> bool:
    """Check if text matches IT/tech keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in IT_KEYWORDS_SHORT)


async def search_tenders_via_searxng(query: str, max_results: int = 10) -> list[dict]:
    """Search for tenders using SearXNG as fallback when APIs/scraping fail."""
    try:
        from ...utils.search import search_web
        results = await search_web(query, max_results=max_results)
        return results
    except Exception:
        return []
