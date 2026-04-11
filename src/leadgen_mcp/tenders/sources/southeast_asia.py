"""Southeast Asia tender sources — Singapore, Philippines, Thailand."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender

logger = logging.getLogger("tenders.southeast_asia")

IT_KEYWORDS = ["software", "it ", "ict", "digital", "web", "cloud", "data", "cyber",
               "network", "system", "application", "portal", "server", "hosting",
               "technology", "computer", "database", "mobile"]


def _is_it_tender(text: str) -> bool:
    return any(kw in text.lower() for kw in IT_KEYWORDS)


async def crawl_singapore(max_results: int = 15) -> list[Tender]:
    """Singapore GeBIZ + data.gov.sg structured data."""
    tenders = []

    # data.gov.sg API (structured JSON)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://data.gov.sg/api/action/datastore_search",
                params={"resource_id": "d_acde1106003906a75c3fa052592f2fcb", "limit": 50},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("result", {}).get("records", [])
                for rec in records:
                    title = rec.get("tender_description", rec.get("title", ""))
                    if not _is_it_tender(str(title)):
                        continue

                    agency = rec.get("agency", "Singapore Government")
                    close_date = rec.get("tender_closing_date", "")
                    ref = rec.get("tender_no", "")
                    award = rec.get("awarded_amt", "")

                    tenders.append(Tender(
                        title=str(title)[:200], organization=str(agency),
                        country="Singapore", source="gebiz_sg",
                        source_url=f"https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml",
                        deadline=str(close_date)[:10] if close_date else "",
                        amount=f"SGD {award}" if award else "",
                        currency="SGD", reference_number=str(ref),
                        category="IT Services",
                    ))
                    if len(tenders) >= max_results:
                        break

    except Exception as e:
        logger.warning("Singapore data.gov.sg failed: %s", e)

    # Fallback: scrape GeBIZ
    if not tenders:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(
                    "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    for row in soup.select("table tr, .opportunity, [class*='listing']")[:max_results * 3]:
                        title_el = row.select_one("a, td, .title")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)[:200]
                        if title and _is_it_tender(title):
                            tenders.append(Tender(
                                title=title, organization="Singapore Government",
                                country="Singapore", source="gebiz_sg",
                                source_url="https://www.gebiz.gov.sg",
                                category="IT Services",
                            ))
                            if len(tenders) >= max_results:
                                break
        except Exception as e:
            logger.debug("GeBIZ scrape failed: %s", e)

    logger.info("Singapore: found %d IT tenders", len(tenders))
    return tenders[:max_results]


async def crawl_philippines(max_results: int = 10) -> list[Tender]:
    """Philippines PhilGEPS."""
    tenders = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.philgeps.gov.ph/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            for row in soup.select("table tr, .tender-row, [class*='opportunity']"):
                title_el = row.select_one("a, td, .title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)[:200]
                if not title or len(title) < 10 or not _is_it_tender(title):
                    continue

                link = ""
                if title_el.name == "a":
                    href = title_el.get("href", "")
                    link = href if href.startswith("http") else f"https://www.philgeps.gov.ph{href}"

                tenders.append(Tender(
                    title=title, organization="Philippines Government",
                    country="Philippines", source="philgeps",
                    source_url=link or "https://www.philgeps.gov.ph",
                    currency="PHP", category="IT Services",
                ))
                if len(tenders) >= max_results:
                    break

    except Exception as e:
        logger.warning("PhilGEPS crawl failed: %s", e)

    logger.info("Philippines: found %d IT tenders", len(tenders))
    return tenders


async def crawl(max_results: int = 25) -> list[Tender]:
    """Crawl all Southeast Asia sources."""
    results = []
    sg = await crawl_singapore(max_results // 2)
    ph = await crawl_philippines(max_results // 2)
    results = sg + ph
    logger.info("Southeast Asia total: %d IT tenders", len(results))
    return results[:max_results]
