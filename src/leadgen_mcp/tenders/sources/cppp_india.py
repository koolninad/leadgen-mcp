"""CPPP (Central Public Procurement Portal) — India. Web scraping."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender

logger = logging.getLogger("tenders.cppp_india")

CPPP_URL = "https://eprocure.gov.in/eprocure/app"
GEM_SEARCH = "https://mkp.gem.gov.in/search"
IT_KEYWORDS = [
    "software", "web portal", "IT services", "cloud", "ERP",
    "mobile app", "digital", "cybersecurity", "hosting", "database",
    "e-governance", "network", "data center", "AI", "machine learning",
]


async def crawl_cppp(max_results: int = 20) -> list[Tender]:
    """Crawl CPPP active tenders."""
    tenders = []

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                f"{CPPP_URL}?page=FrontEndLatestActiveTenders&service=page",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code != 200:
                logger.warning("CPPP returned %d", resp.status_code)
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            for row in soup.select("table tr")[1:]:
                cells = row.select("td")
                if len(cells) < 5:
                    continue

                title = cells[1].get_text(strip=True)[:200] if len(cells) > 1 else ""
                org = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                deadline = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                ref = cells[0].get_text(strip=True) if cells else ""

                # Filter for IT-related tenders
                combined = f"{title} {org}".lower()
                if not any(kw in combined for kw in IT_KEYWORDS):
                    continue

                link = ""
                link_el = cells[1].select_one("a[href]") if len(cells) > 1 else None
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        link = f"https://eprocure.gov.in{href}"
                    elif href.startswith("http"):
                        link = href

                # Try to extract amount from title/description
                amount = ""
                amt_match = re.search(r'(?:Rs\.?|INR|₹)\s*([\d,.]+)\s*(?:Cr|Lakh|crore|lakh)?', title, re.I)
                if amt_match:
                    amount = f"INR {amt_match.group(0)}"

                tenders.append(Tender(
                    title=title,
                    organization=org,
                    country="India",
                    source="cppp_india",
                    source_url=link or CPPP_URL,
                    description=f"CPPP Tender: {title}",
                    amount=amount,
                    currency="INR",
                    deadline=deadline,
                    reference_number=ref,
                    category="IT Services",
                ))

                if len(tenders) >= max_results:
                    break

    except Exception as e:
        logger.warning("CPPP crawl failed: %s", e)

    logger.info("CPPP India: found %d IT tenders", len(tenders))
    return tenders


async def crawl_gem(max_results: int = 20) -> list[Tender]:
    """Crawl GeM (Government e-Marketplace) India."""
    tenders = []

    for keyword in IT_KEYWORDS[:3]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    GEM_SEARCH, params={"q": keyword, "page": 1},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                for card in soup.select(".bid-card, .product-card, [class*='tender'], [class*='bid']")[:max_results]:
                    title_el = card.select_one("h3, h4, .title, [class*='title']")
                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)[:200]
                    dept_el = card.select_one(".department, .org, [class*='department']")
                    dept = dept_el.get_text(strip=True) if dept_el else ""

                    link = ""
                    link_el = card.select_one("a[href]")
                    if link_el:
                        href = link_el.get("href", "")
                        link = f"https://gem.gov.in{href}" if href.startswith("/") else href

                    tenders.append(Tender(
                        title=title,
                        organization=dept,
                        country="India",
                        source="gem_india",
                        source_url=link or "https://gem.gov.in",
                        description=f"GeM: {title}",
                        currency="INR",
                        category="IT Services",
                    ))

        except Exception as e:
            logger.debug("GeM search failed: %s", e)

        if len(tenders) >= max_results:
            break

    logger.info("GeM India: found %d tenders", len(tenders))
    return tenders[:max_results]


async def crawl_state_portals(max_results: int = 15) -> list[Tender]:
    """Crawl Indian state eProcurement portals (NIC-based)."""
    tenders = []

    # NIC-based state portals share the same structure
    state_portals = [
        ("Tamil Nadu", "https://tntenders.gov.in/nicgep/app"),
        ("Maharashtra", "https://mahatenders.gov.in/nicgep/app"),
        ("Andhra Pradesh", "https://tender.apeprocurement.gov.in/"),
        ("Telangana", "https://tender.telangana.gov.in/"),
        ("Uttar Pradesh", "https://etender.up.nic.in/nicgep/app"),
    ]

    for state_name, portal_url in state_portals:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(
                    portal_url,
                    params={"page": "FrontEndLatestActiveTenders", "service": "page"} if "nicgep" in portal_url else {},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                for row in soup.select("table tr")[1:]:
                    cells = row.select("td")
                    if len(cells) < 3:
                        continue

                    title = cells[1].get_text(strip=True)[:200] if len(cells) > 1 else ""
                    org = cells[2].get_text(strip=True) if len(cells) > 2 else state_name
                    deadline = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                    combined = f"{title} {org}".lower()
                    if not any(kw in combined for kw in IT_KEYWORDS):
                        continue

                    tenders.append(Tender(
                        title=title, organization=org,
                        country="India", source=f"india_{state_name.lower().replace(' ', '_')}",
                        source_url=portal_url, deadline=deadline,
                        currency="INR", category="IT Services",
                    ))

                    if len(tenders) >= max_results:
                        break

        except Exception as e:
            logger.debug("State portal %s failed: %s", state_name, e)

        if len(tenders) >= max_results:
            break

    logger.info("India state portals: found %d IT tenders", len(tenders))
    return tenders[:max_results]


async def crawl(max_results: int = 40) -> list[Tender]:
    """Crawl all Indian tender sources."""
    cppp = await crawl_cppp(max_results // 3)
    gem = await crawl_gem(max_results // 3)
    states = await crawl_state_portals(max_results // 3)
    return (cppp + gem + states)[:max_results]
