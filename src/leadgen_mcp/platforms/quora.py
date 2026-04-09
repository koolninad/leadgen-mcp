"""Quora crawling for lead generation via DuckDuckGo search."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


SIGNAL_PATTERNS = {
    "looking_for_agency": re.compile(
        r"(best|top|good)\s+(software|web|app)\s+(agency|company|firm)|recommend.*agency", re.I
    ),
    "needs_app_built": re.compile(
        r"need\s+(an?\s+)?app\s+built|build\s+(an?\s+)?app|develop\s+(an?\s+)?app|cost\s+to\s+build", re.I
    ),
    "tech_question": re.compile(
        r"how\s+to\s+find\s+(a\s+)?developer|hire\s+(a\s+)?developer|find\s+(a\s+)?programmer", re.I
    ),
}


class QuoraCrawler(PlatformCrawler):
    platform_name = "quora"
    rate_limit = 2.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Search Quora for people asking about hiring developers or building apps."""
        keywords = query.get("keywords", [
            "how to find a developer",
            "best software agency",
            "need app built",
            "cost to build an app",
        ])
        max_results = query.get("max_results", 20)

        keyword_str = " OR ".join(f'"{kw}"' for kw in keywords)
        search_query = f"site:quora.com {keyword_str}"

        results = await web_search(search_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            if "quora.com" not in url:
                continue

            combined_text = f"{title} {snippet}"

            # Clean up title: remove " - Quora" suffix
            question = re.sub(r"\s*[\|–-]\s*Quora.*$", "", title).strip()

            # Detect signals
            signals = []
            for signal_name, pattern in SIGNAL_PATTERNS.items():
                if pattern.search(combined_text):
                    signals.append(signal_name)

            leads.append(PlatformLead(
                source="quora",
                company_name=question[:80],
                description=f"{question}\n{snippet}",
                raw_url=url,
                signals=signals or ["quora_question"],
            ))

            if len(leads) >= max_results:
                break

        return leads
