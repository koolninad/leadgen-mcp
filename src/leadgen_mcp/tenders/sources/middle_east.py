"""Middle East tender sources — UAE, Saudi, Oman, Bahrain, Qatar, Kuwait.

All government portals are SPAs requiring JS rendering.
Strategy: Use SearXNG to find active tenders from these portals.
"""

import logging
import re

from ..models import Tender
from .common import is_it_tender, search_tenders_via_searxng

logger = logging.getLogger("tenders.middle_east")

SEARCH_QUERIES = [
    # UAE
    'UAE government tender IT software cloud 2026',
    'site:mof.gov.ae tender technology digital',
    '"Abu Dhabi" OR "Dubai" tender software development 2026',
    # Saudi Arabia
    'Saudi Arabia government tender IT software 2026',
    'site:etimad.sa tender technology',
    '"saudi" tender software cloud hosting 2026',
    # Oman
    'Oman tender IT services software 2026',
    'site:tenderboard.gov.om technology',
    # Bahrain
    'Bahrain tender IT software development 2026',
    # Qatar
    'Qatar government tender IT technology software 2026',
    # Kuwait
    'Kuwait government tender IT services technology 2026',
    # General Gulf
    'GCC government tender software development cloud 2026',
    'Middle East tender IT services hosting cybersecurity 2026',
]

COUNTRY_PATTERNS = {
    "uae": "UAE", "abu dhabi": "UAE", "dubai": "UAE", "emirates": "UAE",
    "saudi": "Saudi Arabia", "riyadh": "Saudi Arabia", "etimad": "Saudi Arabia",
    "oman": "Oman", "muscat": "Oman",
    "bahrain": "Bahrain", "manama": "Bahrain",
    "qatar": "Qatar", "doha": "Qatar",
    "kuwait": "Kuwait",
}


def _detect_country(text: str) -> str:
    text_lower = text.lower()
    for pattern, country in COUNTRY_PATTERNS.items():
        if pattern in text_lower:
            return country
    return "Middle East"


async def crawl(max_results: int = 30) -> list[Tender]:
    """Find Middle East IT tenders via SearXNG."""
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

                # Skip aggregator listing pages
                if any(skip in url for skip in ["/search", "/category", "/listing", "page="]):
                    continue

                country = _detect_country(f"{title} {snippet} {url}")

                # Extract deadline
                deadline = ""
                date_match = re.search(r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', snippet)
                if date_match:
                    deadline = date_match.group(1)

                # Extract amount
                amount = ""
                for curr in ["USD", "AED", "SAR", "OMR", "BHD", "QAR", "KWD"]:
                    amt_match = re.search(rf'{curr}\s*([\d,.]+)', snippet, re.I)
                    if amt_match:
                        amount = f"{curr} {amt_match.group(1)}"
                        break

                # Determine source
                source_map = {
                    "mof.gov.ae": "uae_mof", "etimad.sa": "saudi_etimad",
                    "tenderboard.gov.om": "oman_tender", "tenderboard.gov.bh": "bahrain_tender",
                }
                source = "middle_east_search"
                for domain, src in source_map.items():
                    if domain in url:
                        source = src
                        break

                # Extract org
                org = f"{country} Government"
                org_match = re.search(r'(?:Ministry|Department|Authority|Commission|Corporation)\s+(?:of\s+)?[\w\s]+', f"{title} {snippet}", re.I)
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
            logger.debug("ME search failed for '%s': %s", query[:30], e)

        if len(tenders) >= max_results:
            break

    logger.info("Middle East (via search): found %d IT tenders", len(tenders))
    return tenders[:max_results]
