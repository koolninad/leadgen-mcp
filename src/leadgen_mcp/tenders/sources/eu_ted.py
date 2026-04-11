"""EU TED (Tenders Electronic Daily) — XML/JSON feeds."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..models import Tender

logger = logging.getLogger("tenders.eu_ted")

# TED API (new version)
API_BASE = "https://api.ted.europa.eu/v3"
SEARCH_URL = f"{API_BASE}/notices/search"

IT_CPV_CODES = [
    "72000000",  # IT services
    "72200000",  # Software programming
    "72300000",  # Data services
    "72400000",  # Internet services
    "48000000",  # Software packages
    "72210000",  # Programming of packaged software
    "72220000",  # Systems and technical consultancy
    "72260000",  # Software-related services
    "72310000",  # Data-processing
    "72500000",  # Computer-related services
]


async def crawl(days_back: int = 14, max_results: int = 20) -> list[Tender]:
    """Search EU TED for IT tenders."""
    tenders = []

    try:
        # TED Search API
        published_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d")

        async with httpx.AsyncClient(timeout=30) as client:
            # Try the search endpoint
            for cpv in IT_CPV_CODES[:3]:
                try:
                    resp = await client.get(
                        "https://ted.europa.eu/api/v3.0/notices/search",
                        params={
                            "q": f"cpv:{cpv}",
                            "pageSize": min(max_results, 10),
                            "pageNum": 1,
                            "scope": 3,  # Active notices
                        },
                        headers={"Accept": "application/json"},
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        notices = data.get("notices", data.get("results", []))

                        for notice in notices:
                            title = notice.get("title", notice.get("titleText", ""))
                            org = notice.get("buyerName", notice.get("organisationName", ""))
                            country = notice.get("country", notice.get("iso_country", "EU"))
                            deadline = notice.get("deadline", notice.get("submissionDeadline", ""))
                            pub_date = notice.get("publicationDate", "")
                            doc_id = notice.get("documentNumber", notice.get("noticeId", ""))
                            amount = notice.get("estimatedValue", "")

                            tenders.append(Tender(
                                title=title[:200] if isinstance(title, str) else str(title)[:200],
                                organization=org if isinstance(org, str) else str(org),
                                country=country if isinstance(country, str) else "EU",
                                source="eu_ted",
                                source_url=f"https://ted.europa.eu/en/notice/-/detail/{doc_id}" if doc_id else "https://ted.europa.eu",
                                description=f"EU TED Notice: {title}",
                                amount=str(amount) if amount else "",
                                currency="EUR",
                                deadline=str(deadline)[:10] if deadline else "",
                                published_date=str(pub_date)[:10] if pub_date else "",
                                reference_number=str(doc_id),
                                category="IT Services",
                            ))

                except Exception as e:
                    logger.debug("TED CPV search failed for %s: %s", cpv, e)

                if len(tenders) >= max_results:
                    break

            # Fallback: keyword search
            if not tenders:
                for keyword in ["software development", "IT services", "digital"]:
                    try:
                        resp = await client.get(
                            "https://ted.europa.eu/api/v3.0/notices/search",
                            params={"q": keyword, "pageSize": 10, "scope": 3},
                            headers={"Accept": "application/json"},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            for notice in data.get("notices", data.get("results", [])):
                                title = notice.get("title", str(notice.get("titleText", "")))
                                tenders.append(Tender(
                                    title=str(title)[:200],
                                    organization=str(notice.get("buyerName", "")),
                                    country="EU",
                                    source="eu_ted",
                                    source_url="https://ted.europa.eu",
                                    category="IT Services",
                                ))
                    except Exception:
                        pass

    except Exception as e:
        logger.warning("EU TED crawl failed: %s", e)

    logger.info("EU TED: found %d IT tenders", len(tenders))
    return tenders[:max_results]
