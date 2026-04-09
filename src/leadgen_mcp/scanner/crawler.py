"""Web crawler using Crawl4AI for browser-based crawling with httpx fallback."""

import asyncio
import time
from dataclasses import dataclass, field

from ..utils.http import create_client, random_ua
from ..utils.robots import can_crawl
from ..utils.throttle import Semaphore
from ..config import settings


@dataclass
class CrawlResult:
    url: str
    status_code: int = 0
    html: str = ""
    headers: dict = field(default_factory=dict)
    load_time_ms: float = 0
    error: str | None = None
    success: bool = False


async def crawl_url(url: str, respect_robots: bool = True) -> CrawlResult:
    """Crawl a single URL. Tries Crawl4AI first, falls back to httpx."""
    if respect_robots and not await can_crawl(url):
        return CrawlResult(url=url, error="Blocked by robots.txt")

    sem = Semaphore.get("scanner", settings.max_scan_concurrency)
    async with sem:
        # Try Crawl4AI for JS-rendered pages
        try:
            return await _crawl_with_crawl4ai(url)
        except Exception:
            pass

        # Fallback to httpx for static pages
        return await _crawl_with_httpx(url)


async def _crawl_with_crawl4ai(url: str) -> CrawlResult:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    run_cfg = CrawlerRunConfig(
        wait_until="networkidle",
        page_timeout=30000,
    )

    start = time.monotonic()
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    elapsed = (time.monotonic() - start) * 1000

    if result.success:
        return CrawlResult(
            url=url,
            status_code=result.status_code,
            html=result.html,
            headers=dict(result.response_headers) if result.response_headers else {},
            load_time_ms=elapsed,
            success=True,
        )
    return CrawlResult(url=url, error=f"Crawl4AI failed: {result.error_message}")


async def _crawl_with_httpx(url: str) -> CrawlResult:
    start = time.monotonic()
    async with create_client(timeout=30.0) as client:
        resp = await client.get(url)
    elapsed = (time.monotonic() - start) * 1000

    return CrawlResult(
        url=url,
        status_code=resp.status_code,
        html=resp.text,
        headers=dict(resp.headers),
        load_time_ms=elapsed,
        success=resp.status_code < 400,
    )


async def crawl_batch(urls: list[str], concurrency: int = 10) -> list[CrawlResult]:
    """Crawl multiple URLs concurrently."""
    sem = asyncio.Semaphore(concurrency)

    async def _limited_crawl(url: str) -> CrawlResult:
        async with sem:
            try:
                return await crawl_url(url)
            except Exception as e:
                return CrawlResult(url=url, error=str(e))

    return await asyncio.gather(*[_limited_crawl(u) for u in urls])
