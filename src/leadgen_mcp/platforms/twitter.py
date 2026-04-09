"""Twitter/X crawling for lead generation via DuckDuckGo search."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


SIGNAL_PATTERNS = {
    "hiring_signal": re.compile(r"hiring|looking\s+for\s+(a\s+)?dev|need\s+(a\s+)?cto|seeking\s+engineer", re.I),
    "funding_announcement": re.compile(r"raised\s+\$|funded|seed\s+round|series\s+[a-c]|investment", re.I),
    "tech_struggle": re.compile(r"app\s+(is\s+)?broken|site\s+(is\s+)?down|outage|bug(gy)?|struggling\s+with", re.I),
    "needs_developer": re.compile(r"need\s+(a\s+)?developer|looking\s+for\s+freelanc|who\s+can\s+build", re.I),
}


class TwitterCrawler(PlatformCrawler):
    platform_name = "twitter"
    rate_limit = 2.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Search Twitter/X for intent signals via DuckDuckGo."""
        keywords = query.get("keywords", [
            "looking for developer",
            "need a website",
            "need a CTO",
        ])
        max_results = query.get("max_results", 20)

        keyword_str = " OR ".join(f'"{kw}"' for kw in keywords[:3])
        search_query = f"(site:twitter.com OR site:x.com) {keyword_str}"

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            if "twitter.com" not in url and "x.com" not in url:
                continue

            title = r["title"]
            snippet = r["snippet"]
            combined = f"{title} {snippet}"

            # Extract author
            author = "unknown"
            match = re.search(r"(?:twitter|x)\.com/([^/?\s]+)", url)
            if match:
                author = f"@{match.group(1)}"

            tweet_text = re.sub(r"\s*(?:/\s*X|on\s+X|[\|–-]\s*(?:Twitter|X)).*$", "", title)

            signals = []
            for name, pattern in SIGNAL_PATTERNS.items():
                if pattern.search(combined):
                    signals.append(name)

            leads.append(PlatformLead(
                source="twitter",
                company_name=author,
                contact_name=author,
                description=f"{tweet_text}\n{snippet}",
                raw_url=url,
                signals=signals or ["twitter_mention"],
            ))

            if len(leads) >= max_results:
                break

        return leads
