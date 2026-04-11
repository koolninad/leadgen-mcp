"""Multilateral tender sources — World Bank, UNGM, ADB, AfDB."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import Tender

logger = logging.getLogger("tenders.multilateral")


async def crawl_world_bank(max_results: int = 15) -> list[Tender]:
    """World Bank Procurement — high-value IT projects."""
    tenders = []
    url = "https://projects.worldbank.org/en/projects-operations/procurement"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # WB API for procurement notices
            api_url = "https://search.worldbank.org/api/v2/procnotices"
            resp = await client.get(api_url, params={
                "format": "json",
                "qterm": "information technology software",
                "rows": max_results,
                "os": 0,
            })

            if resp.status_code == 200:
                data = resp.json()
                raw_notices = data.get("procnotices", {})

                # Handle both dict and list formats
                if isinstance(raw_notices, list):
                    notices = {str(i): n for i, n in enumerate(raw_notices) if isinstance(n, dict)}
                elif isinstance(raw_notices, dict):
                    notices = raw_notices
                else:
                    notices = {}

                for key, notice in notices.items():
                    if not isinstance(notice, dict):
                        continue

                    title = notice.get("notice_text", notice.get("project_name", ""))[:200]
                    country = notice.get("countryshortname", "")
                    deadline = notice.get("deadline_date", "")
                    pub_date = notice.get("notice_posting_date", "")
                    notice_url = notice.get("url", "")
                    borrower = notice.get("borrower", "")

                    tenders.append(Tender(
                        title=title,
                        organization=borrower or "World Bank",
                        country=country or "Global",
                        source="world_bank",
                        source_url=notice_url or url,
                        deadline=deadline,
                        published_date=pub_date,
                        category="IT Services",
                        raw_data=notice if isinstance(notice, dict) else {},
                    ))

    except Exception as e:
        logger.warning("World Bank crawl failed: %s", e)

    logger.info("World Bank: found %d tenders", len(tenders))
    return tenders[:max_results]


async def crawl_ungm(max_results: int = 10) -> list[Tender]:
    """UNGM (United Nations Global Marketplace)."""
    tenders = []

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.ungm.org/Public/Notice",
                params={"PageIndex": 0, "PageSize": 20},
                headers={"User-Agent": "Mozilla/5.0"},
            )

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")

                for row in soup.select("table tr, .notice-item, [class*='notice']")[:max_results]:
                    title_el = row.select_one("a, h3, .title")
                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)[:200]
                    # Filter for IT
                    if not any(kw in title.lower() for kw in ["software", "it ", "ict", "digital", "web", "cloud", "data"]):
                        continue

                    link = ""
                    if title_el.name == "a":
                        href = title_el.get("href", "")
                        link = f"https://www.ungm.org{href}" if href.startswith("/") else href

                    org_el = row.select_one(".organization, td:nth-child(2)")
                    org = org_el.get_text(strip=True) if org_el else "UN Agency"

                    deadline_el = row.select_one(".deadline, td:nth-child(3)")
                    deadline = deadline_el.get_text(strip=True) if deadline_el else ""

                    tenders.append(Tender(
                        title=title,
                        organization=org,
                        country="Global",
                        source="ungm",
                        source_url=link or "https://www.ungm.org/Public/Notice",
                        deadline=deadline,
                        category="IT Services",
                    ))

    except Exception as e:
        logger.warning("UNGM crawl failed: %s", e)

    logger.info("UNGM: found %d tenders", len(tenders))
    return tenders[:max_results]


async def crawl(max_results: int = 25) -> list[Tender]:
    """Crawl all multilateral sources."""
    wb = await crawl_world_bank(max_results // 2)
    ungm = await crawl_ungm(max_results // 2)
    return (wb + ungm)[:max_results]
