"""Southeast Asia tender sources — Singapore, Philippines, Malaysia, Thailand.

GeBIZ is XHTML, PhilGEPS is SPA. Use SearXNG as primary strategy.
"""

import logging
import re

from ..models import Tender
from .common import is_it_tender, search_tenders_via_searxng

logger = logging.getLogger("tenders.southeast_asia")

SEARCH_QUERIES = [
    # Singapore
    'site:gebiz.gov.sg tender software IT 2026',
    'Singapore government tender IT services software cloud 2026',
    'Singapore tender cybersecurity hosting technology 2026',
    # Philippines
    'site:philgeps.gov.ph tender IT software 2026',
    'Philippines government tender software development 2026',
    # Malaysia
    'Malaysia government tender IT services software 2026',
    'site:myprocurement.gov.my tender technology',
    # Thailand
    'Thailand government tender IT software development 2026',
    # General ASEAN
    'ASEAN government tender software cloud hosting 2026',
]

COUNTRY_PATTERNS = {
    "singapore": "Singapore", "gebiz": "Singapore",
    "philippines": "Philippines", "philgeps": "Philippines", "manila": "Philippines",
    "malaysia": "Malaysia", "kuala lumpur": "Malaysia",
    "thailand": "Thailand", "bangkok": "Thailand",
    "indonesia": "Indonesia", "jakarta": "Indonesia",
    "vietnam": "Vietnam", "hanoi": "Vietnam",
}


def _detect_country(text: str) -> str:
    text_lower = text.lower()
    for pattern, country in COUNTRY_PATTERNS.items():
        if pattern in text_lower:
            return country
    return "Southeast Asia"


async def crawl(max_results: int = 25) -> list[Tender]:
    """Find SE Asia IT tenders via SearXNG."""
    tenders = []
    seen_urls = set()

    for query in SEARCH_QUERIES:
        try:
            results = await search_tenders_via_searxng(query, max_results=8)
            for r in results:
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("content", "")

                if url in seen_urls or not title:
                    continue
                seen_urls.add(url)

                combined = f"{title} {snippet}".lower()
                if not is_it_tender(combined):
                    continue

                if any(skip in url for skip in ["/search", "/category", "page="]):
                    continue

                country = _detect_country(f"{title} {snippet} {url}")

                deadline = ""
                date_match = re.search(r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', snippet)
                if date_match:
                    deadline = date_match.group(1)

                amount = ""
                for curr in ["SGD", "PHP", "MYR", "THB", "USD"]:
                    amt_match = re.search(rf'{curr}\s*([\d,.]+)', snippet, re.I)
                    if amt_match:
                        amount = f"{curr} {amt_match.group(1)}"
                        break

                source_map = {
                    "gebiz.gov.sg": "gebiz_sg", "philgeps.gov.ph": "philgeps",
                    "myprocurement.gov.my": "malaysia_proc",
                }
                source = "se_asia_search"
                for domain, src in source_map.items():
                    if domain in url:
                        source = src
                        break

                org = f"{country} Government"
                org_match = re.search(r'(?:Ministry|Department|Authority|Agency)\s+(?:of\s+)?[\w\s]+', f"{title} {snippet}", re.I)
                if org_match:
                    org = org_match.group(0).strip()[:100]

                tenders.append(Tender(
                    title=title[:200],
                    organization=org,
                    country=country,
                    source=source,
                    source_url=url,
                    description=snippet[:300],
                    amount=amount,
                    deadline=deadline,
                    category="IT Services",
                ))

                if len(tenders) >= max_results:
                    break

        except Exception as e:
            logger.debug("SE Asia search failed: %s", e)

        if len(tenders) >= max_results:
            break

    logger.info("Southeast Asia (via search): found %d IT tenders", len(tenders))
    return tenders[:max_results]
