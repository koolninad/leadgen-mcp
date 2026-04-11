"""EU TED — Tenders Electronic Daily. API v3 is dead, use SearXNG + HTML scrape."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender
from .common import is_it_tender, search_tenders_via_searxng

logger = logging.getLogger("tenders.eu_ted")

SEARCH_QUERIES = [
    'site:ted.europa.eu software development 2026',
    'site:ted.europa.eu IT services cloud 2026',
    'site:ted.europa.eu cybersecurity hosting 2026',
    'EU tender software development 2026 active',
    'European Union tender IT services cloud hosting 2026',
]

EU_COUNTRIES = {
    "germany": "Germany", "france": "France", "spain": "Spain", "italy": "Italy",
    "netherlands": "Netherlands", "belgium": "Belgium", "austria": "Austria",
    "sweden": "Sweden", "denmark": "Denmark", "finland": "Finland",
    "portugal": "Portugal", "ireland": "Ireland", "poland": "Poland",
    "czech": "Czech Republic", "romania": "Romania", "greece": "Greece",
}


def _detect_eu_country(text: str) -> str:
    text_lower = text.lower()
    for pattern, country in EU_COUNTRIES.items():
        if pattern in text_lower:
            return country
    return "EU"


async def crawl(days_back: int = 14, max_results: int = 20) -> list[Tender]:
    """Find EU IT tenders via SearXNG."""
    tenders = []
    seen_urls = set()

    for query in SEARCH_QUERIES:
        try:
            results = await search_tenders_via_searxng(query, max_results=10)
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

                if any(skip in url for skip in ["/search", "result?", "page="]):
                    continue

                country = _detect_eu_country(f"{title} {snippet}")

                deadline = ""
                date_match = re.search(r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', snippet)
                if date_match:
                    deadline = date_match.group(1)

                amount = ""
                amt_match = re.search(r'(?:EUR|€)\s*([\d,.]+)', snippet, re.I)
                if amt_match:
                    amount = f"EUR {amt_match.group(1)}"

                org = "EU Government"
                org_match = re.search(r'(?:Ministry|Commission|Agency|Authority|Council|Department)\s+(?:of\s+)?[\w\s]+', f"{title} {snippet}", re.I)
                if org_match:
                    org = org_match.group(0).strip()[:100]

                source = "eu_ted_search" if "ted.europa.eu" in url else "eu_search"

                tenders.append(Tender(
                    title=title[:200],
                    organization=org,
                    country=country,
                    source=source,
                    source_url=url,
                    description=snippet[:300],
                    amount=amount,
                    currency="EUR",
                    deadline=deadline,
                    category="IT Services",
                ))

                if len(tenders) >= max_results:
                    break

        except Exception as e:
            logger.debug("EU TED search failed: %s", e)

        if len(tenders) >= max_results:
            break

    logger.info("EU TED (via search): found %d IT tenders", len(tenders))
    return tenders[:max_results]
