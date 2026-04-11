"""Abstract base class for platform crawlers."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..utils.http import create_client, random_ua
from ..utils.throttle import Semaphore, TokenBucket
from ..config import settings


@dataclass
class PlatformLead:
    source: str
    company_name: str
    domain: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    description: str = ""
    budget_estimate: int | None = None
    signals: list[str] = field(default_factory=list)
    raw_url: str = ""
    location: str | None = None
    industry: str | None = None
    company_size: str | None = None
    skills_needed: list[str] = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "company_name": self.company_name,
            "domain": self.domain,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "description": self.description,
            "budget_estimate": self.budget_estimate,
            "signals": self.signals,
            "raw_url": self.raw_url,
            "location": self.location,
            "industry": self.industry,
            "company_size": self.company_size,
            "skills_needed": self.skills_needed,
            "scraped_at": self.scraped_at,
        }


class PlatformCrawler(ABC):
    """Base class for all platform crawlers."""

    platform_name: str = "unknown"
    rate_limit: float = 2.0  # requests per minute
    max_concurrency: int = 3

    def __init__(self):
        self._bucket = TokenBucket(self.rate_limit / 60.0, 1.0)

    async def _throttled_fetch(self, url: str, headers: dict | None = None) -> str:
        """Fetch a URL with rate limiting and concurrency control."""
        await self._bucket.acquire()
        sem = Semaphore.get(f"platform_{self.platform_name}", self.max_concurrency)
        async with sem:
            async with create_client(timeout=30.0) as client:
                if headers:
                    resp = await client.get(url, headers=headers)
                else:
                    resp = await client.get(url)
                resp.raise_for_status()
                return resp.text

    async def _crawl4ai_fetch(self, url: str, wait_for: str | None = None) -> str:
        """Fetch a URL using Crawl4AI for JS-rendered pages."""
        await self._bucket.acquire()
        sem = Semaphore.get(f"platform_{self.platform_name}", self.max_concurrency)
        async with sem:
            try:
                from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

                browser_cfg = BrowserConfig(headless=True, verbose=False)
                run_cfg = CrawlerRunConfig(
                    wait_until="networkidle",
                    page_timeout=30000,
                )

                async with AsyncWebCrawler(config=browser_cfg) as crawler:
                    result = await crawler.arun(url=url, config=run_cfg)
                    if result.success:
                        return result.html
                    raise RuntimeError(f"Crawl4AI failed: {result.error_message}")
            except ImportError:
                # Fallback to httpx if Crawl4AI not available
                return await self._throttled_fetch(url)

    @abstractmethod
    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Execute crawl with given query parameters. Must be implemented by subclasses."""
        ...

    async def safe_crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl with error handling + SearXNG fallback for blocked sites."""
        try:
            results = await self.crawl(query)
            if results:
                return results
        except Exception:
            pass

        # Fallback: search via SearXNG for this platform's leads
        try:
            return await self._searxng_fallback(query)
        except Exception:
            return []

    async def _searxng_fallback(self, query: dict) -> list[PlatformLead]:
        """Generic SearXNG fallback when direct crawling fails."""
        import re
        from ..utils.search import web_search

        keywords = query.get("keywords", ["software developer"])
        max_results = query.get("max_results", 10)

        # Platform-specific search queries
        platform_queries = {
            "upwork": "site:upwork.com software development project",
            "clutch": "site:clutch.co software development company",
            "producthunt": "site:producthunt.com new product launch 2026",
            "yellowpages": "yellowpages.com software services business",
            "private_tenders": "tender software development IT services 2026",
        }

        search_query = platform_queries.get(
            self.platform_name,
            f"{self.platform_name} {' '.join(keywords[:2])}"
        )

        results = await web_search(search_query, max_results=max_results)
        leads = []

        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", r.get("content", ""))

            if not title or any(skip in url for skip in ["google.", "facebook.", "wikipedia."]):
                continue

            # Extract domain
            domain = None
            domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
            if domain_match:
                d = domain_match.group(1)
                if self.platform_name not in d and "upwork" not in d and "clutch" not in d:
                    domain = d

            company = re.sub(r"\s*[\|–-]\s*(Upwork|Clutch|Product Hunt|Yellow Pages).*$", "", title).strip()

            leads.append(PlatformLead(
                source=self.platform_name,
                company_name=company[:80],
                domain=domain,
                description=snippet[:200] if snippet else title,
                raw_url=url,
                signals=[f"{self.platform_name}_search"],
            ))

            if len(leads) >= max_results:
                break

        return leads
