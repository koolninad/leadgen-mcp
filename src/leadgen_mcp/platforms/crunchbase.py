"""Crunchbase crawling for recently funded startups via DuckDuckGo search."""

import re

from .base import PlatformCrawler, PlatformLead
from ..utils.search import web_search


SIGNAL_PATTERNS = {
    "recently_funded": re.compile(r"raised|funding|funded|investment|round", re.I),
    "seed_stage": re.compile(r"seed\s+(round|funding|stage)|pre-seed", re.I),
    "series_a": re.compile(r"series\s+a", re.I),
    "has_budget": re.compile(r"\$[\d,.]+[mkb]|\$[\d,]+\s*(million|billion)", re.I),
}

FUNDING_AMOUNT_RE = re.compile(
    r"\$\s*([\d,.]+)\s*(k|m|mm|b|million|billion|thousand)?", re.I
)


class CrunchbaseCrawler(PlatformCrawler):
    platform_name = "crunchbase"
    rate_limit = 2.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Search Crunchbase for recently funded startups via DuckDuckGo search."""
        keywords = query.get("keywords", [])
        stage = query.get("stage", "")  # seed, series-a, series-b
        industry = query.get("industry", "")
        max_results = query.get("max_results", 20)

        # Build search query for Crunchbase
        parts = ['site:crunchbase.com']

        if stage:
            parts.append(f'"{stage}"')
        else:
            parts.append('"seed" OR "series a" OR "series b"')

        parts.append("raised")

        if industry:
            parts.append(f'"{industry}"')

        if keywords:
            kw_str = " OR ".join(f'"{kw}"' for kw in keywords)
            parts.append(kw_str)

        # Add recent years
        parts.append("2024 OR 2025 OR 2026")

        search_query = " ".join(parts)
        results = await web_search(search_query, max_results=max_results)

        # Fallback: broader search without site: restriction
        if not results:
            fallback_query = f"startup funded {stage or 'seed'} {industry or 'software'} 2026 raised"
            results = await web_search(fallback_query, max_results=max_results)

        leads = []
        for r in results:
            url = r["url"]
            title = r["title"]
            snippet = r["snippet"]

            # Accept results from crunchbase OR general funding news
            if any(skip in url for skip in ["google.", "facebook.", "twitter.", "linkedin."]):
                continue

            combined_text = f"{title} {snippet}"

            # Extract company name from title — pattern: "Company Name - Crunchbase"
            company_name = re.sub(r"\s*[\|–-]\s*Crunchbase.*$", "", title).strip()

            # Extract funding amount
            budget = self._extract_funding_amount(combined_text)

            # Detect signals
            signals = []
            for signal_name, pattern in SIGNAL_PATTERNS.items():
                if pattern.search(combined_text):
                    signals.append(signal_name)

            # Try to extract domain from snippet
            domain = None
            domain_match = re.search(
                r"(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", snippet
            )
            if domain_match:
                d = domain_match.group(1)
                if "crunchbase.com" not in d:
                    domain = d

            leads.append(PlatformLead(
                source="crunchbase",
                company_name=company_name,
                domain=domain,
                description=f"{title}\n{snippet}",
                budget_estimate=budget,
                raw_url=url,
                industry=industry or None,
                signals=signals or ["crunchbase_listing"],
            ))

            if len(leads) >= max_results:
                break

        return leads

    @staticmethod
    def _extract_funding_amount(text: str) -> int | None:
        """Try to extract a dollar funding amount from text."""
        match = FUNDING_AMOUNT_RE.search(text)
        if not match:
            return None
        amount_str = match.group(1).replace(",", "")
        try:
            amount = float(amount_str)
        except ValueError:
            return None

        multiplier_str = (match.group(2) or "").lower()
        multiplier_map = {
            "k": 1_000, "thousand": 1_000,
            "m": 1_000_000, "mm": 1_000_000, "million": 1_000_000,
            "b": 1_000_000_000, "billion": 1_000_000_000,
        }
        multiplier = multiplier_map.get(multiplier_str, 1)
        return int(amount * multiplier)
