"""G2 review scraping for extracting tech pain points from reviews."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


class G2Crawler(PlatformCrawler):
    platform_name = "g2"
    rate_limit = 2.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl G2 for products/companies with negative reviews indicating tech needs."""
        product_category = query.get("product_category", "web-development")
        max_results = query.get("max_results", 20)

        search_query = f"site:g2.com/categories/{product_category} OR site:g2.com/products"
        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            if "g2.com" not in url:
                continue

            # Clean title
            company_name = re.sub(r"\s*[\|–-]\s*G2.*$", "", title)
            company_name = re.sub(r"\s*Reviews\s*\d*", "", company_name)

            signals = ["g2_listed"]
            # Analyze snippet for pain points
            pain_keywords = ["slow", "bug", "crash", "outdated", "expensive", "difficult",
                           "poor support", "missing feature", "unreliable", "complex"]
            for kw in pain_keywords:
                if kw in snippet.lower():
                    signals.append(f"pain_point_{kw.replace(' ', '_')}")

            leads.append(PlatformLead(
                source="g2",
                company_name=company_name,
                description=snippet,
                raw_url=url,
                industry=product_category,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads
