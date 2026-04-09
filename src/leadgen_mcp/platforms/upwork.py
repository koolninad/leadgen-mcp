"""Upwork project scraping for large software development projects."""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead


class UpworkCrawler(PlatformCrawler):
    platform_name = "upwork"
    rate_limit = 2.0
    max_concurrency = 3

    SKILL_CATEGORIES = {
        "web_development": "web-development",
        "mobile_development": "mobile-development",
        "software_development": "software-development",
        "ecommerce": "ecommerce-development",
        "ai_ml": "ai-services",
        "blockchain": "blockchain",
        "devops": "devops-engineering",
        "data_science": "data-science",
    }

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl Upwork for large software development projects."""
        category = query.get("category", "software_development")
        skills = query.get("skills", [])
        min_budget = query.get("min_budget", 5000)
        max_results = query.get("max_results", 30)

        # Build search URL
        search_terms = " ".join(skills) if skills else category.replace("_", " ")
        url = f"https://www.upwork.com/nx/search/jobs/?q={quote_plus(search_terms)}&sort=recency"

        # Add budget filter for larger projects
        if min_budget >= 5000:
            url += "&budget=5000-"
        elif min_budget >= 1000:
            url += "&budget=1000-4999"

        html = await self._crawl4ai_fetch(url)
        soup = BeautifulSoup(html, "lxml")

        leads = []

        # Parse Upwork job listings
        for listing in soup.select("[data-test='job-tile-list'] section, .job-tile, .up-card-section"):
            title_el = listing.select_one("h2 a, .job-title a, [data-test='job-title-link']")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            job_url = title_el.get("href", "")
            if job_url and not job_url.startswith("http"):
                job_url = f"https://www.upwork.com{job_url}"

            # Description
            desc_el = listing.select_one("[data-test='job-description-text'], .job-description, .up-line-clamp-v2")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Budget
            budget_el = listing.select_one("[data-test='budget'], .js-budget, .job-type")
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget = self._parse_budget(budget_text)

            if min_budget and budget and budget < min_budget:
                continue

            # Skills
            skill_tags = listing.select("[data-test='attr-item'] span, .up-skill-badge, .skill-badge")
            found_skills = [s.get_text(strip=True) for s in skill_tags]

            # Client info
            client_el = listing.select_one("[data-test='client-country'], .client-location")
            client_location = client_el.get_text(strip=True) if client_el else ""

            spent_el = listing.select_one("[data-test='client-spendings'], .client-spend")
            client_spent = spent_el.get_text(strip=True) if spent_el else ""

            signals = ["upwork_project"]
            if budget and budget >= 10000:
                signals.append("high_budget_project")
            if "enterprise" in description.lower() or "large" in description.lower():
                signals.append("enterprise_project")
            if client_spent and self._parse_budget(client_spent):
                spent_amount = self._parse_budget(client_spent)
                if spent_amount and spent_amount > 50000:
                    signals.append("high_spending_client")

            leads.append(PlatformLead(
                source="upwork",
                company_name=title[:100],
                description=description[:500],
                budget_estimate=budget,
                raw_url=job_url,
                location=client_location or None,
                signals=signals,
                skills_needed=found_skills or list(skills),
            ))

            if len(leads) >= max_results:
                break

        return leads

    def _parse_budget(self, text: str) -> int | None:
        match = re.search(r"\$?([\d,]+)", text.replace(" ", ""))
        if match:
            return int(match.group(1).replace(",", ""))
        return None
