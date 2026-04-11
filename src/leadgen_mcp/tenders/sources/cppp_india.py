"""India tender sources — CPPP, GeM, State portals via SearXNG fallback.

CPPP has captcha protection, GeM is a SPA. Both are difficult to scrape directly.
Strategy: Use SearXNG to search for active IT tenders from Indian government portals.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender
from .common import is_it_tender, search_tenders_via_searxng

logger = logging.getLogger("tenders.india")

SEARCH_QUERIES = [
    # CPPP / eProcure
    '"eprocure.gov.in" tender software 2026',
    '"eprocure.gov.in" tender IT services 2026',
    '"eprocure.gov.in" tender cloud hosting 2026',
    # GeM
    'site:gem.gov.in bid software development 2026',
    'site:gem.gov.in bid IT services cloud 2026',
    # State portals
    'india government tender software development 2026 active',
    'india state tender IT services cloud hosting 2026',
    'india government tender cybersecurity blockchain 2026',
    # Aggregators
    'site:tendertiger.com india software development tender 2026',
    'site:bidassist.com software IT services tender 2026',
]


async def crawl_via_search(max_results: int = 30) -> list[Tender]:
    """Find Indian IT tenders via SearXNG search."""
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

                # Check if it's IT-related
                combined = f"{title} {snippet}".lower()
                if not is_it_tender(combined):
                    continue

                # Skip aggregator listing pages (not individual tenders)
                if any(skip in url for skip in ["/search", "/category", "/listing", "page="]):
                    continue

                # Extract deadline from snippet
                deadline = ""
                date_match = re.search(r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', snippet)
                if date_match:
                    deadline = date_match.group(1)

                # Extract amount
                amount = ""
                amt_match = re.search(r'(?:Rs\.?|INR|₹)\s*([\d,.]+)\s*(?:Cr|Lakh|crore|lakh)?', snippet, re.I)
                if amt_match:
                    amount = f"INR {amt_match.group(0)}"

                # Determine source
                source = "india_search"
                if "eprocure.gov.in" in url:
                    source = "cppp_india"
                elif "gem.gov.in" in url:
                    source = "gem_india"
                elif "tntenders" in url:
                    source = "india_tamil_nadu"
                elif "mahatenders" in url:
                    source = "india_maharashtra"
                elif "tendertiger" in url or "bidassist" in url:
                    source = "india_aggregator"

                # Extract org from title/snippet
                org = "Indian Government"
                org_patterns = [
                    r'(?:Ministry of|Department of|Directorate of|Office of)\s+[\w\s]+',
                    r'(?:Corporation|Authority|Board|Commission|Council)\s*(?:of\s+[\w\s]+)?',
                ]
                for pat in org_patterns:
                    org_match = re.search(pat, f"{title} {snippet}", re.I)
                    if org_match:
                        org = org_match.group(0).strip()[:100]
                        break

                tenders.append(Tender(
                    title=title[:200],
                    organization=org,
                    country="India",
                    source=source,
                    source_url=url,
                    description=snippet[:300],
                    amount=amount,
                    currency="INR",
                    deadline=deadline,
                    category="IT Services",
                ))

                if len(tenders) >= max_results:
                    break

        except Exception as e:
            logger.debug("India search failed for '%s': %s", query[:30], e)

        if len(tenders) >= max_results:
            break

    logger.info("India (via search): found %d IT tenders", len(tenders))
    return tenders[:max_results]


async def crawl(max_results: int = 30) -> list[Tender]:
    """Crawl Indian tender sources."""
    return await crawl_via_search(max_results)
