"""Wellfound (AngelList) startup scraping."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


class WellfoundCrawler(PlatformCrawler):
    platform_name = "wellfound"
    rate_limit = 2.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl Wellfound for startups needing development work."""
        industry = query.get("industry", "software")
        stage = query.get("stage", "")  # seed, series-a, etc.
        max_results = query.get("max_results", 20)

        # Use DuckDuckGo to find Wellfound company pages
        search_query = f"site:wellfound.com/company {industry}"
        if stage:
            search_query += f" {stage}"
        search_query += " hiring developer engineer"

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            if "wellfound.com" not in url:
                continue

            company_name = re.sub(r"\s*[\|–-]\s*Wellfound.*$", "", title)

            # Extract signals from snippet
            signals = ["startup", "wellfound_listed"]
            if "hiring" in snippet.lower():
                signals.append("actively_hiring")
            if "series" in snippet.lower():
                signals.append("funded_startup")
            if "seed" in snippet.lower():
                signals.append("seed_stage")

            leads.append(PlatformLead(
                source="wellfound",
                company_name=company_name,
                description=snippet,
                raw_url=url,
                industry=industry,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads
