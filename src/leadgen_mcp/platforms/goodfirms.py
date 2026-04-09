"""GoodFirms review scraping for companies with tech pain points."""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead


class GoodFirmsCrawler(PlatformCrawler):
    platform_name = "goodfirms"
    rate_limit = 3.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl GoodFirms for companies and reviews indicating tech needs."""
        category = query.get("category", "software-development")
        location = query.get("location", "")
        max_results = query.get("max_results", 20)

        url = f"https://www.goodfirms.co/directory/category/{category}"
        if location:
            url += f"/country/{quote_plus(location.lower())}"

        html = await self._crawl4ai_fetch(url)
        soup = BeautifulSoup(html, "lxml")

        leads = []

        for card in soup.select(".firm-card, .directory-list-item, .profile-card"):
            name_el = card.select_one("h3 a, .firm-name a, .company-name a")
            if not name_el:
                continue

            company_name = name_el.get_text(strip=True)
            profile_url = name_el.get("href", "")
            if profile_url and not profile_url.startswith("http"):
                profile_url = f"https://www.goodfirms.co{profile_url}"

            rating_el = card.select_one(".rating-number, .avg-rating")
            rating = rating_el.get_text(strip=True) if rating_el else ""

            desc_el = card.select_one(".firm-description, .tagline, .firm-tagline")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            loc_el = card.select_one(".location, .firm-location")
            loc = loc_el.get_text(strip=True) if loc_el else ""

            # Extract domain
            website_el = card.select_one("a.website-link, a[data-event='visit_website']")
            website = website_el.get("href") if website_el else None
            domain = None
            if website:
                from urllib.parse import urlparse
                parsed = urlparse(website)
                domain = parsed.netloc.replace("www.", "")

            signals = ["goodfirms_listed"]
            if rating:
                try:
                    if float(rating) < 4.0:
                        signals.append("low_rated_competitor")
                except ValueError:
                    pass

            leads.append(PlatformLead(
                source="goodfirms",
                company_name=company_name,
                domain=domain,
                description=desc,
                raw_url=profile_url,
                location=loc or None,
                industry=category,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads
