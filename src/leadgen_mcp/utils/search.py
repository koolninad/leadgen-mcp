"""Web search utility with SearXNG (primary) and DuckDuckGo HTML (fallback).

SearXNG is a self-hosted meta-search engine that aggregates results from
multiple search engines. When unavailable, we fall back to DuckDuckGo's
HTML endpoint which requires no API key.
"""

import logging
import re
from urllib.parse import unquote, urlencode, urlparse, parse_qs

from bs4 import BeautifulSoup

from ..config import settings
from .http import create_client
from .throttle import TokenBucket

logger = logging.getLogger(__name__)

_bucket_ddg = TokenBucket(rate=2.0 / 60, capacity=1.0)  # 2 searches/min for DDG
_bucket_searxng = TokenBucket(rate=10.0 / 60, capacity=3.0)  # 10 searches/min for self-hosted


# ---------------------------------------------------------------------------
# SearXNG health check
# ---------------------------------------------------------------------------

async def check_searxng() -> dict:
    """Check if SearXNG instance is available.

    Returns dict with keys:
        available (bool): whether the instance responded
        url (str): the configured SearXNG URL
        error (str | None): error message if unavailable
    """
    base_url = settings.searxng_url.rstrip("/")
    try:
        async with create_client(timeout=5.0, use_ipv6=False) as client:
            resp = await client.get(f"{base_url}/healthz")
            if resp.status_code == 200:
                return {"available": True, "url": base_url, "error": None}
            # Some SearXNG versions don't have /healthz — try a quick search
            resp = await client.get(
                f"{base_url}/search",
                params={"q": "test", "format": "json"},
            )
            if resp.status_code == 200:
                return {"available": True, "url": base_url, "error": None}
            return {
                "available": False,
                "url": base_url,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as exc:
        return {"available": False, "url": base_url, "error": str(exc)}


# ---------------------------------------------------------------------------
# SearXNG search
# ---------------------------------------------------------------------------

async def _search_searxng(
    query: str,
    max_results: int = 20,
    categories: str = "general",
    engines: str | None = None,
    time_range: str | None = None,
    language: str = "en",
) -> list[dict]:
    """Search via SearXNG JSON API.

    Returns list of {title, url, snippet}.
    Raises on connection/HTTP errors so the caller can fall back.
    """
    await _bucket_searxng.acquire()

    base_url = settings.searxng_url.rstrip("/")
    params: dict = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": language,
        "pageno": 1,
    }
    if engines:
        params["engines"] = engines
    if time_range and time_range in ("day", "week", "month", "year"):
        params["time_range"] = time_range

    results: list[dict] = []

    async with create_client(timeout=15.0, use_ipv6=False) as client:
        resp = await client.get(f"{base_url}/search", params=params)
        resp.raise_for_status()
        data = resp.json()

    for item in data.get("results", []):
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        snippet = item.get("content", "").strip()

        if not url:
            continue

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break

    return results


# ---------------------------------------------------------------------------
# DuckDuckGo HTML fallback
# ---------------------------------------------------------------------------

async def _search_ddg(query: str, max_results: int = 20) -> list[dict]:
    """Search using DuckDuckGo HTML endpoint. Returns list of {title, url, snippet}."""
    await _bucket_ddg.acquire()

    url = f"https://html.duckduckgo.com/html/?q={query}"

    async with create_client(timeout=20.0) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for item in soup.select(".result"):
        # Title and URL
        link = item.select_one(".result__a")
        if not link:
            continue

        title = link.get_text(strip=True)
        raw_href = link.get("href", "")

        # DuckDuckGo wraps URLs in a redirect — extract the real URL
        real_url = _extract_ddg_url(raw_href)
        if not real_url or "duckduckgo.com" in real_url:
            continue

        # Snippet
        snippet_el = item.select_one(".result__snippet")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        results.append({
            "title": title,
            "url": real_url,
            "snippet": snippet,
        })

        if len(results) >= max_results:
            break

    return results


def _extract_ddg_url(href: str) -> str | None:
    """Extract real URL from DuckDuckGo redirect wrapper."""
    if not href:
        return None

    # Pattern: //duckduckgo.com/l/?uddg=https%3A%2F%2F...
    if "uddg=" in href:
        parsed = parse_qs(urlparse(href).query)
        urls = parsed.get("uddg", [])
        if urls:
            return unquote(urls[0])

    # Direct URL
    if href.startswith("http"):
        return href

    return None


# ---------------------------------------------------------------------------
# Unified search entry-point
# ---------------------------------------------------------------------------

async def web_search(
    query: str,
    max_results: int = 20,
    categories: str = "general",
    engines: str | None = None,
    time_range: str | None = None,
    language: str = "en",
) -> list[dict]:
    """Search using SearXNG (primary) or DuckDuckGo (fallback).

    Returns list of {title, url, snippet}.
    """
    # Try SearXNG first if enabled
    if settings.searxng_enabled:
        try:
            results = await _search_searxng(
                query,
                max_results=max_results,
                categories=categories,
                engines=engines,
                time_range=time_range,
                language=language,
            )
            if results:
                logger.debug("SearXNG returned %d results for: %s", len(results), query)
                return results
            logger.warning("SearXNG returned 0 results for: %s", query)
        except Exception as exc:
            logger.warning("SearXNG unavailable (%s), trying fallback", exc)

    # Fallback to DuckDuckGo
    if settings.search_fallback_ddg or not settings.searxng_enabled:
        logger.debug("Using DuckDuckGo fallback for: %s", query)
        return await _search_ddg(query, max_results=max_results)

    logger.error("SearXNG failed and DDG fallback is disabled — no results for: %s", query)
    return []


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

def register_search_tools(mcp):
    @mcp.tool()
    async def search_web(
        query: str,
        max_results: int = 20,
        engines: str | None = None,
    ) -> dict:
        """Search the web using SearXNG or DuckDuckGo fallback.

        Args:
            query: Search query
            max_results: Maximum results
            engines: Comma-separated engine names (google,bing,reddit)
        """
        results = await web_search(query, max_results=max_results, engines=engines)
        return {"query": query, "total": len(results), "results": results}

    @mcp.tool()
    async def search_status() -> dict:
        """Check if the SearXNG search instance is available."""
        return await check_searxng()
