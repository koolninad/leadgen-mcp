"""Middle East tender sources — UAE, Saudi Arabia, Oman, Bahrain."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender

logger = logging.getLogger("tenders.middle_east")

IT_KEYWORDS = ["software", "it ", "ict", "digital", "web", "cloud", "data", "cyber",
               "network", "system", "application", "portal", "server", "hosting",
               "erp", "database", "mobile", "app", "technology", "computer"]


def _is_it_tender(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in IT_KEYWORDS)


async def crawl_uae(max_results: int = 15) -> list[Tender]:
    """UAE Ministry of Finance tenders."""
    tenders = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                "https://mof.gov.ae/en/public-finance/government-procurement/tenders-and-auctions/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select("table tr, .tender-item, article, .card, [class*='tender']"):
                title_el = card.select_one("a, h3, h4, td:first-child, .title")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)[:200]
                if not title or len(title) < 10:
                    continue
                if not _is_it_tender(title):
                    continue

                link = ""
                if title_el.name == "a":
                    href = title_el.get("href", "")
                    link = href if href.startswith("http") else f"https://mof.gov.ae{href}"

                deadline_el = card.select_one("td:nth-child(3), .date, .deadline")
                deadline = deadline_el.get_text(strip=True) if deadline_el else ""

                tenders.append(Tender(
                    title=title, organization="UAE Ministry of Finance",
                    country="UAE", source="uae_mof",
                    source_url=link or "https://mof.gov.ae/en/public-finance/government-procurement/tenders-and-auctions/",
                    deadline=deadline, category="IT Services",
                ))
                if len(tenders) >= max_results:
                    break

    except Exception as e:
        logger.warning("UAE MOF crawl failed: %s", e)

    logger.info("UAE MOF: found %d IT tenders", len(tenders))
    return tenders


async def crawl_saudi(max_results: int = 15) -> list[Tender]:
    """Saudi Arabia ETIMAD platform."""
    tenders = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # ETIMAD redirects to a SPA — try their API
            for keyword in ["software", "IT services", "technology"]:
                try:
                    resp = await client.get(
                        "https://tenders.etimad.sa/Tender/AllTendersForVisitor",
                        params={"PageNumber": 1, "PageSize": 10, "SearchText": keyword},
                        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                    )
                    if resp.status_code == 200 and resp.text.strip().startswith(("{", "[")):
                        data = resp.json()
                        items = data if isinstance(data, list) else data.get("data", data.get("items", data.get("result", [])))
                        if isinstance(items, list):
                            for item in items[:max_results]:
                                title = item.get("tenderName", item.get("name", item.get("title", "")))
                                org = item.get("agencyName", item.get("organization", "Saudi Government"))
                                deadline = item.get("lastOfferPresentationDate", item.get("deadline", ""))
                                ref = item.get("referenceNumber", item.get("tenderNumber", ""))
                                amount = item.get("estimatedValue", "")

                                tenders.append(Tender(
                                    title=str(title)[:200], organization=str(org),
                                    country="Saudi Arabia", source="saudi_etimad",
                                    source_url=f"https://tenders.etimad.sa/Tender/DetailsForVisitor?STenderId={ref}" if ref else "https://etimad.sa",
                                    deadline=str(deadline)[:20], amount=f"SAR {amount}" if amount else "",
                                    currency="SAR", reference_number=str(ref), category="IT Services",
                                ))
                except Exception:
                    pass

            # Fallback: scrape main page
            if not tenders:
                resp = await client.get("https://etimad.sa/", headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    for el in soup.select("a[href*='tender'], [class*='tender']")[:max_results]:
                        title = el.get_text(strip=True)[:200]
                        if title and _is_it_tender(title):
                            tenders.append(Tender(
                                title=title, organization="Saudi Government",
                                country="Saudi Arabia", source="saudi_etimad",
                                source_url="https://etimad.sa", category="IT Services",
                            ))

    except Exception as e:
        logger.warning("Saudi ETIMAD crawl failed: %s", e)

    logger.info("Saudi ETIMAD: found %d tenders", len(tenders))
    return tenders[:max_results]


async def crawl_oman(max_results: int = 10) -> list[Tender]:
    """Oman Tender Board."""
    tenders = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                "https://etendering.tenderboard.gov.om/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            for row in soup.select("table tr, .tender-row, [class*='tender']"):
                title_el = row.select_one("a, td:first-child, .title")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)[:200]
                if not title or len(title) < 10:
                    continue
                if not _is_it_tender(title):
                    continue

                link = ""
                if title_el.name == "a":
                    href = title_el.get("href", "")
                    link = href if href.startswith("http") else f"https://etendering.tenderboard.gov.om{href}"

                tenders.append(Tender(
                    title=title, organization="Oman Tender Board",
                    country="Oman", source="oman_tender",
                    source_url=link or "https://etendering.tenderboard.gov.om",
                    category="IT Services",
                ))
                if len(tenders) >= max_results:
                    break

    except Exception as e:
        logger.warning("Oman tender crawl failed: %s", e)

    logger.info("Oman: found %d IT tenders", len(tenders))
    return tenders


async def crawl_bahrain(max_results: int = 10) -> list[Tender]:
    """Bahrain Tender Board."""
    tenders = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.tenderboard.gov.bh/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            for row in soup.select("table tr, .tender-item, [class*='tender'], article"):
                title_el = row.select_one("a, h3, td, .title")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)[:200]
                if not title or len(title) < 10:
                    continue
                if not _is_it_tender(title):
                    continue

                link = ""
                if title_el.name == "a":
                    href = title_el.get("href", "")
                    link = href if href.startswith("http") else f"https://www.tenderboard.gov.bh{href}"

                tenders.append(Tender(
                    title=title, organization="Bahrain Tender Board",
                    country="Bahrain", source="bahrain_tender",
                    source_url=link or "https://www.tenderboard.gov.bh",
                    category="IT Services",
                ))
                if len(tenders) >= max_results:
                    break

    except Exception as e:
        logger.warning("Bahrain tender crawl failed: %s", e)

    logger.info("Bahrain: found %d IT tenders", len(tenders))
    return tenders


async def crawl(max_results: int = 40) -> list[Tender]:
    """Crawl all Middle East sources."""
    results = []
    per_source = max_results // 4

    for name, fn in [("UAE", crawl_uae), ("Saudi", crawl_saudi), ("Oman", crawl_oman), ("Bahrain", crawl_bahrain)]:
        try:
            batch = await fn(per_source)
            results.extend(batch)
        except Exception as e:
            logger.warning("%s failed: %s", name, e)

    logger.info("Middle East total: %d IT tenders", len(results))
    return results[:max_results]
