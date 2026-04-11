"""SAM.gov — US Federal tenders. Free REST API."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..models import Tender

logger = logging.getLogger("tenders.sam_gov")

API_BASE = "https://api.sam.gov/opportunities/v2/search"
IT_NAICS = ["541511", "541512", "541513", "541519", "518210", "519130", "511210"]
KEYWORDS = [
    "software development", "web application", "cloud computing",
    "cybersecurity", "IT services", "data analytics", "artificial intelligence",
    "mobile application", "digital transformation", "hosting services",
]


async def crawl(days_back: int = 14, max_results: int = 30) -> list[Tender]:
    """Search SAM.gov Opportunities API."""
    tenders = []
    posted_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%m/%d/%Y")

    for keyword in KEYWORDS[:5]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_BASE, params={
                    "api_key": "DEMO_KEY",
                    "postedFrom": posted_from,
                    "keyword": keyword,
                    "ptype": "o",
                    "limit": min(max_results, 25),
                })
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for opp in data.get("opportunitiesData", []):
                    title = opp.get("title", "")
                    dept = opp.get("fullParentPathName", "")
                    sol_num = opp.get("solicitationNumber", "")
                    deadline = opp.get("responseDeadLine", "")
                    posted = opp.get("postedDate", "")
                    ui_link = opp.get("uiLink", f"https://sam.gov/opp/{opp.get('noticeId', '')}/view")
                    naics = opp.get("naicsCode", "")
                    set_aside = opp.get("typeOfSetAside", "")
                    desc = opp.get("description", "")

                    # Extract contact
                    contact = opp.get("pointOfContact", [{}])
                    contact_name = contact[0].get("fullName", "") if contact else ""
                    contact_email = contact[0].get("email", "") if contact else ""
                    contact_phone = contact[0].get("phone", "") if contact else ""

                    tenders.append(Tender(
                        title=title[:200],
                        organization=dept,
                        country="USA",
                        source="sam_gov",
                        source_url=ui_link,
                        description=desc[:500] if desc else f"NAICS: {naics}. {set_aside}",
                        reference_number=sol_num,
                        deadline=deadline,
                        published_date=posted,
                        category="IT Services",
                        contact_name=contact_name,
                        contact_email=contact_email,
                        contact_phone=contact_phone,
                        raw_data=opp,
                    ))

        except Exception as e:
            logger.warning("SAM.gov search failed for '%s': %s", keyword, e)

        if len(tenders) >= max_results:
            break

    logger.info("SAM.gov: found %d tenders", len(tenders))
    return tenders[:max_results]
