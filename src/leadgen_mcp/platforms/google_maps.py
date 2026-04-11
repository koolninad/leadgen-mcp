"""Google Maps crawling for local businesses without websites via DuckDuckGo search."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


SIGNAL_PATTERNS = {
    "no_website": re.compile(r"no\s+website|without\s+website|no\s+web\s+presence", re.I),
    "needs_web_presence": re.compile(r"yelp\.com|facebook\.com/pages|yellowpages", re.I),
    "local_business": re.compile(
        r"restaurant|plumber|dentist|salon|lawyer|contractor|clinic|repair|cleaning|landscap",
        re.I,
    ),
}


class GoogleMapsCrawler(PlatformCrawler):
    platform_name = "google_maps"
    rate_limit = 2.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        action = query.get("action", "no_website")
        if action == "no_website":
            return await self._find_businesses_without_websites(query)
        return await self._find_local_businesses(query)

    async def _find_businesses_without_websites(self, query: dict) -> list[PlatformLead]:
        """Find local businesses that don't have a website using SearXNG/DDG search."""
        import random

        categories = query.get("categories", [query.get("category", "restaurant")])
        cities = query.get("cities", [query.get("city", "")])
        max_results = query.get("max_results", 30)

        # Pick random category + city combo each run for variety
        category = random.choice(categories) if isinstance(categories, list) else categories
        city = random.choice(cities) if isinstance(cities, list) and cities else "United States"
        location = city

        # Strategy: Search for businesses with only social media / directory pages
        search_query = (
            f'"{category}" "{location}" '
            f'(site:yelp.com OR site:facebook.com OR site:yellowpages.com) '
            f'-site:*.{category.replace(" ", "")}.com'
        )

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            # Extract business name (usually before " - Yelp", " | Facebook", etc.)
            business_name = re.sub(
                r"\s*[\|–-]\s*(Yelp|Facebook|Yellow\s*Pages|Foursquare).*$", "", title
            ).strip()

            signals = ["no_website", "local_business"]
            if "yelp.com" in url:
                signals.append("needs_web_presence")

            leads.append(PlatformLead(
                source="google_maps",
                company_name=business_name,
                description=f"{title}\n{snippet}",
                raw_url=url,
                location=location,
                industry=category,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads

    async def _find_local_businesses(self, query: dict) -> list[PlatformLead]:
        """Search for local businesses in a category/city via DuckDuckGo."""
        category = query.get("category", "restaurant")
        city = query.get("city", "")
        location = query.get("location", city)
        max_results = query.get("max_results", 20)

        if not location:
            location = "United States"

        search_query = f'site:google.com/maps "{category}" "{location}"'

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            business_name = re.sub(r"\s*[\|–-]\s*Google\s*Maps.*$", "", title).strip()

            signals = ["local_business"]

            leads.append(PlatformLead(
                source="google_maps",
                company_name=business_name,
                description=f"{title}\n{snippet}",
                raw_url=url,
                location=location,
                industry=category,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads
