"""MCP tool definitions for the Lead Enrichment module."""

from .email_finder import find_emails_for_domain
from .contacts import find_decision_makers
from .company_intel import get_company_intel
from .scoring import score_lead
from .social_profiler import SocialProfiler
from ..db.repository import (
    get_lead, get_contacts, save_contact, save_scan_result,
    query_leads,
)
from ..utils.validators import extract_domain


def register(mcp):
    """Register all enrichment tools with the MCP server."""

    @mcp.tool()
    async def enrich_lead(lead_id: str) -> dict:
        """Run full enrichment on a lead: find emails, contacts, company intel, and score.

        Args:
            lead_id: The ID of the lead to enrich
        """
        lead = await get_lead(lead_id)
        if not lead:
            return {"error": f"Lead {lead_id} not found"}

        domain = lead.get("domain")
        if not domain:
            return {"error": "Lead has no domain — cannot enrich"}

        results = {"lead_id": lead_id, "domain": domain}

        # 1. Find emails
        email_results = await find_emails_for_domain(domain, lead.get("company_name"))
        results["emails"] = email_results

        # Save found emails as contacts
        for email in email_results.get("emails_found", []):
            await save_contact(lead_id, email=email, source="website_scrape", email_verified=False)

        # 2. Find decision makers
        contacts = await find_decision_makers(domain)
        results["decision_makers"] = contacts

        for contact in contacts:
            await save_contact(
                lead_id,
                name=contact.get("name"),
                title=contact.get("title"),
                source=contact.get("source", "website"),
            )

        # 3. Company intelligence
        intel = await get_company_intel(domain)
        results["company_intel"] = intel

        # Save intel as scan result
        await save_scan_result(lead_id, "company_intel", intel, "info")

        # 4. Score the lead
        score = await score_lead(lead_id)
        results["score"] = score

        return results

    @mcp.tool()
    async def find_emails(domain: str, contact_name: str | None = None) -> dict:
        """Find email addresses for a domain by scraping the website and generating candidates.

        Args:
            domain: The domain to find emails for (e.g., 'example.com')
            contact_name: Optional name to generate personalized email candidates
        """
        return await find_emails_for_domain(domain, contact_name)

    @mcp.tool()
    async def find_lead_decision_makers(domain: str) -> dict:
        """Find decision-makers (CEO, CTO, VP, Director) from a company's website.

        Args:
            domain: The company's domain (e.g., 'example.com')
        """
        contacts = await find_decision_makers(domain)
        return {"domain": domain, "decision_makers": contacts, "total": len(contacts)}

    @mcp.tool()
    async def get_company_intelligence(domain: str) -> dict:
        """Gather company intelligence: size, revenue estimate, industry, social links, hiring signals.

        Args:
            domain: The company's domain (e.g., 'example.com')
        """
        return await get_company_intel(domain)

    @mcp.tool()
    async def score_a_lead(lead_id: str) -> dict:
        """Calculate a comprehensive lead score (0-100) based on tech opportunity, budget signals, engagement readiness, and contact quality.

        Args:
            lead_id: The ID of the lead to score
        """
        return await score_lead(lead_id)

    @mcp.tool()
    async def search_leads(
        min_score: float = 0,
        source_platform: str | None = None,
        domain_contains: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Search and filter leads in the database.

        Args:
            min_score: Minimum lead score threshold (0-100)
            source_platform: Filter by source (linkedin, clutch, upwork, etc.)
            domain_contains: Filter by domain substring
            limit: Maximum results to return
        """
        leads = await query_leads(
            min_score=min_score,
            source_platform=source_platform,
            domain_contains=domain_contains,
            limit=limit,
        )
        return {"total": len(leads), "leads": leads}

    @mcp.tool()
    async def find_social_profiles(username: str) -> dict:
        """Find social media profiles for a username across GitHub, Twitter, LinkedIn, Reddit,
        ProductHunt, Dev.to, Medium, Dribbble, Behance, and StackOverflow.

        Checks each platform concurrently and returns which ones have an active profile.

        Args:
            username: The username to search for across platforms
        """
        profiler = SocialProfiler()
        return await profiler.find_profiles(username)

    @mcp.tool()
    async def enrich_github_profile(username: str) -> dict:
        """Get detailed profile information from a GitHub username.
        Returns: name, company, blog, location, bio, public repos, followers, hireable status, etc.

        Args:
            username: GitHub username to look up
        """
        profiler = SocialProfiler()
        return await profiler.enrich_from_github(username)

    @mcp.tool()
    async def find_company_social_profiles(company_name: str, domain: str = "") -> dict:
        """Find all social media profiles for a company by trying common username patterns.
        Checks variations like 'acmecorp', 'acme_corp', 'acme-corp' across all platforms.

        Args:
            company_name: The company name to search for
            domain: Optional company domain to derive additional username candidates
        """
        profiler = SocialProfiler()
        return await profiler.find_company_profiles(company_name, domain)
