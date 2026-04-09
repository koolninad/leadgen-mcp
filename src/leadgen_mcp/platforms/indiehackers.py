"""IndieHackers scraping for products/founders needing development help."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


class IndieHackersCrawler(PlatformCrawler):
    platform_name = "indiehackers"
    rate_limit = 3.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl IndieHackers for products and founders needing dev help."""
        keywords = query.get("keywords", ["looking for developer", "need developer", "technical cofounder"])
        max_results = query.get("max_results", 20)

        all_leads = []

        for kw in keywords[:3]:  # Limit to first 3 keywords to stay within rate limits
            search_query = f"site:indiehackers.com {kw}"
            results = await web_search(search_query, max_results=10)

            for r in results:
                url = r["url"]
                title = r["title"]
                snippet = r["snippet"]

                if "indiehackers.com" not in url:
                    continue

                signals = ["indiehacker"]
                if "looking for" in snippet.lower() and "developer" in snippet.lower():
                    signals.append("needs_developer")
                if "technical cofounder" in snippet.lower():
                    signals.append("needs_technical_cofounder")
                if "mvp" in snippet.lower():
                    signals.append("building_mvp")

                all_leads.append(PlatformLead(
                    source="indiehackers",
                    company_name=re.sub(r"\s*[\|–-]\s*Indie Hackers.*$", "", title),
                    description=snippet,
                    raw_url=url,
                    signals=signals,
                ))

                if len(all_leads) >= max_results:
                    return all_leads

        return all_leads
