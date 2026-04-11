"""New company registration scanner — finds newly incorporated companies globally.

Strategy: SearXNG searches for company registrations in target countries.
UK Companies House API when API key is available.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from .base import PlatformCrawler, PlatformLead
from ..config import settings
from ..utils.http import create_client
from ..utils.search import web_search

logger = logging.getLogger("leadgen.platforms.company_registry")

# Country-specific search queries for new company registrations
COUNTRY_QUERIES = {
    # Priority 1: India
    "India": [
        "newly registered company India software technology 2026",
        "MCA new company incorporation IT services India 2026",
        "startup registered India technology digital 2026",
    ],
    # Priority 1: USA
    "USA": [
        "new business registration USA software technology 2026",
        "SEC EDGAR new company filing technology startup 2026",
        "Delaware incorporation technology software startup 2026",
    ],
    # Priority 1: UK
    "UK": [
        "companies house new incorporation technology software 2026",
        "UK new company registered IT services digital 2026",
    ],
    # Priority 1: UAE
    "UAE": [
        "new company registered Dubai technology software 2026",
        "DMCC new business license IT digital UAE 2026",
        "Abu Dhabi new company registration technology 2026",
    ],
    # Priority 1: Singapore
    "Singapore": [
        "ACRA new company registration Singapore technology 2026",
        "Singapore startup incorporated software IT 2026",
    ],
    # Priority 2: Middle East
    "Saudi Arabia": [
        "Saudi Arabia new company registration technology IT 2026",
    ],
    "Qatar": [
        "Qatar new company registration technology software 2026",
    ],
    # Priority 2: Southeast Asia
    "Malaysia": [
        "SSM Malaysia new company registration technology 2026",
    ],
    "Philippines": [
        "SEC Philippines new company registration IT software 2026",
    ],
    # Priority 3: Others
    "Australia": [
        "ASIC new company registration technology software 2026",
    ],
    "Canada": [
        "Canada new business registration technology startup 2026",
    ],
    "Germany": [
        "Germany new company registration technology GmbH 2026",
    ],
}


class CompanyRegistryCrawler(PlatformCrawler):
    platform_name = "company_registry"
    rate_limit = 2.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        keywords = query.get("keywords", ["software", "technology"])
        max_results = query.get("max_results", 30)
        countries = query.get("countries", list(COUNTRY_QUERIES.keys()))

        leads = []

        # Try UK Companies House API first if key available
        if settings.companies_house_api_key:
            try:
                uk_leads = await self._crawl_companies_house(keywords, 30, max_results // 3)
                leads.extend(uk_leads)
            except Exception as e:
                logger.debug("Companies House API failed: %s", e)

        # Search all target countries via SearXNG
        for country in countries:
            if len(leads) >= max_results:
                break

            queries = COUNTRY_QUERIES.get(country, [f"new company registration {country} technology software 2026"])

            for search_query in queries[:1]:  # 1 query per country to avoid overload
                try:
                    results = await web_search(search_query, max_results=5)

                    for r in results:
                        title = r.get("title", "")
                        url = r.get("url", "")
                        snippet = r.get("snippet", r.get("content", ""))

                        # Skip aggregator/directory pages
                        if any(skip in url for skip in [
                            "google.", "facebook.", "wikipedia.", "linkedin.",
                            "youtube.", "twitter.", "/search", "/category",
                        ]):
                            continue

                        # Skip if title is clearly not a company
                        title_lower = title.lower()
                        if any(skip in title_lower for skip in [
                            "definition", "meaning", "how to", "what is",
                            "template", "format", "sample",
                        ]):
                            continue

                        # Extract company name
                        company = re.sub(
                            r"\s*[\|–-]\s*(Companies House|MCA|ACRA|DMCC|SEC|LinkedIn|Bloomberg).*$",
                            "", title
                        ).strip()[:80]

                        # Extract domain if present
                        domain = None
                        domain_match = re.search(r"https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", url)
                        if domain_match:
                            d = domain_match.group(1)
                            if not any(skip in d for skip in ["google.", "facebook.", "linkedin."]):
                                domain = d

                        signals = ["newly_incorporated"]
                        if any(kw in f"{title} {snippet}".lower() for kw in ["software", "tech", "digital", "it ", "cloud"]):
                            signals.append("tech_company")

                        leads.append(PlatformLead(
                            source="company_registry",
                            company_name=company,
                            domain=domain,
                            description=snippet[:200] if snippet else title,
                            signals=signals,
                            raw_url=url,
                            location=country,
                        ))

                        if len(leads) >= max_results:
                            break

                except Exception as e:
                    logger.debug("Company search failed for %s: %s", country, e)

        logger.info("Company registry: %d leads across %d countries", len(leads), len(countries))
        return leads[:max_results]

    async def _crawl_companies_house(self, keywords, days_back, max_results):
        """UK Companies House API (free, needs API key)."""
        leads = []
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        for keyword in keywords[:2]:
            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(
                        "https://api.company-information.service.gov.uk/advanced-search/companies",
                        params={"company_name_includes": keyword, "incorporated_from": since, "size": 10},
                        auth=(settings.companies_house_api_key, ""),
                    )
                    if resp.status_code != 200:
                        continue

                    for item in resp.json().get("items", []):
                        name = item.get("company_name", "")
                        number = item.get("company_number", "")
                        leads.append(PlatformLead(
                            source="company_registry",
                            company_name=name[:80],
                            description=f"UK company. Number: {number}",
                            signals=["newly_incorporated", "uk_company"],
                            raw_url=f"https://find-and-update.company-information.service.gov.uk/company/{number}",
                            location="UK",
                        ))
            except Exception as e:
                logger.debug("Companies House failed: %s", e)

        return leads[:max_results]
