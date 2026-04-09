"""Clutch.co directory scraping for companies seeking dev partners."""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead


class ClutchCrawler(PlatformCrawler):
    platform_name = "clutch"
    rate_limit = 3.0
    max_concurrency = 3

    CATEGORY_URLS = {
        "web_development": "web-developers",
        "mobile_development": "app-developers",
        "custom_software": "custom-software-development",
        "ecommerce": "ecommerce-developers",
        "ui_ux": "ui-ux-designers",
        "it_services": "it-services",
        "cloud": "cloud-consulting",
        "ai_ml": "artificial-intelligence",
    }

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl Clutch.co for companies in specific categories."""
        category = query.get("category", "web_development")
        location = query.get("location", "")
        min_budget = query.get("min_budget", 0)
        max_results = query.get("max_results", 30)

        cat_slug = self.CATEGORY_URLS.get(category, category)
        url = f"https://clutch.co/developers/{cat_slug}"
        if location:
            url += f"?location={quote_plus(location)}"

        html = await self._crawl4ai_fetch(url)
        soup = BeautifulSoup(html, "lxml")

        leads = []

        # Parse Clutch company listing cards
        for card in soup.select(".provider-row, .provider__info, [data-provider-id]"):
            name_el = card.select_one(".company_info a, .provider__title a, h3 a")
            if not name_el:
                continue

            company_name = name_el.get_text(strip=True)
            profile_url = name_el.get("href", "")
            if profile_url and not profile_url.startswith("http"):
                profile_url = f"https://clutch.co{profile_url}"

            # Extract details
            rating_el = card.select_one(".rating, .sg-rating__number")
            rating = rating_el.get_text(strip=True) if rating_el else ""

            location_el = card.select_one(".locality, .provider__locality")
            loc = location_el.get_text(strip=True) if location_el else ""

            budget_el = card.select_one(".field--min-project-size .field-item, .provider__budget")
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget = self._parse_budget(budget_text)

            desc_el = card.select_one(".provider__tagline, .tagline")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            # Filter by minimum budget
            if min_budget and budget and budget < min_budget:
                continue

            website_el = card.select_one("a[data-link_type='website'], .website-link")
            website = website_el.get("href") if website_el else None
            domain = self._extract_domain(website) if website else None

            signals = ["clutch_listed"]
            if rating:
                try:
                    if float(rating) >= 4.5:
                        signals.append("high_rated_on_clutch")
                except ValueError:
                    pass

            leads.append(PlatformLead(
                source="clutch",
                company_name=company_name,
                domain=domain,
                description=desc,
                budget_estimate=budget,
                raw_url=profile_url,
                location=loc or None,
                industry=category,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads

    def _parse_budget(self, text: str) -> int | None:
        """Parse budget string like '$25,000+' or '$10,000 - $25,000'."""
        match = re.search(r"\$?([\d,]+)", text.replace(" ", ""))
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _extract_domain(self, url: str | None) -> str | None:
        if not url:
            return None
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None
