"""ProductHunt scraping for new product launches needing dev support."""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import PlatformCrawler, PlatformLead


class ProductHuntCrawler(PlatformCrawler):
    platform_name = "producthunt"
    rate_limit = 3.0
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        """Crawl ProductHunt for recently launched products."""
        days_back = query.get("days_back", 30)
        min_upvotes = query.get("min_upvotes", 50)
        topics = query.get("topics", ["saas", "developer-tools", "productivity"])
        max_results = query.get("max_results", 20)

        all_leads = []

        for topic in topics[:3]:
            url = f"https://www.producthunt.com/topics/{topic}"
            try:
                html = await self._crawl4ai_fetch(url)
            except Exception:
                # Fallback to Google search
                search = f"site:producthunt.com/posts {topic}"
                google_url = f"https://www.google.com/search?q={quote_plus(search)}&num=10&tbs=qdr:m"
                html = await self._throttled_fetch(google_url)

            soup = BeautifulSoup(html, "lxml")

            # Try ProductHunt direct parsing
            for card in soup.select("[data-test='post-item'], .post-item, .styles_item"):
                name_el = card.select_one("h3, .styles_title, [data-test='post-name']")
                if not name_el:
                    continue

                product_name = name_el.get_text(strip=True)
                link_el = card.select_one("a")
                product_url = link_el.get("href", "") if link_el else ""
                if product_url and not product_url.startswith("http"):
                    product_url = f"https://www.producthunt.com{product_url}"

                tagline_el = card.select_one(".styles_tagline, [data-test='post-tagline']")
                tagline = tagline_el.get_text(strip=True) if tagline_el else ""

                vote_el = card.select_one(".styles_voteCount, [data-test='vote-button'] span")
                votes = 0
                if vote_el:
                    match = re.search(r"(\d+)", vote_el.get_text())
                    if match:
                        votes = int(match.group(1))

                if votes < min_upvotes:
                    continue

                signals = ["new_product", "producthunt_launch"]
                if votes > 200:
                    signals.append("popular_launch")
                if "ai" in tagline.lower() or "ai" in product_name.lower():
                    signals.append("ai_product")

                all_leads.append(PlatformLead(
                    source="producthunt",
                    company_name=product_name,
                    description=tagline,
                    raw_url=product_url,
                    signals=signals,
                ))

                if len(all_leads) >= max_results:
                    return all_leads

            # Fallback: parse Google results
            for result in soup.select("div.g"):
                link_tag = result.select_one("a")
                title_tag = result.select_one("h3")
                snippet_tag = result.select_one(".VwiC3b")

                if not link_tag or not title_tag:
                    continue

                href = link_tag.get("href", "")
                if "producthunt.com" not in href:
                    continue

                title = title_tag.get_text(strip=True)
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                all_leads.append(PlatformLead(
                    source="producthunt",
                    company_name=re.sub(r"\s*[\|–-]\s*Product Hunt.*$", "", title),
                    description=snippet,
                    raw_url=href,
                    signals=["new_product", "producthunt_launch"],
                ))

                if len(all_leads) >= max_results:
                    return all_leads

        return all_leads
