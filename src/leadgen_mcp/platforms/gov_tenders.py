"""Government tender/procurement crawler.

Crawls government procurement portals for IT/software tenders:
- India: GeM (gem.gov.in), CPPP (eprocure.gov.in), state eProcurement
- US: SAM.gov Opportunities API (free, no key needed)
- UK: Contracts Finder (free API)

Signals: tender, government_contract, software_rfp, it_procurement
Verticals: chandorkar (software dev), staff_aug (team augmentation)
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client, random_ua

logger = logging.getLogger("leadgen.platforms.gov_tenders")

# Keywords to search for IT/software related tenders
IT_KEYWORDS = [
    "software development", "web application", "mobile app",
    "website design", "IT services", "cloud migration",
    "ERP implementation", "database management", "cybersecurity",
    "digital transformation", "AI solution", "machine learning",
    "blockchain", "e-governance", "portal development",
    "custom software", "application maintenance", "hosting services",
]


class GovTenderCrawler(PlatformCrawler):
    platform_name = "gov_tenders"
    rate_limit = 3.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        source = query.get("source", "sam_gov")
        keywords = query.get("keywords", ["software development", "web application", "IT services"])
        max_results = query.get("max_results", 30)
        days_back = query.get("days_back", 14)

        if source == "sam_gov":
            return await self._crawl_sam_gov(keywords, max_results, days_back)
        elif source == "gem_india":
            return await self._crawl_gem_india(keywords, max_results)
        elif source == "cppp_india":
            return await self._crawl_cppp_india(keywords, max_results)
        elif source == "uk_contracts":
            return await self._crawl_uk_contracts(keywords, max_results, days_back)
        elif source == "all":
            leads = []
            for src in ["sam_gov", "gem_india", "cppp_india", "uk_contracts"]:
                try:
                    batch = await self.crawl({**query, "source": src, "max_results": max_results // 4})
                    leads.extend(batch)
                except Exception as e:
                    logger.warning("Tender source %s failed: %s", src, e)
            return leads[:max_results]
        else:
            return await self._crawl_sam_gov(keywords, max_results, days_back)

    async def _crawl_sam_gov(self, keywords: list[str], max_results: int, days_back: int) -> list[PlatformLead]:
        """Search SAM.gov Opportunities API (free, no auth)."""
        leads = []
        posted_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%m/%d/%Y")

        for keyword in keywords[:3]:
            url = "https://api.sam.gov/opportunities/v2/search"
            params = {
                "api_key": "DEMO_KEY",  # SAM.gov provides a demo key
                "postedFrom": posted_from,
                "keyword": keyword,
                "ptype": "o",  # opportunities
                "limit": min(max_results, 25),
                "offset": 0,
            }

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429:
                        logger.warning("SAM.gov rate limited")
                        break
                    if resp.status_code != 200:
                        logger.debug("SAM.gov returned %d for '%s'", resp.status_code, keyword)
                        continue

                    data = resp.json()
                    opportunities = data.get("opportunitiesData", [])

                    for opp in opportunities:
                        title = opp.get("title", "")
                        dept = opp.get("fullParentPathName", opp.get("department", ""))
                        sol_number = opp.get("solicitationNumber", "")
                        posted_date = opp.get("postedDate", "")
                        response_deadline = opp.get("responseDeadLine", "")
                        url_link = opp.get("uiLink", f"https://sam.gov/opp/{opp.get('noticeId', '')}/view")
                        naics = opp.get("naicsCode", "")
                        set_aside = opp.get("typeOfSetAside", "")

                        description = f"US Federal: {title}"
                        if dept:
                            description += f"\nAgency: {dept}"
                        if response_deadline:
                            description += f"\nDeadline: {response_deadline}"
                        if naics:
                            description += f"\nNAICS: {naics}"

                        signals = ["tender", "government_contract", "us_federal"]
                        if any(kw in title.lower() for kw in ["software", "web", "app", "it ", "cloud", "cyber"]):
                            signals.append("software_rfp")

                        leads.append(PlatformLead(
                            source="gov_tenders",
                            company_name=title[:80],
                            description=description,
                            signals=signals,
                            raw_url=url_link,
                            location="US",
                            industry="government",
                        ))

            except Exception as e:
                logger.warning("SAM.gov search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_gem_india(self, keywords: list[str], max_results: int) -> list[PlatformLead]:
        """Search GeM (Government e-Marketplace) India for IT bids."""
        leads = []

        for keyword in keywords[:3]:
            # GeM doesn't have a public API, scrape search results
            url = f"https://mkp.gem.gov.in/search?q={quote(keyword)}&page=1"

            try:
                await self._bucket.acquire()
                html = await self._throttled_fetch(url)

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")

                # Parse bid cards
                for card in soup.select(".bid-card, .product-card, [class*='tender'], [class*='bid']")[:max_results]:
                    title_el = card.select_one("h3, h4, .title, [class*='title']")
                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)[:80]
                    link = ""
                    link_el = card.select_one("a[href]")
                    if link_el:
                        href = link_el.get("href", "")
                        if href.startswith("/"):
                            link = f"https://gem.gov.in{href}"
                        elif href.startswith("http"):
                            link = href

                    dept = ""
                    dept_el = card.select_one(".department, .org, [class*='department']")
                    if dept_el:
                        dept = dept_el.get_text(strip=True)

                    leads.append(PlatformLead(
                        source="gov_tenders",
                        company_name=title,
                        description=f"GeM India: {title}" + (f"\nDepartment: {dept}" if dept else ""),
                        signals=["tender", "government_contract", "india_gem", "it_procurement"],
                        raw_url=link or f"https://gem.gov.in/search?q={quote(keyword)}",
                        location="India",
                        industry="government",
                    ))

            except Exception as e:
                logger.debug("GeM search failed for '%s': %s", keyword, e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_cppp_india(self, keywords: list[str], max_results: int) -> list[PlatformLead]:
        """Search Central Public Procurement Portal (eprocure.gov.in)."""
        leads = []

        for keyword in keywords[:3]:
            url = f"https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page"

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, headers={"User-Agent": random_ua()})
                    if resp.status_code != 200:
                        continue

                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "lxml")

                    for row in soup.select("table tr")[1:max_results + 1]:
                        cells = row.select("td")
                        if len(cells) < 4:
                            continue

                        title = cells[1].get_text(strip=True)[:80] if len(cells) > 1 else ""
                        org = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                        deadline = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                        # Filter by keyword
                        combined = f"{title} {org}".lower()
                        if not any(kw.lower() in combined for kw in keywords):
                            continue

                        link_el = cells[1].select_one("a[href]") if len(cells) > 1 else None
                        link = ""
                        if link_el:
                            href = link_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://eprocure.gov.in{href}"

                        leads.append(PlatformLead(
                            source="gov_tenders",
                            company_name=title,
                            description=f"CPPP India: {title}\nOrg: {org}\nDeadline: {deadline}",
                            signals=["tender", "government_contract", "india_cppp"],
                            raw_url=link or "https://eprocure.gov.in/eprocure/app",
                            location="India",
                            industry="government",
                        ))

            except Exception as e:
                logger.debug("CPPP search failed: %s", e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]

    async def _crawl_uk_contracts(self, keywords: list[str], max_results: int, days_back: int) -> list[PlatformLead]:
        """Search UK Contracts Finder API (free, no auth)."""
        leads = []
        published_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

        for keyword in keywords[:3]:
            url = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
            params = {
                "keyword": keyword,
                "publishedFrom": published_from,
                "size": min(max_results, 20),
                "publishedTo": "",
            }

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    releases = data.get("releases", [])

                    for release in releases:
                        tender = release.get("tender", {})
                        title = tender.get("title", "")[:80]
                        description_text = tender.get("description", "")[:200]
                        value = tender.get("value", {})
                        amount = value.get("amount")
                        buyer = release.get("buyer", {}).get("name", "")

                        desc = f"UK Contract: {title}"
                        if buyer:
                            desc += f"\nBuyer: {buyer}"
                        if amount:
                            desc += f"\nValue: GBP {amount:,.0f}"

                        leads.append(PlatformLead(
                            source="gov_tenders",
                            company_name=title,
                            description=desc,
                            budget_estimate=int(amount) if amount else None,
                            signals=["tender", "government_contract", "uk_contract"],
                            raw_url=f"https://www.contractsfinder.service.gov.uk/Notice/{release.get('id', '')}",
                            location="UK",
                            industry="government",
                        ))

            except Exception as e:
                logger.debug("UK Contracts Finder failed: %s", e)

            if len(leads) >= max_results:
                break

        return leads[:max_results]
