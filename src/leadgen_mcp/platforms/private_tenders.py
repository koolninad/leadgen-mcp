"""Private tender / RFP aggregator crawler.

Crawls private sector tender portals and RFP aggregators:
- TenderTiger (India) — tendertiger.com
- Tender247 (India/Global) — tender247.com
- TendersInfo (India/Global) — tendersinfo.com
- BidAssist (India) — bidassist.com
- Global Tenders — globaltenders.com

Signals: private_tender, rfp, software_rfp, it_services
Verticals: chandorkar (software dev), hostingduty (hosting), staff_aug
"""

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client, random_ua

logger = logging.getLogger("leadgen.platforms.private_tenders")


class PrivateTenderCrawler(PlatformCrawler):
    platform_name = "private_tenders"
    rate_limit = 3.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        source = query.get("source", "tendertiger")
        keywords = query.get("keywords", ["software development", "web application", "IT services"])
        max_results = query.get("max_results", 30)

        if source == "tendertiger":
            return await self._crawl_tendertiger(keywords, max_results)
        elif source == "tender247":
            return await self._crawl_tender247(keywords, max_results)
        elif source == "tendersinfo":
            return await self._crawl_tendersinfo(keywords, max_results)
        elif source == "all":
            leads = []
            for src in ["tendertiger", "tender247", "tendersinfo"]:
                try:
                    batch = await self.crawl({**query, "source": src, "max_results": max_results // 3})
                    leads.extend(batch)
                except Exception as e:
                    logger.warning("Tender source %s failed: %s", src, e)
            return leads[:max_results]
        else:
            return await self._crawl_tendertiger(keywords, max_results)

    async def _crawl_tendertiger(self, keywords: list[str], max_results: int) -> list[PlatformLead]:
        """Search TenderTiger.com for IT/software tenders."""
        leads = []

        for keyword in keywords[:3]:
            url = f"https://www.tendertiger.com/TenderAI/TenderAIList"
            params = {"searchtext": f"{keyword}-tenders"}

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params, headers={"User-Agent": random_ua()})
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    cards = soup.select(".tender-card, .card, [class*='tender-item'], tr[class*='tender']")

                    if not cards:
                        # Try alternative selectors
                        cards = soup.select("table tbody tr, .list-group-item, article")

                    for card in cards[:max_results]:
                        title_el = card.select_one("a, h3, h4, .title, td:first-child")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)[:80]
                        if not title or len(title) < 10:
                            continue

                        link = ""
                        if title_el.name == "a":
                            href = title_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://www.tendertiger.com{href}"
                            elif href.startswith("http"):
                                link = href

                        # Extract org/location if available
                        org = ""
                        org_el = card.select_one(".org, .department, td:nth-child(2)")
                        if org_el:
                            org = org_el.get_text(strip=True)[:60]

                        deadline = ""
                        date_el = card.select_one(".date, .deadline, td:nth-child(3)")
                        if date_el:
                            deadline = date_el.get_text(strip=True)

                        desc = f"TenderTiger: {title}"
                        if org:
                            desc += f"\nOrg: {org}"
                        if deadline:
                            desc += f"\nDeadline: {deadline}"

                        signals = ["private_tender", "rfp"]
                        title_lower = title.lower()
                        if any(kw in title_lower for kw in ["software", "web", "app", "it ", "cloud", "digital", "hosting"]):
                            signals.append("software_rfp")

                        leads.append(PlatformLead(
                            source="private_tenders",
                            company_name=title,
                            description=desc,
                            signals=signals,
                            raw_url=link or f"https://www.tendertiger.com/TenderAI/TenderAIList?searchtext={quote(keyword)}-tenders",
                            industry="tender",
                        ))

            except Exception as e:
                logger.debug("TenderTiger search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_tender247(self, keywords: list[str], max_results: int) -> list[PlatformLead]:
        """Search Tender247.com for IT tenders."""
        leads = []

        for keyword in keywords[:3]:
            url = f"https://www.tender247.com/keyword/{quote(keyword.replace(' ', '-'))}-tenders"

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, headers={"User-Agent": random_ua()})
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")

                    for card in soup.select(".tender-list-item, .card, tr, article, .list-item")[:max_results]:
                        title_el = card.select_one("a, h3, h4, .title")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)[:80]
                        if not title or len(title) < 10:
                            continue

                        link = ""
                        if title_el.name == "a":
                            href = title_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://www.tender247.com{href}"
                            elif href.startswith("http"):
                                link = href

                        leads.append(PlatformLead(
                            source="private_tenders",
                            company_name=title,
                            description=f"Tender247: {title}",
                            signals=["private_tender", "rfp"],
                            raw_url=link or url,
                            industry="tender",
                        ))

            except Exception as e:
                logger.debug("Tender247 search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_tendersinfo(self, keywords: list[str], max_results: int) -> list[PlatformLead]:
        """Search TendersInfo.com for global IT tenders."""
        leads = []

        for keyword in keywords[:3]:
            url = f"https://www.tendersinfo.com/searchresult.php"
            params = {"search": keyword}

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params, headers={"User-Agent": random_ua()})
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")

                    for card in soup.select(".tender-row, .search-result, tr, .list-group-item")[:max_results]:
                        title_el = card.select_one("a, h3, .title")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)[:80]
                        if not title or len(title) < 10:
                            continue

                        link = ""
                        if title_el.name == "a":
                            href = title_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://www.tendersinfo.com{href}"
                            elif href.startswith("http"):
                                link = href

                        # Try to find location
                        location = ""
                        loc_el = card.select_one(".location, .country")
                        if loc_el:
                            location = loc_el.get_text(strip=True)

                        leads.append(PlatformLead(
                            source="private_tenders",
                            company_name=title,
                            description=f"TendersInfo: {title}",
                            signals=["private_tender", "rfp", "global_tender"],
                            raw_url=link or url,
                            location=location,
                            industry="tender",
                        ))

            except Exception as e:
                logger.debug("TendersInfo search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]
