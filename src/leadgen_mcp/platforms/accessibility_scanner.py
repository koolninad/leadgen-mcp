"""Bulk accessibility scanner.

Scans websites for WCAG/ADA compliance issues.
Uses pa11y CLI if available, falls back to Python-based checks.
Sites with accessibility violations = leads for Chandorkar Technologies.
"""

import asyncio
import json
import logging

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client

logger = logging.getLogger("leadgen.platforms.accessibility")


class AccessibilityScannerCrawler(PlatformCrawler):
    platform_name = "accessibility_scanner"
    rate_limit = 5.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        urls = query.get("urls", [])
        max_results = query.get("max_results", 50)

        if not urls:
            # If no URLs provided, try to get from keywords (search for sites to scan)
            keywords = query.get("keywords", [])
            if keywords:
                urls = await self._find_urls_to_scan(keywords, max_results)

        if not urls:
            logger.info("No URLs to scan for accessibility")
            return []

        leads = []
        pa11y_available = await self._check_pa11y()

        for url in urls[:max_results]:
            try:
                if pa11y_available:
                    issues = await self._scan_with_pa11y(url)
                else:
                    issues = await self._scan_with_python(url)

                if issues:
                    domain = None
                    import re
                    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if match:
                        domain = match.group(1)

                    critical = sum(1 for i in issues if i.get("type") == "error")
                    warnings = sum(1 for i in issues if i.get("type") == "warning")

                    signals = ["accessibility_violations"]
                    if critical >= 5:
                        signals.append("ada_non_compliant")
                    if critical >= 10:
                        signals.append("wcag_critical")

                    leads.append(PlatformLead(
                        source="accessibility_scanner",
                        company_name=domain or url,
                        domain=domain,
                        description=f"Found {critical} errors, {warnings} warnings. Top issues: "
                                    + "; ".join(i.get("message", "")[:60] for i in issues[:3]),
                        signals=signals,
                        raw_url=url,
                    ))

            except Exception as e:
                logger.warning("Accessibility scan failed for %s: %s", url, e)

        logger.info("Accessibility scanner: %d sites with issues out of %d scanned",
                     len(leads), len(urls))
        return leads

    async def _check_pa11y(self) -> bool:
        """Check if pa11y CLI is available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pa11y", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def _scan_with_pa11y(self, url: str) -> list[dict]:
        """Scan a URL using pa11y CLI."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pa11y", url,
                "--reporter", "json",
                "--timeout", "15000",
                "--standard", "WCAG2AA",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)

            if stdout:
                return json.loads(stdout.decode())
            return []
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
            logger.debug("pa11y scan failed for %s: %s", url, e)
            return []

    async def _scan_with_python(self, url: str) -> list[dict]:
        """Fallback: basic accessibility check using HTML parsing."""
        try:
            await self._bucket.acquire()
            async with create_client(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                html = resp.text
        except Exception:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        issues = []

        # Missing alt text on images
        for img in soup.find_all("img"):
            if not img.get("alt"):
                issues.append({"type": "error", "message": "Image missing alt text", "code": "WCAG2AA.H37"})

        # Missing form labels
        for inp in soup.find_all("input", {"type": lambda t: t not in ("hidden", "submit", "button")}):
            inp_id = inp.get("id")
            if inp_id and not soup.find("label", {"for": inp_id}):
                issues.append({"type": "error", "message": "Form input missing label", "code": "WCAG2AA.H44"})

        # Missing lang attribute
        html_tag = soup.find("html")
        if html_tag and not html_tag.get("lang"):
            issues.append({"type": "error", "message": "HTML missing lang attribute", "code": "WCAG2AA.H57"})

        # Empty links
        for a in soup.find_all("a"):
            if not a.get_text(strip=True) and not a.get("aria-label"):
                issues.append({"type": "warning", "message": "Empty link without aria-label", "code": "WCAG2AA.H30"})

        # Missing viewport meta
        if not soup.find("meta", {"name": "viewport"}):
            issues.append({"type": "warning", "message": "Missing viewport meta tag"})

        return issues

    async def _find_urls_to_scan(self, keywords: list[str], max_results: int) -> list[str]:
        """Search for URLs to scan using SearXNG."""
        from ..utils.search import web_search
        urls = []
        scan_queries = [f"{kw} website" for kw in keywords] if keywords else [
            "law firm website USA",
            "medical practice website",
            "restaurant website online order",
            "real estate website listings",
            "small business website services",
        ]
        for kw in scan_queries[:4]:
            try:
                results = await web_search(kw, max_results=max_results // max(len(scan_queries[:4]), 1))
                for r in results:
                    url = r.get("url", "")
                    if url.startswith("http") and not any(skip in url for skip in [
                        "google.", "facebook.", "yelp.", "wikipedia.", "linkedin.",
                        "twitter.", "instagram.", "youtube.", "amazon.", "reddit.",
                    ]):
                        urls.append(url)
            except Exception:
                pass
        return urls[:max_results]
