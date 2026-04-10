"""LeadGen MCP Server — AI-powered lead generation for Chandorkar Technologies.

6 verticals: HostingDuty, Chandorkar Tech, Nubo, Vikasit AI, Setara, Staff Aug.
22 crawlers, 180 sender accounts, PostgreSQL backend, warmup system.

Modules:
- Website Scanner (7): Tech stacks, performance, security, accessibility, missing features
- Platform Crawler (22): Reddit, HN, LinkedIn, Upwork, Google Maps, CT Logs, Yellow Pages, etc.
- Lead Enrichment (6+): Emails, decision-makers, company intel, scoring, vertical matching
- AI Email (6): Personalized outreach via Gemma 4 / Ollama
- Email Sender (6): Campaigns, rate limiting, sender rotation, tracking
- Domain Intelligence (7): WHOIS, DNS, SSL, HTTP health, broken links
- Warmup (2): Sender account warmup status and history
- Listmonk (5): Campaign management, subscriber sync
- IMAP Aggregate (2): Reply inbox stats, recent replies
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="leadgen-mcp",
    version="2.0.0",
    instructions=(
        "AI-powered lead generation MCP server for Chandorkar Technologies. "
        "22 independent crawlers scan the internet for leads across 6 verticals. "
        "Leads are enriched, scored, matched to verticals, and emailed via "
        "180 rotating sender accounts with warmup. Campaigns managed via Listmonk."
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

# New modules (require PostgreSQL via DATABASE_URL)
from .config import settings
if settings.database_url:
    from .warmup.tools import register_warmup
    from .listmonk.tools import register_listmonk
    from .imap_aggregate.tools import register_imap

    register_warmup(mcp)
    register_listmonk(mcp)
    register_imap(mcp)


# --- Database initialization tool ---

@mcp.tool()
async def init_database() -> dict:
    """Initialize the lead generation database. Run this first before using other tools."""
    if settings.database_url:
        from .db.pg_repository import get_pool
        await get_pool()
        return {"status": "ok", "backend": "postgresql"}
    else:
        from .db.repository import get_db
        await get_db()
        return {"status": "ok", "backend": "sqlite"}


@mcp.tool()
async def server_status() -> dict:
    """Check the status of the LeadGen MCP server and its dependencies."""
    from .ai.ollama_client import check_health

    ai_status = await check_health()
    db_backend = "postgresql" if settings.database_url else f"sqlite:{settings.db_path}"

    status = {
        "server": "leadgen-mcp v2.0.0",
        "database": db_backend,
        "ai_engine": ai_status,
        "smtp_configured": bool(settings.smtp_user),
        "tracking_url": settings.tracking_base_url,
        "linkedin_stealth_configured": bool(settings.linkedin_email),
        "warmup_enabled": settings.warmup_enabled and bool(settings.database_url),
        "listmonk_configured": bool(settings.listmonk_password),
        "crawlers": 22,
    }

    if settings.database_url:
        try:
            from .db.pg_repository import get_pool
            pool = await get_pool()
            row = await pool.fetchrow("SELECT COUNT(*) as c FROM sender_accounts WHERE is_enabled = TRUE")
            status["sender_accounts"] = row["c"] if row else 0
            row = await pool.fetchrow("SELECT COUNT(*) as c FROM leads")
            status["total_leads"] = row["c"] if row else 0
        except Exception:
            pass

    return status


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
