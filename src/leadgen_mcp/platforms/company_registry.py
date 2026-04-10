"""Company Registration Scanner.

Scans OpenCorporates and UK Companies House for newly incorporated companies.
New company registration = potential lead needing website/software.
"""

import logging
from datetime import datetime, timedelta, timezone

from .base import PlatformCrawler, PlatformLead
from ..config import settings
from ..utils.http import create_client

logger = logging.getLogger("leadgen.platforms.company_registry")


class CompanyRegistryCrawler(PlatformCrawler):
    platform_name = "company_registry"
    rate_limit = 2.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        source = query.get("source", "opencorporates")
        keywords = query.get("keywords", ["software", "technology", "digital", "app"])
        days_back = query.get("days_back", 30)
        max_results = query.get("max_results", 30)

        if source == "companies_house":
            return await self._crawl_companies_house(keywords, days_back, max_results)
        return await self._crawl_opencorporates(keywords, days_back, max_results)

    async def _crawl_opencorporates(
        self, keywords: list[str], days_back: int, max_results: int,
    ) -> list[PlatformLead]:
        """Search OpenCorporates for recently incorporated companies."""
        leads = []
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        for keyword in keywords[:3]:
            url = "https://api.opencorporates.com/v0.4/companies/search"
            params = {
                "q": keyword,
                "incorporation_date": f"{since}:",
                "order": "incorporation_date",
                "per_page": min(max_results, 30),
            }
            if settings.opencorporates_api_key:
                params["api_token"] = settings.opencorporates_api_key

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 403:
                        logger.warning("OpenCorporates rate limited or needs API key")
                        break
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    companies = data.get("results", {}).get("companies", [])

                    for item in companies:
                        co = item.get("company", {})
                        name = co.get("name", "")
                        jurisdiction = co.get("jurisdiction_code", "")
                        inc_date = co.get("incorporation_date", "")
                        oc_url = co.get("opencorporates_url", "")

                        leads.append(PlatformLead(
                            source="company_registry",
                            company_name=name[:80],
                            description=f"Newly incorporated ({inc_date}) in {jurisdiction}. Keyword: {keyword}",
                            signals=["newly_incorporated", "tech_company"],
                            raw_url=oc_url,
                            location=jurisdiction.upper(),
                        ))

            except Exception as e:
                logger.warning("OpenCorporates search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_companies_house(
        self, keywords: list[str], days_back: int, max_results: int,
    ) -> list[PlatformLead]:
        """Search UK Companies House for new incorporations."""
        if not settings.companies_house_api_key:
            logger.info("Companies House API key not set, skipping")
            return []

        leads = []
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        for keyword in keywords[:3]:
            url = "https://api.company-information.service.gov.uk/advanced-search/companies"
            params = {
                "company_name_includes": keyword,
                "incorporated_from": since,
                "size": min(max_results, 20),
            }

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(
                        url, params=params,
                        auth=(settings.companies_house_api_key, ""),
                    )
                    if resp.status_code != 200:
                        logger.warning("Companies House returned %d", resp.status_code)
                        continue

                    data = resp.json()
                    for item in data.get("items", []):
                        name = item.get("company_name", "")
                        number = item.get("company_number", "")
                        inc_date = item.get("date_of_creation", "")

                        leads.append(PlatformLead(
                            source="company_registry",
                            company_name=name[:80],
                            description=f"UK company incorporated {inc_date}. Number: {number}",
                            signals=["newly_incorporated", "uk_company"],
                            raw_url=f"https://find-and-update.company-information.service.gov.uk/company/{number}",
                            location="UK",
                        ))

            except Exception as e:
                logger.warning("Companies House failed: %s", e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]
