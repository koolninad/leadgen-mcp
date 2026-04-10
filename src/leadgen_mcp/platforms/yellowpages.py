"""Yellow Pages scraper.

Scrapes yellowpages.com for businesses by category and location.
Businesses without websites = leads for HostingDuty/Chandorkar.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client, random_ua

logger = logging.getLogger("leadgen.platforms.yellowpages")


class YellowPagesCrawler(PlatformCrawler):
    platform_name = "yellowpages"
    rate_limit = 3.0
    max_concurrency = 2

    async def crawl(self, query: dict) -> list[PlatformLead]:
        category = query.get("category", query.get("keywords", ["restaurants"])[0])
        location = query.get("location", "New York, NY")
        max_results = query.get("max_results", 30)

        leads = []
        page = 1

        while len(leads) < max_results and page <= 3:
            url = f"https://www.yellowpages.com/search"
            params = {
                "search_terms": category,
                "geo_location_terms": location,
                "page": page,
            }

            try:
                await self._bucket.acquire()
                async with create_client(timeout=30.0) as client:
                    resp = await client.get(url, params=params, headers={"User-Agent": random_ua()})
                    if resp.status_code != 200:
                        logger.warning("YellowPages returned %d", resp.status_code)
                        break

                    html = resp.text

                soup = BeautifulSoup(html, "lxml")
                results = soup.select(".result, .search-results .listing, .organic .srp-listing")

                if not results:
                    # Try alternative selectors
                    results = soup.select("[class*='result'], [class*='listing']")

                for item in results:
                    name_el = item.select_one(".business-name, h2 a, .n a, [class*='name']")
                    if not name_el:
                        continue

                    name = name_el.get_text(strip=True)[:80]
                    phone = ""
                    website = ""
                    address = ""

                    phone_el = item.select_one(".phones, .phone, [class*='phone']")
                    if phone_el:
                        phone = phone_el.get_text(strip=True)

                    addr_el = item.select_one(".adr, .address, [class*='address'], .street-address")
                    if addr_el:
                        address = addr_el.get_text(strip=True)

                    link_el = item.select_one("a.track-visit-website, a[href*='website'], .links a")
                    if link_el:
                        website = link_el.get("href", "")

                    # Extract domain from website URL
                    domain = None
                    if website:
                        match = re.search(r"https?://(?:www\.)?([^/]+)", website)
                        if match:
                            domain = match.group(1)

                    signals = ["local_business"]
                    if not website:
                        signals.append("no_website")

                    detail_url = ""
                    detail_link = name_el.get("href", "") if name_el.name == "a" else ""
                    if detail_link and detail_link.startswith("/"):
                        detail_url = f"https://www.yellowpages.com{detail_link}"

                    leads.append(PlatformLead(
                        source="yellowpages",
                        company_name=name,
                        domain=domain,
                        description=f"{category} in {location}. {address}",
                        signals=signals,
                        raw_url=detail_url or website,
                        location=location,
                        industry=category,
                    ))

                    if phone:
                        leads[-1].contact_email = None  # Phone stored in raw data

                    if len(leads) >= max_results:
                        break

            except Exception as e:
                logger.warning("YellowPages scrape failed: %s", e)
                break

            page += 1

        logger.info("YellowPages: found %d businesses for '%s' in '%s'",
                     len(leads), category, location)
        return leads[:max_results]
