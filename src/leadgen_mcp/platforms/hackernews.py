"""Hacker News crawling for lead generation via the Algolia API."""

import json
from urllib.parse import quote_plus

from .base import PlatformCrawler, PlatformLead


HN_API_BASE = "https://hn.algolia.com/api/v1"

SIGNAL_KEYWORDS = {
    "hiring": ["hiring", "looking for", "need developer", "job", "freelance"],
    "show_hn_launch": ["show hn", "launched", "just built", "side project"],
    "ask_hn_needs_dev": ["ask hn", "need help", "looking for developer", "technical cofounder"],
}


class HackerNewsCrawler(PlatformCrawler):
    platform_name = "hackernews"
    rate_limit = 5.0  # HN Algolia API is generous
    max_concurrency = 5

    async def crawl(self, query: dict) -> list[PlatformLead]:
        action = query.get("action", "search")
        if action == "hiring":
            return await self._crawl_hiring(query)
        elif action == "show_hn":
            return await self._crawl_show_hn(query)
        elif action == "ask_hn":
            return await self._crawl_ask_hn(query)
        return await self._search_all(query)

    async def _search_all(self, query: dict) -> list[PlatformLead]:
        """General search across HN posts."""
        keywords = query.get("keywords", ["looking for developer"])
        max_results = query.get("max_results", 20)

        search_query = " ".join(keywords)
        url = f"{HN_API_BASE}/search?query={quote_plus(search_query)}&hitsPerPage={max_results}"

        raw = await self._throttled_fetch(url)
        data = json.loads(raw)

        return self._parse_hits(data.get("hits", []), max_results)

    async def _crawl_hiring(self, query: dict) -> list[PlatformLead]:
        """Search 'Who is Hiring' threads and hiring posts."""
        max_results = query.get("max_results", 20)

        url = (
            f"{HN_API_BASE}/search?query=looking+for+developer"
            f"&tags=ask_hn&hitsPerPage={max_results}"
        )

        raw = await self._throttled_fetch(url)
        data = json.loads(raw)

        leads = []
        for hit in data.get("hits", [])[:max_results]:
            title = hit.get("title") or hit.get("story_title") or ""
            text = hit.get("comment_text") or hit.get("story_text") or ""
            author = hit.get("author", "unknown")
            object_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"

            signals = ["hiring"]
            description = title or text[:300]

            leads.append(PlatformLead(
                source="hackernews",
                company_name=author,
                contact_name=author,
                description=description,
                raw_url=hn_url,
                signals=signals,
            ))

        return leads

    async def _crawl_show_hn(self, query: dict) -> list[PlatformLead]:
        """Find Show HN posts — new product launches that may need dev help."""
        max_results = query.get("max_results", 20)
        keywords = query.get("keywords", ["show hn"])

        search_query = " ".join(keywords)
        url = (
            f"{HN_API_BASE}/search?query={quote_plus(search_query)}"
            f"&tags=show_hn&hitsPerPage={max_results}"
        )

        raw = await self._throttled_fetch(url)
        data = json.loads(raw)

        leads = []
        for hit in data.get("hits", [])[:max_results]:
            title = hit.get("title", "")
            author = hit.get("author", "unknown")
            object_id = hit.get("objectID", "")
            points = hit.get("points", 0)
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            project_url = hit.get("url", "")

            # Extract domain from project URL
            domain = None
            if project_url:
                import re
                domain_match = re.search(r"https?://(?:www\.)?([^/]+)", project_url)
                if domain_match:
                    domain = domain_match.group(1)

            signals = ["show_hn_launch"]
            if points and points > 100:
                signals.append("popular_launch")

            leads.append(PlatformLead(
                source="hackernews",
                company_name=title[:80],
                contact_name=author,
                domain=domain,
                description=f"{title} (by {author}, {points} points)",
                raw_url=hn_url,
                signals=signals,
            ))

        return leads

    async def _crawl_ask_hn(self, query: dict) -> list[PlatformLead]:
        """Find Ask HN posts where people need developer help."""
        max_results = query.get("max_results", 20)
        keywords = query.get("keywords", ["need developer", "looking for developer", "technical cofounder"])

        search_query = " ".join(keywords[:2])
        url = (
            f"{HN_API_BASE}/search?query={quote_plus(search_query)}"
            f"&tags=ask_hn&hitsPerPage={max_results}"
        )

        raw = await self._throttled_fetch(url)
        data = json.loads(raw)

        leads = []
        for hit in data.get("hits", [])[:max_results]:
            title = hit.get("title") or ""
            author = hit.get("author", "unknown")
            object_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"

            signals = ["ask_hn_needs_dev"]

            leads.append(PlatformLead(
                source="hackernews",
                company_name=author,
                contact_name=author,
                description=title,
                raw_url=hn_url,
                signals=signals,
            ))

        return leads

    def _parse_hits(self, hits: list, max_results: int) -> list[PlatformLead]:
        """Parse Algolia API hits into PlatformLead objects."""
        leads = []
        for hit in hits[:max_results]:
            title = hit.get("title") or hit.get("story_title") or ""
            author = hit.get("author", "unknown")
            object_id = hit.get("objectID", "")
            points = hit.get("points", 0)
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            project_url = hit.get("url", "")

            # Detect signals from title
            signals = []
            title_lower = title.lower()
            for signal_name, kws in SIGNAL_KEYWORDS.items():
                if any(kw in title_lower for kw in kws):
                    signals.append(signal_name)

            domain = None
            if project_url:
                import re
                dm = re.search(r"https?://(?:www\.)?([^/]+)", project_url)
                if dm:
                    domain = dm.group(1)

            leads.append(PlatformLead(
                source="hackernews",
                company_name=author,
                contact_name=author,
                domain=domain,
                description=f"{title} ({points} points)",
                raw_url=hn_url,
                signals=signals or ["hn_post"],
            ))

        return leads
