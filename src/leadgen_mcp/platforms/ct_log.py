"""Certificate Transparency Log crawler.

Monitors crt.sh for newly issued SSL certificates matching business keywords.
New SSL cert = someone building a website = potential lead.
"""

import json
import logging
import re
from urllib.parse import quote

from .base import PlatformCrawler, PlatformLead
from ..config import settings
from ..utils.http import create_client

logger = logging.getLogger("leadgen.platforms.ct_log")


class CTLogCrawler(PlatformCrawler):
    platform_name = "ct_log"
    rate_limit = 6.0  # crt.sh is rate-limited, be conservative
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        keywords = query.get("keywords", settings.ctlog_keyword_list)
        max_results = query.get("max_results", 50)
        leads = []

        for keyword in keywords[:5]:  # Limit to 5 keywords per run
            try:
                results = await self._query_crtsh(keyword, max_results=max_results // len(keywords))
                leads.extend(results)
            except Exception as e:
                logger.warning("crt.sh query failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        # Deduplicate by domain
        seen = set()
        unique = []
        for lead in leads:
            if lead.domain and lead.domain not in seen:
                seen.add(lead.domain)
                unique.append(lead)

        return unique[:max_results]

    async def _query_crtsh(self, keyword: str, max_results: int = 20) -> list[PlatformLead]:
        """Query crt.sh JSON API for certificates matching a keyword."""
        url = f"https://crt.sh/?q=%25{quote(keyword)}%25&output=json"

        await self._bucket.acquire()
        async with create_client(timeout=30.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

            try:
                data = resp.json()
            except Exception:
                return []

        leads = []
        seen_domains = set()

        for entry in data[:max_results * 2]:
            name_value = entry.get("name_value", "")
            # name_value can contain multiple domains separated by newlines
            for domain in name_value.split("\n"):
                domain = domain.strip().lower()
                # Skip wildcards and duplicates
                if domain.startswith("*."):
                    domain = domain[2:]
                if not domain or domain in seen_domains:
                    continue
                # Skip common/internal domains
                if any(skip in domain for skip in [
                    "localhost", "example.", "test.", "internal.",
                    "cloudflare", "amazonaws", "google", "microsoft",
                ]):
                    continue

                seen_domains.add(domain)
                issuer = entry.get("issuer_name", "")

                leads.append(PlatformLead(
                    source="ct_log",
                    company_name=domain.split(".")[0].replace("-", " ").title(),
                    domain=domain,
                    description=f"New SSL certificate issued for {domain}. Keyword match: {keyword}",
                    signals=["new_ssl_cert", "business_keyword_match"],
                    raw_url=f"https://crt.sh/?q={domain}",
                ))

                if len(leads) >= max_results:
                    break

        return leads
