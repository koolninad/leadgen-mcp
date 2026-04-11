"""Tech debt scanner.

Detects websites running outdated technologies at scale.
Outdated tech = leads for Chandorkar Technologies (modernization).
"""

import logging
import re

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client, random_ua

logger = logging.getLogger("leadgen.platforms.tech_debt")

# Outdated tech patterns to detect in HTML/headers
OUTDATED_PATTERNS = {
    "jquery_1x": {
        "html": [re.compile(r"jquery[/-]1\.\d+", re.I)],
        "signal": "outdated_jquery",
        "description": "jQuery 1.x (end-of-life)",
    },
    "jquery_2x": {
        "html": [re.compile(r"jquery[/-]2\.\d+", re.I)],
        "signal": "outdated_jquery",
        "description": "jQuery 2.x (end-of-life)",
    },
    "bootstrap_2": {
        "html": [re.compile(r"bootstrap[/-]2\.\d+", re.I)],
        "signal": "outdated_bootstrap",
        "description": "Bootstrap 2.x",
    },
    "bootstrap_3": {
        "html": [re.compile(r"bootstrap[/-]3\.\d+", re.I)],
        "signal": "outdated_bootstrap",
        "description": "Bootstrap 3.x",
    },
    "angularjs": {
        "html": [re.compile(r"angular[./]1\.\d+", re.I), re.compile(r"ng-app", re.I)],
        "signal": "outdated_angularjs",
        "description": "AngularJS 1.x (end-of-life Dec 2021)",
    },
    "old_wordpress": {
        "html": [re.compile(r"wp-includes.*ver=[1-4]\.", re.I)],
        "signal": "outdated_wordpress",
        "description": "WordPress < 5.0",
    },
    "old_php": {
        "header": [re.compile(r"PHP/[5-7]\.[0-3]", re.I)],
        "signal": "outdated_php",
        "description": "PHP < 7.4 (end-of-life)",
    },
    "old_apache": {
        "header": [re.compile(r"Apache/2\.[0-2]", re.I)],
        "signal": "outdated_apache",
        "description": "Apache < 2.4",
    },
    "flash": {
        "html": [re.compile(r"application/x-shockwave-flash", re.I), re.compile(r"\.swf", re.I)],
        "signal": "uses_flash",
        "description": "Adobe Flash (discontinued 2020)",
    },
    "http_only": {
        "signal": "no_https",
        "description": "Site not using HTTPS",
    },
    "no_viewport": {
        "signal": "not_mobile_friendly",
        "description": "Missing viewport meta (not mobile-friendly)",
    },
}


class TechDebtCrawler(PlatformCrawler):
    platform_name = "tech_debt"
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

        for url in urls[:max_results * 2]:
            try:
                issues = await self._scan_url(url)
                if issues:
                    domain = None
                    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if match:
                        domain = match.group(1)

                    signals = list({i["signal"] for i in issues})
                    if len(issues) >= 3:
                        signals.append("legacy_stack")

                    desc_parts = [i["description"] for i in issues[:5]]

                    leads.append(PlatformLead(
                        source="tech_debt",
                        company_name=domain or url,
                        domain=domain,
                        description=f"Tech debt detected: {', '.join(desc_parts)}",
                        signals=signals,
                        raw_url=url,
                    ))

            except Exception as e:
                logger.debug("Tech debt scan failed for %s: %s", url, e)

            if len(leads) >= max_results:
                break

        logger.info("Tech debt scanner: %d sites with outdated tech out of %d",
                     len(leads), len(urls))
        return leads[:max_results]

    async def _scan_url(self, url: str) -> list[dict]:
        """Scan a single URL for outdated technology."""
        issues = []

        # Check HTTPS
        if url.startswith("http://"):
            issues.append(OUTDATED_PATTERNS["http_only"])

        try:
            await self._bucket.acquire()
            async with create_client(timeout=15.0) as client:
                resp = await client.get(url, follow_redirects=True, headers={"User-Agent": random_ua()})
                if resp.status_code != 200:
                    return []

                html = resp.text
                headers_str = " ".join(f"{k}: {v}" for k, v in resp.headers.items())

                # Check HTML patterns
                for name, pattern in OUTDATED_PATTERNS.items():
                    if name in ("http_only", "no_viewport"):
                        continue
                    for regex in pattern.get("html", []):
                        if regex.search(html):
                            issues.append({"signal": pattern["signal"], "description": pattern["description"]})
                            break
                    for regex in pattern.get("header", []):
                        if regex.search(headers_str):
                            issues.append({"signal": pattern["signal"], "description": pattern["description"]})
                            break

                # Check viewport
                if "<meta" not in html.lower() or "viewport" not in html.lower():
                    issues.append(OUTDATED_PATTERNS["no_viewport"])

        except Exception as e:
            logger.debug("Scan error for %s: %s", url, e)

        return issues

    async def _find_urls(self, keywords: list[str], max_results: int) -> list[str]:
        from ..utils.search import web_search
        urls = []
        # Better queries that find actual business websites
        scan_queries = keywords if keywords != ["small business website"] else [
            "restaurant website .com",
            "law firm website contact",
            "dental clinic website book appointment",
            "real estate agency website listings",
            "plumber website near me",
            "salon website book online",
            "accounting firm website services",
            "construction company website projects",
            "auto repair shop website",
            "hotel website book room",
        ]
        for kw in scan_queries[:5]:
            try:
                results = await web_search(kw, max_results=max_results // max(len(scan_queries[:5]), 1))
                for r in results:
                    url = r.get("url", "")
                    if url.startswith("http") and not any(skip in url for skip in [
                        "google.", "facebook.", "yelp.", "yellowpages.", "wikipedia.",
                        "linkedin.", "twitter.", "instagram.", "youtube.", "amazon.",
                        "apple.", "microsoft.", "reddit.", "pinterest.",
                    ]):
                        urls.append(url)
            except Exception:
                pass
        return urls[:max_results]
