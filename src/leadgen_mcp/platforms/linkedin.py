"""LinkedIn public page and job scraping for lead generation.

Uses stealth browser when LinkedIn credentials are configured,
falls back to DuckDuckGo/SearXNG web search otherwise.
"""

import logging
import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search
from ..config import settings

logger = logging.getLogger(__name__)


class LinkedInCrawler(PlatformCrawler):
    platform_name = "linkedin"
    rate_limit = 1.0  # Very conservative — LinkedIn aggressively blocks scrapers
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        # If LinkedIn credentials are set, use stealth browser
        if settings.linkedin_email and settings.linkedin_password:
            try:
                return await self._crawl_with_stealth(query)
            except Exception as exc:
                logger.warning(
                    "Stealth browser failed (%s), falling back to web search", exc
                )
        # Otherwise fallback to web search
        return await self._crawl_with_search(query)

    async def _crawl_with_stealth(self, query: dict) -> list[PlatformLead]:
        """Use the Playwright stealth browser for direct LinkedIn scraping."""
        from .linkedin_stealth import LinkedInStealth

        action = query.get("action", "companies")
        keywords = query.get("keywords", [])
        location = query.get("location", "")
        max_results = query.get("max_results", 20)
        search_terms = " ".join(keywords)

        stealth = LinkedInStealth()
        try:
            if action == "companies":
                industry = query.get("industry", "")
                if industry:
                    search_terms += f" {industry}"
                return await stealth.search_companies(search_terms, location, max_results)
            elif action == "jobs":
                return await stealth.search_jobs(search_terms, location, max_results)
            elif action == "posts":
                return await stealth.search_posts(search_terms, max_results)
            else:
                return await stealth.search_companies(search_terms, location, max_results)
        finally:
            await stealth.close()

    async def _crawl_with_search(self, query: dict) -> list[PlatformLead]:
        """Fallback: search via DuckDuckGo/SearXNG."""
        action = query.get("action", "companies")
        if action == "companies":
            return await self._crawl_companies(query)
        elif action == "jobs":
            return await self._crawl_jobs(query)
        return []

    async def _crawl_companies(self, query: dict) -> list[PlatformLead]:
        """Search LinkedIn for companies using DuckDuckGo search."""
        keywords = query.get("keywords", [])
        location = query.get("location", "")
        industry = query.get("industry", "")
        max_results = query.get("max_results", 20)

        search_terms = " ".join(keywords)
        if location:
            search_terms += f" {location}"
        if industry:
            search_terms += f" {industry}"

        search_query = f"site:linkedin.com/company {search_terms}"
        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            if "linkedin.com/company" not in url:
                continue

            # Clean up title: remove " | LinkedIn", "- LinkedIn" etc.
            company_name = re.sub(r"\s*[\|–-]\s*LinkedIn.*$", "", title)

            # Try to extract domain from snippet or company name
            domain = self._extract_domain_from_text(snippet)

            leads.append(PlatformLead(
                source="linkedin",
                company_name=company_name,
                domain=domain,
                description=snippet,
                raw_url=url,
                location=location or None,
                industry=industry or None,
                signals=["linkedin_company_page"],
                skills_needed=keywords,
            ))

            if len(leads) >= max_results:
                break

        return leads

    async def _crawl_jobs(self, query: dict) -> list[PlatformLead]:
        """Search LinkedIn job postings indicating tech needs."""
        keywords = query.get("keywords", ["software development", "web application"])
        location = query.get("location", "")
        max_results = query.get("max_results", 20)

        search_terms = " ".join(keywords)
        if location:
            search_terms += f" {location}"

        search_query = f"site:linkedin.com/jobs {search_terms}"
        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            if "linkedin.com/jobs" not in url:
                continue

            # Extract company name from job title pattern: "Job Title at Company"
            company = ""
            match = re.search(r"(?:at|@)\s+(.+?)(?:\s*[\|–-]|$)", title)
            if match:
                company = match.group(1).strip()

            signals = ["hiring_tech_role"]
            for kw in ["senior", "lead", "architect", "full-stack", "fullstack"]:
                if kw in title.lower():
                    signals.append(f"hiring_{kw.replace('-', '_')}")

            leads.append(PlatformLead(
                source="linkedin_jobs",
                company_name=company or title,
                description=f"{title}\n{snippet}",
                raw_url=url,
                location=location or None,
                signals=signals,
                skills_needed=keywords,
            ))

            if len(leads) >= max_results:
                break

        return leads

    def _extract_domain_from_text(self, text: str) -> str | None:
        """Try to find a domain in text."""
        match = re.search(r"(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
        if match:
            domain = match.group(1)
            if "linkedin.com" not in domain:
                return domain
        return None
