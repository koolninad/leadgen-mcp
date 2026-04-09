"""LeadGen MCP Server — AI-powered lead generation for software development agencies.

41 tools across 6 modules:
- Website Scanner (7): Scan websites for tech stacks, performance, security, accessibility, missing features
- Platform Crawler (10): Crawl LinkedIn, Clutch, Upwork, Wellfound, GoodFirms, G2, IndieHackers, ProductHunt
- Lead Enrichment (6): Find emails, decision-makers, company intel, score leads
- AI Email (6): Generate personalized outreach emails with Gemma 4 via Ollama
- Email Sender (6): Send emails with tracking, campaigns, rate limiting, analytics
- Domain Intelligence (7): WHOIS, DNS health, SSL monitoring, HTTP health, broken links
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="leadgen-mcp",
    version="1.0.0",
    instructions=(
        "AI-powered lead generation MCP server for software development agencies. "
        "Scans websites for technical issues, crawls platforms (LinkedIn, Upwork, Clutch, etc.) "
        "for project opportunities, enriches leads with emails and company intel, generates "
        "personalized outreach emails using Gemma 4, and sends them with tracking."
    ),
)

# Register all tool modules
from .scanner.tools import register as register_scanner
from .platforms.tools import register as register_platforms
from .enrichment.tools import register as register_enrichment
from .ai.tools import register as register_ai
from .email_sender.tools import register as register_email
from .domain_intel.tools import register as register_domain_intel
from .platforms.linkedin_stealth import register as register_linkedin_stealth

register_scanner(mcp)
register_platforms(mcp)
register_enrichment(mcp)
register_ai(mcp)
register_email(mcp)
register_domain_intel(mcp)
register_linkedin_stealth(mcp)


# --- Database initialization tool ---

@mcp.tool()
async def init_database() -> dict:
    """Initialize the lead generation database. Run this first before using other tools."""
    from .db.repository import get_db
    await get_db()
    return {"status": "ok", "message": "Database initialized successfully"}


@mcp.tool()
async def server_status() -> dict:
    """Check the status of the LeadGen MCP server and its dependencies."""
    from .ai.ollama_client import check_health
    from .config import settings

    ai_status = await check_health()

    return {
        "server": "leadgen-mcp v1.0.0",
        "database": settings.db_path,
        "ai_engine": ai_status,
        "smtp_configured": bool(settings.smtp_user),
        "tracking_url": settings.tracking_base_url,
        "linkedin_stealth_configured": bool(settings.linkedin_email),
        "tools_registered": 47,
        "modules": [
            "scanner (7 tools)",
            "platforms (10 tools)",
            "linkedin_stealth (5 tools)",
            "enrichment (6 tools)",
            "ai (6 tools)",
            "email_sender (6 tools)",
            "domain_intel (7 tools)",
        ],
    }


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
