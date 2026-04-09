"""Reddit crawling for lead generation.

Uses Reddit's public JSON API as primary source, with DuckDuckGo web
search as a fallback when the JSON API is unavailable.
"""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


SUBREDDITS = ["forhire", "startups", "webdev", "entrepreneur", "smallbusiness"]

SIGNAL_PATTERNS = {
    "hiring": re.compile(r"\[hiring\]|looking\s+for\s+(a\s+)?developer|need\s+(a\s+)?developer", re.I),
    "budget_mentioned": re.compile(r"\$[\d,]+|budget|pay(ing)?\s+\$|rate\s*:?\s*\$", re.I),
    "needs_developer": re.compile(r"need\s+(a\s+)?(web\s+)?dev|looking\s+for\s+freelanc|hiring\s+dev", re.I),
    "needs_website": re.compile(r"need\s+(a\s+)?website|build\s+(a\s+)?site|web\s+presence", re.I),
    "app_broken": re.compile(r"app\s+(is\s+)?broken|site\s+(is\s+)?down|bug(gy)?|not\s+working", re.I),
}


class RedditCrawler(PlatformCrawler):
    platform_name = "reddit"
    rate_limit = 2.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        # Try Reddit JSON API first (more reliable, richer data)
        try:
            from .reddit_api import RedditAPICrawler

            api_crawler = RedditAPICrawler()
            leads = await api_crawler.crawl(query)
            if leads:
                return leads
        except Exception:
            pass

        # Fallback to web search
        action = query.get("action", "search")
        if action == "subreddits":
            return await self._crawl_subreddits(query)
        return await self._search_reddit(query)

    async def _search_reddit(self, query: dict) -> list[PlatformLead]:
        """Search Reddit posts via DuckDuckGo."""
        keywords = query.get("keywords", ["looking for developer", "[Hiring]"])
        subreddits = query.get("subreddits", SUBREDDITS)
        max_results = query.get("max_results", 20)

        keyword_str = " OR ".join(f'"{kw}"' for kw in keywords[:3])
        sub_str = " OR ".join(f"site:reddit.com/r/{s}" for s in subreddits[:3])
        search_query = f"({sub_str}) {keyword_str}"

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            if "reddit.com" not in url:
                continue

            title = r["title"]
            snippet = r["snippet"]
            combined = f"{title} {snippet}"

            # Extract subreddit
            sub_match = re.search(r"reddit\.com/r/(\w+)", url)
            subreddit = sub_match.group(1) if sub_match else "unknown"

            # Detect signals
            signals = []
            for signal_name, pattern in SIGNAL_PATTERNS.items():
                if pattern.search(combined):
                    signals.append(signal_name)

            # Clean title
            poster = re.sub(r"\s*[\|:\-]\s*r/\w+.*$", "", title)
            poster = re.sub(r"\s*-\s*Reddit$", "", poster)

            leads.append(PlatformLead(
                source="reddit",
                company_name=poster[:80],
                description=f"[r/{subreddit}] {title}\n{snippet}",
                raw_url=url,
                signals=signals or ["reddit_post"],
                skills_needed=keywords,
            ))

            if len(leads) >= max_results:
                break

        return leads

    async def _crawl_subreddits(self, query: dict) -> list[PlatformLead]:
        """Crawl specific subreddits for hiring posts."""
        subreddits = query.get("subreddits", SUBREDDITS)
        max_results = query.get("max_results", 20)

        all_leads = []
        for sub in subreddits[:3]:
            search_query = f'site:reddit.com/r/{sub} "[Hiring]" OR "looking for developer"'
            results = await web_search(search_query, max_results=10)

            for r in results:
                if "reddit.com" not in r["url"]:
                    continue

                combined = f"{r['title']} {r['snippet']}"
                signals = []
                for signal_name, pattern in SIGNAL_PATTERNS.items():
                    if pattern.search(combined):
                        signals.append(signal_name)

                all_leads.append(PlatformLead(
                    source="reddit",
                    company_name=r["title"][:80],
                    description=f"[r/{sub}] {r['title']}\n{r['snippet']}",
                    raw_url=r["url"],
                    signals=signals or ["reddit_post"],
                ))

            if len(all_leads) >= max_results:
                break

        return all_leads[:max_results]
