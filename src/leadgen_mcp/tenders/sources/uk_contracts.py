"""UK Contracts Finder — Free JSON API, no auth."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..models import Tender

logger = logging.getLogger("tenders.uk_contracts")

API_BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
KEYWORDS = [
    "software", "web development", "IT services", "cloud",
    "digital", "cybersecurity", "application", "hosting",
]


async def crawl(days_back: int = 14, max_results: int = 20) -> list[Tender]:
    """Search UK Contracts Finder OCDS API."""
    tenders = []
    published_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

    for keyword in KEYWORDS[:4]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Only get tenders closing in the future
                tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
                resp = await client.get(API_BASE, params={
                    "keyword": keyword,
                    "publishedFrom": published_from,
                    "closingDateFrom": tomorrow,
                    "size": min(max_results, 20),
                })
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for release in data.get("releases", []):
                    tender_data = release.get("tender", {})
                    title = tender_data.get("title", "")
                    desc = tender_data.get("description", "")
                    value = tender_data.get("value", {})
                    amount = value.get("amount")
                    currency = value.get("currency", "GBP")
                    buyer = release.get("buyer", {})
                    buyer_name = buyer.get("name", "")

                    # Contact
                    contact_point = buyer.get("contactPoint", {})
                    contact_name = contact_point.get("name", "")
                    contact_email = contact_point.get("email", "")
                    contact_phone = contact_point.get("telephone", "")

                    deadline = tender_data.get("tenderPeriod", {}).get("endDate", "")
                    published = release.get("date", "")
                    notice_id = release.get("id", "")

                    tenders.append(Tender(
                        title=title[:200],
                        organization=buyer_name,
                        country="UK",
                        source="uk_contracts",
                        source_url=f"https://www.contractsfinder.service.gov.uk/Notice/{notice_id}",
                        description=desc[:500],
                        amount=f"{currency} {amount:,.0f}" if amount else "",
                        currency=currency,
                        deadline=deadline[:10] if deadline else "",
                        published_date=published[:10] if published else "",
                        reference_number=notice_id,
                        category="IT Services",
                        contact_name=contact_name,
                        contact_email=contact_email,
                        contact_phone=contact_phone,
                        raw_data=release,
                    ))

        except Exception as e:
            logger.warning("UK Contracts failed for '%s': %s", keyword, e)

        if len(tenders) >= max_results:
            break

    logger.info("UK Contracts Finder: found %d tenders", len(tenders))
    return tenders[:max_results]
