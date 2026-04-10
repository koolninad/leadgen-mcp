"""Broken website detector.

Scans websites for dead links, SSL errors, timeouts, 5xx errors.
Uses lychee CLI if available, falls back to httpx-based checking.
Broken sites = leads for Chandorkar Technologies / HostingDuty.
"""

import asyncio
import json
import logging
import re

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client

logger = logging.getLogger("leadgen.platforms.broken_sites")


class BrokenSiteDetector(PlatformCrawler):
    platform_name = "broken_sites"
    rate_limit = 5.0
    max_concurrency = 5

    async def crawl(self, query: dict) -> list[PlatformLead]:
        urls = query.get("urls", [])
        max_results = query.get("max_results", 50)

        if not urls:
            keywords = query.get("keywords", [])
            if keywords:
                urls = await self._find_urls(keywords, max_results)

        if not urls:
            return []

        leads = []
        lychee_available = await self._check_lychee()

        for url in urls[:max_results * 2]:
            try:
                if lychee_available:
                    issues = await self._check_with_lychee(url)
                else:
                    issues = await self._check_with_httpx(url)

                if issues:
                    domain = None
                    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if match:
                        domain = match.group(1)

                    signals = ["broken_website"]
                    if any("ssl" in i.lower() or "certificate" in i.lower() for i in issues):
                        signals.append("ssl_expired")
                    if any("500" in i or "502" in i or "503" in i for i in issues):
                        signals.append("server_errors")
                    if any("timeout" in i.lower() for i in issues):
                        signals.append("site_timeout")

                    leads.append(PlatformLead(
                        source="broken_sites",
                        company_name=domain or url,
                        domain=domain,
                        description=f"Found {len(issues)} issues: " + "; ".join(issues[:3]),
                        signals=signals,
                        raw_url=url,
                    ))

            except Exception as e:
                logger.debug("Broken site check failed for %s: %s", url, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _check_lychee(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "lychee", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def _check_with_lychee(self, url: str) -> list[str]:
        """Check a URL using lychee CLI."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "lychee", url,
                "--format", "json",
                "--timeout", "10",
                "--max-redirects", "5",
                "--no-progress",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

            if stdout:
                data = json.loads(stdout.decode())
                issues = []
                for fail in data.get("fail_map", {}).values():
                    for item in fail:
                        status = item.get("status", {})
                        issues.append(f"{item.get('url', '')}: {status}")
                return issues
            return []
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            return []

    async def _check_with_httpx(self, url: str) -> list[str]:
        """Fallback: check URL and key pages with httpx."""
        issues = []
        try:
            await self._bucket.acquire()
            async with create_client(timeout=15.0) as client:
                resp = await client.get(url, follow_redirects=True)

                if resp.status_code >= 500:
                    issues.append(f"Server error: {resp.status_code}")
                elif resp.status_code == 404:
                    issues.append("Main page returns 404")

                # Check a few common pages
                for path in ["/about", "/contact", "/sitemap.xml"]:
                    try:
                        sub_resp = await client.get(f"{url.rstrip('/')}{path}", follow_redirects=True)
                        if sub_resp.status_code >= 500:
                            issues.append(f"{path}: {sub_resp.status_code}")
                    except Exception:
                        pass

        except Exception as e:
            err = str(e).lower()
            if "ssl" in err or "certificate" in err:
                issues.append(f"SSL error: {e}")
            elif "timeout" in err or "timed out" in err:
                issues.append("Connection timeout")
            else:
                issues.append(f"Connection error: {e}")

        return issues

    async def _find_urls(self, keywords: list[str], max_results: int) -> list[str]:
        from ..utils.search import search_web
        urls = []
        for kw in keywords[:3]:
            try:
                results = await search_web(kw, max_results=max_results // max(len(keywords), 1))
                for r in results:
                    url = r.get("url", "")
                    if url.startswith("http"):
                        urls.append(url)
            except Exception:
                pass
        return urls[:max_results]
