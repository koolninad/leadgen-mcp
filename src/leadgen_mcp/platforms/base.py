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
        """Crawl with error handling."""
        try:
            return await self.crawl(query)
        except Exception as e:
            return [PlatformLead(
                source=self.platform_name,
                company_name="ERROR",
                description=f"Crawl failed: {str(e)}",
            )]
