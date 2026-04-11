"""SAM.gov — US Federal tenders via internal search API (no API key needed).

Uses SAM.gov's internal search endpoint (same as their website).
No rate limits, no API key required.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..models import Tender
from .common import is_it_tender

logger = logging.getLogger("tenders.sam_gov")

# Internal SAM.gov search API (no key needed)
API_BASE = "https://sam.gov/api/prod/sgs/v1/search/"

KEYWORDS = [
    "software development", "IT services", "cloud computing",
    "cybersecurity", "web application", "hosting services",
    "blockchain", "DevOps", "data analytics",
    "digital transformation", "artificial intelligence",
]


async def crawl(days_back: int = 14, max_results: int = 30) -> list[Tender]:
    """Search SAM.gov via internal API (no API key needed)."""
    tenders = []
    seen_ids = set()

    for keyword in KEYWORDS[:6]:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                # Request active opportunities, sort by response date
                tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%m/%d/%Y")
                resp = await client.get(API_BASE, params={
                    "index": "opp",
                    "q": keyword,
                    "page": 0,
                    "size": min(max_results * 2, 50),  # fetch extra, filter later
                    "mode": "search",
                    "is_active": "true",
                    "sort": "-responseDate",  # newest deadlines first
                }, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/hal+json",
                })

                if resp.status_code != 200:
                    logger.debug("SAM.gov %d for '%s'", resp.status_code, keyword)
                    continue

                data = resp.json()
                results = data.get("_embedded", {}).get("results", [])

                for opp in results:
                    title = opp.get("title", "")
                    sol_num = opp.get("solicitationNumber", "")

                    # Dedup
                    if sol_num in seen_ids:
                        continue
                    seen_ids.add(sol_num)

                    # Only active
                    if not opp.get("isActive", True):
                        continue

                    deadline = opp.get("responseDate", "")
                    if deadline and "T" in deadline:
                        deadline = deadline[:10]

                    # Skip expired tenders
                    if deadline:
                        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        if deadline < today:
                            continue

                    published = opp.get("publishDate", "")
                    if published and "T" in published:
                        published = published[:10]

                    opp_type = opp.get("type", {})
                    type_desc = opp_type.get("value", "") if isinstance(opp_type, dict) else str(opp_type)

                    # Get description
                    descriptions = opp.get("descriptions", [])
                    desc = ""
                    if descriptions and isinstance(descriptions, list):
                        desc = descriptions[0].get("content", "")[:500] if isinstance(descriptions[0], dict) else str(descriptions[0])[:500]

                    # Try to get organization from the opp data
                    org = opp.get("organizationHierarchy", opp.get("department", "US Federal Government"))
                    if isinstance(org, list) and org:
                        org = org[0].get("name", "US Federal Government") if isinstance(org[0], dict) else str(org[0])
                    elif isinstance(org, dict):
                        org = org.get("name", "US Federal Government")

                    # Build SAM.gov link
                    notice_id = opp.get("noticeId", sol_num)
                    ui_link = f"https://sam.gov/opp/{notice_id}/view" if notice_id else "https://sam.gov/search"

                    tenders.append(Tender(
                        title=title[:200],
                        organization=str(org)[:200],
                        country="USA",
                        source="sam_gov",
                        source_url=ui_link,
                        description=desc if desc else f"Type: {type_desc}. Sol#: {sol_num}",
                        reference_number=sol_num,
                        deadline=deadline,
                        published_date=published,
                        category="IT Services",
                        raw_data=opp,
                    ))

        except Exception as e:
            logger.warning("SAM.gov failed for '%s': %s", keyword, e)

        if len(tenders) >= max_results:
            break

    logger.info("SAM.gov: found %d tenders", len(tenders))
    return tenders[:max_results]
