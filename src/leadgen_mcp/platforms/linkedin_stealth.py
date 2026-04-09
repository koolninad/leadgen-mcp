"""LinkedIn stealth browser scraper using Playwright.

Uses playwright-stealth to avoid detection. Logs into a burner account,
saves session cookies for reuse, and extracts data with human-like delays.
"""

import asyncio
import json
import logging
import random
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth

from .base import PlatformLead
from ..config import settings

logger = logging.getLogger(__name__)

# Hard limit to avoid LinkedIn bans
MAX_REQUESTS_PER_SESSION = 100


class LinkedInStealth:
    """Stealth LinkedIn scraper with session persistence."""

    def __init__(self):
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._session_path = Path(settings.linkedin_session_file)
        self._request_count = 0
        self._playwright = None

    async def start(self):
        """Launch browser and login to LinkedIn."""
        if self._browser is not None:
            return

        self._session_path.parent.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.linkedin_headless,
            slow_mo=settings.linkedin_slow_mo,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )

        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
        )

        self._page = await self._context.new_page()
        stealth = Stealth()
        await stealth.apply_stealth(self._page)

        # Try loading saved session first
        if await self._load_session(self._context):
            logger.info("LinkedIn session restored from cookies")
            # Verify session is still valid
            await self._page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            await self._human_delay(2.0, 4.0)
            if "/login" in self._page.url or "/authwall" in self._page.url:
                logger.info("Saved session expired, performing fresh login")
                await self._login(self._page)
            else:
                logger.info("LinkedIn session is valid")
        else:
            await self._login(self._page)

    async def _login(self, page: Page):
        """Perform LinkedIn login with human-like typing."""
        logger.info("Logging into LinkedIn...")
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await self._human_delay(1.5, 3.0)

        # Type email slowly
        await self._human_type(page, "#username", settings.linkedin_email)
        await self._human_delay(0.5, 1.5)

        # Type password slowly
        await self._human_type(page, "#password", settings.linkedin_password)
        await self._human_delay(0.5, 1.0)

        # Click sign in
        await page.click('button[type="submit"]')
        await self._human_delay(3.0, 6.0)

        # Check for verification / CAPTCHA challenges
        current_url = page.url
        if "checkpoint" in current_url or "challenge" in current_url:
            logger.warning(
                "LinkedIn verification/CAPTCHA detected at %s. "
                "If running headed, complete it manually within 120 seconds.",
                current_url,
            )
            # Wait up to 120 seconds for manual intervention
            for _ in range(60):
                await asyncio.sleep(2)
                if "checkpoint" not in page.url and "challenge" not in page.url:
                    break
            else:
                logger.error("Verification not completed in time, session may be limited")

        if "/feed" in page.url or "linkedin.com/in/" in page.url:
            logger.info("LinkedIn login successful")
            await self._save_session(page)
        else:
            logger.warning("Login may have failed, current URL: %s", page.url)

    async def _save_session(self, page: Page):
        """Save browser cookies to file for session reuse."""
        cookies = await self._context.cookies()
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_path.write_text(json.dumps(cookies, indent=2))
        logger.info("LinkedIn session saved to %s", self._session_path)

    async def _load_session(self, context: BrowserContext) -> bool:
        """Load saved cookies. Returns True if session file exists and cookies were loaded."""
        if not self._session_path.exists():
            return False
        try:
            cookies = json.loads(self._session_path.read_text())
            await context.add_cookies(cookies)
            logger.info("Loaded %d cookies from session file", len(cookies))
            return True
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to load session cookies: %s", exc)
            return False

    async def _human_delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Random delay to mimic human behavior."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def _human_type(self, page: Page, selector: str, text: str):
        """Type text with random delays between keystrokes."""
        await page.click(selector)
        for char in text:
            await page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.2))

    async def _scroll_page(self, page: Page, times: int = 3):
        """Scroll down the page like a human."""
        for _ in range(times):
            scroll_amount = random.randint(300, 700)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await self._human_delay(1.0, 2.5)

    def _check_rate_limit(self):
        """Check if we've hit the per-session request limit."""
        self._request_count += 1
        if self._request_count > MAX_REQUESTS_PER_SESSION:
            raise RuntimeError(
                f"LinkedIn session request limit ({MAX_REQUESTS_PER_SESSION}) reached. "
                "Close and restart to continue."
            )

    async def _safe_goto(self, url: str):
        """Navigate to a URL with rate limit check and human delay."""
        self._check_rate_limit()
        await self._page.goto(url, wait_until="domcontentloaded")
        await self._human_delay(2.0, 4.0)

    async def search_companies(
        self, keywords: str, location: str = "", max_results: int = 20
    ) -> list[PlatformLead]:
        """Search LinkedIn for companies.

        URL: linkedin.com/search/results/companies/?keywords=...
        Extract: company name, industry, size, description, website
        """
        await self.start()
        leads: list[PlatformLead] = []

        search_q = keywords
        if location:
            search_q += f" {location}"

        url = f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(search_q)}"
        await self._safe_goto(url)
        await self._scroll_page(self._page, times=2)

        page_num = 1
        while len(leads) < max_results:
            # Primary selectors with fallbacks
            cards = await self._page.query_selector_all(
                ".entity-result__item, .reusable-search__result-container, li.reusable-search__result-container"
            )
            if not cards:
                # Broader fallback
                cards = await self._page.query_selector_all(
                    '[data-chameleon-result-urn*="company"], .search-result__wrapper'
                )

            if not cards:
                logger.warning("No company search result cards found on page %d", page_num)
                break

            for card in cards:
                if len(leads) >= max_results:
                    break
                try:
                    # Company name
                    name_el = await card.query_selector(
                        ".entity-result__title-text a span span, "
                        ".entity-result__title-text a, "
                        ".app-aware-link span span"
                    )
                    company_name = (await name_el.inner_text()).strip() if name_el else "Unknown"

                    # Link
                    link_el = await card.query_selector(
                        ".entity-result__title-text a, a.app-aware-link"
                    )
                    company_url = await link_el.get_attribute("href") if link_el else ""

                    # Industry / subtitle
                    subtitle_el = await card.query_selector(
                        ".entity-result__primary-subtitle, "
                        ".entity-result__summary, "
                        ".subline-level-1"
                    )
                    industry = (await subtitle_el.inner_text()).strip() if subtitle_el else ""

                    # Secondary subtitle (often location/size)
                    secondary_el = await card.query_selector(
                        ".entity-result__secondary-subtitle, .subline-level-2"
                    )
                    secondary = (await secondary_el.inner_text()).strip() if secondary_el else ""

                    # Description snippet
                    desc_el = await card.query_selector(
                        ".entity-result__summary, .entity-result__content-summary"
                    )
                    description = (await desc_el.inner_text()).strip() if desc_el else ""

                    # Parse company size from secondary text
                    company_size = None
                    if secondary:
                        for token in ["employees", "staff", "people"]:
                            if token in secondary.lower():
                                company_size = secondary
                                break

                    leads.append(PlatformLead(
                        source="linkedin_stealth",
                        company_name=company_name,
                        description=description or industry,
                        raw_url=company_url if company_url else url,
                        location=secondary if not company_size else (location or None),
                        industry=industry or None,
                        company_size=company_size,
                        signals=["linkedin_company_search"],
                        skills_needed=keywords.split(),
                    ))
                except Exception as exc:
                    logger.debug("Error parsing company card: %s", exc)
                    continue

            # Pagination
            if len(leads) >= max_results:
                break
            page_num += 1
            next_btn = await self._page.query_selector(
                'button[aria-label="Next"], button.artdeco-pagination__button--next'
            )
            if next_btn and await next_btn.is_enabled():
                await next_btn.click()
                await self._human_delay(2.0, 4.0)
                await self._scroll_page(self._page, times=2)
                self._check_rate_limit()
            else:
                break

        return leads

    async def search_jobs(
        self, keywords: str, location: str = "", max_results: int = 20
    ) -> list[PlatformLead]:
        """Search LinkedIn for job postings.

        URL: linkedin.com/jobs/search/?keywords=...
        Extract: job title, company, location, description, signals
        """
        await self.start()
        leads: list[PlatformLead] = []

        search_q = keywords
        loc_param = f"&location={quote_plus(location)}" if location else ""
        url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(search_q)}{loc_param}"
        await self._safe_goto(url)
        await self._scroll_page(self._page, times=3)

        page_num = 1
        while len(leads) < max_results:
            cards = await self._page.query_selector_all(
                ".job-card-container, .jobs-search-results__list-item, "
                "li.jobs-search-results__list-item, .job-card-list__entity-lockup"
            )
            if not cards:
                cards = await self._page.query_selector_all(
                    '[data-job-id], .base-card, .base-search-card'
                )

            if not cards:
                logger.warning("No job cards found on page %d", page_num)
                break

            for card in cards:
                if len(leads) >= max_results:
                    break
                try:
                    # Job title
                    title_el = await card.query_selector(
                        ".job-card-container__link strong, "
                        ".job-card-list__title, "
                        "a.job-card-container__link, "
                        ".base-search-card__title"
                    )
                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"

                    # Company name
                    company_el = await card.query_selector(
                        ".job-card-container__primary-description, "
                        ".job-card-container__company-name, "
                        ".base-search-card__subtitle a, "
                        ".artdeco-entity-lockup__subtitle"
                    )
                    company = (await company_el.inner_text()).strip() if company_el else ""

                    # Location
                    loc_el = await card.query_selector(
                        ".job-card-container__metadata-wrapper, "
                        ".job-card-container__metadata-item, "
                        ".base-search-card__metadata, "
                        ".artdeco-entity-lockup__caption"
                    )
                    job_location = (await loc_el.inner_text()).strip() if loc_el else ""

                    # Link
                    link_el = await card.query_selector(
                        "a.job-card-container__link, a.base-card__full-link, a[href*='/jobs/view/']"
                    )
                    job_url = await link_el.get_attribute("href") if link_el else ""

                    # Build signals
                    signals = ["hiring_tech_role"]
                    title_lower = title.lower()
                    for kw in ["senior", "lead", "architect", "full-stack", "fullstack", "cto", "vp"]:
                        if kw in title_lower:
                            signals.append(f"hiring_{kw.replace('-', '_')}")

                    leads.append(PlatformLead(
                        source="linkedin_stealth_jobs",
                        company_name=company or title,
                        description=f"{title} - {company} - {job_location}",
                        raw_url=job_url if job_url else url,
                        location=job_location or location or None,
                        signals=signals,
                        skills_needed=keywords.split(),
                    ))
                except Exception as exc:
                    logger.debug("Error parsing job card: %s", exc)
                    continue

            # Pagination
            if len(leads) >= max_results:
                break
            page_num += 1
            next_btn = await self._page.query_selector(
                'button[aria-label="Next"], button.artdeco-pagination__button--next, '
                'li.artdeco-pagination__indicator--number button'
            )
            if next_btn and await next_btn.is_enabled():
                await next_btn.click()
                await self._human_delay(2.0, 4.0)
                await self._scroll_page(self._page, times=3)
                self._check_rate_limit()
            else:
                break

        return leads

    async def search_people(
        self, title: str, company: str = "", max_results: int = 10
    ) -> list[dict]:
        """Search for people (decision makers).

        URL: linkedin.com/search/results/people/?keywords=CTO+{company}
        Extract: name, title, company, profile URL
        """
        await self.start()
        results: list[dict] = []

        search_q = title
        if company:
            search_q += f" {company}"

        url = f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(search_q)}"
        await self._safe_goto(url)
        await self._scroll_page(self._page, times=2)

        cards = await self._page.query_selector_all(
            ".entity-result__item, .reusable-search__result-container, "
            "li.reusable-search__result-container"
        )
        if not cards:
            cards = await self._page.query_selector_all(
                '[data-chameleon-result-urn*="member"], .search-result__wrapper'
            )

        for card in cards:
            if len(results) >= max_results:
                break
            try:
                # Name
                name_el = await card.query_selector(
                    ".entity-result__title-text a span span, "
                    ".entity-result__title-text a, "
                    ".app-aware-link span span"
                )
                name = (await name_el.inner_text()).strip() if name_el else "Unknown"
                # Filter out "LinkedIn Member" placeholder
                if "linkedin member" in name.lower():
                    continue

                # Title/subtitle
                title_el = await card.query_selector(
                    ".entity-result__primary-subtitle, .subline-level-1"
                )
                person_title = (await title_el.inner_text()).strip() if title_el else ""

                # Secondary (often location)
                secondary_el = await card.query_selector(
                    ".entity-result__secondary-subtitle, .subline-level-2"
                )
                person_location = (await secondary_el.inner_text()).strip() if secondary_el else ""

                # Profile link
                link_el = await card.query_selector(
                    ".entity-result__title-text a, a.app-aware-link"
                )
                profile_url = await link_el.get_attribute("href") if link_el else ""

                results.append({
                    "name": name,
                    "title": person_title,
                    "company": company,
                    "location": person_location,
                    "profile_url": profile_url,
                })
            except Exception as exc:
                logger.debug("Error parsing people card: %s", exc)
                continue

        return results

    async def get_company_page(self, company_url: str) -> dict:
        """Scrape a company's LinkedIn page.

        Extract: description, website, industry, size, locations, recent posts
        """
        await self.start()
        result: dict = {
            "url": company_url,
            "name": "",
            "description": "",
            "website": "",
            "industry": "",
            "company_size": "",
            "headquarters": "",
            "founded": "",
            "specialties": "",
            "recent_posts": [],
        }

        # Ensure we go to the about page for full details
        about_url = company_url.rstrip("/")
        if not about_url.endswith("/about"):
            about_url += "/about"

        await self._safe_goto(about_url)
        await self._scroll_page(self._page, times=2)

        # Company name
        name_el = await self._page.query_selector(
            "h1.org-top-card-summary__title, h1.top-card-layout__title, "
            "h1 span.org-top-card-summary__title"
        )
        if name_el:
            result["name"] = (await name_el.inner_text()).strip()

        # Description (about section)
        desc_el = await self._page.query_selector(
            "p.break-words, section.org-about-module__description, "
            ".org-about-us-organization-description__text, "
            "div.org-page-details-module__card-spacing p"
        )
        if desc_el:
            result["description"] = (await desc_el.inner_text()).strip()

        # Detail fields on the about page
        detail_items = await self._page.query_selector_all(
            "dl.org-page-details__definition-list dt, "
            ".org-about-company-module__company-size-definition-list dt"
        )
        detail_values = await self._page.query_selector_all(
            "dl.org-page-details__definition-list dd, "
            ".org-about-company-module__company-size-definition-list dd"
        )

        for dt_el, dd_el in zip(detail_items, detail_values):
            try:
                label = (await dt_el.inner_text()).strip().lower()
                value = (await dd_el.inner_text()).strip()

                if "website" in label:
                    result["website"] = value
                elif "industry" in label:
                    result["industry"] = value
                elif "company size" in label or "employees" in label:
                    result["company_size"] = value
                elif "headquarters" in label:
                    result["headquarters"] = value
                elif "founded" in label:
                    result["founded"] = value
                elif "specialties" in label or "specialities" in label:
                    result["specialties"] = value
            except Exception:
                continue

        # Try getting recent posts from the main page
        posts_url = company_url.rstrip("/") + "/posts/"
        await self._safe_goto(posts_url)
        await self._human_delay(1.5, 3.0)
        await self._scroll_page(self._page, times=2)

        post_containers = await self._page.query_selector_all(
            ".feed-shared-update-v2, .update-components-text, "
            ".org-update-card, .occludable-update"
        )
        for container in post_containers[:5]:  # Limit to 5 recent posts
            try:
                text_el = await container.query_selector(
                    ".feed-shared-text__text-view, .update-components-text__text-view, "
                    ".break-words span"
                )
                if text_el:
                    post_text = (await text_el.inner_text()).strip()
                    if post_text and len(post_text) > 20:
                        result["recent_posts"].append(post_text[:500])
            except Exception:
                continue

        return result

    async def search_posts(
        self, keywords: str, max_results: int = 20
    ) -> list[PlatformLead]:
        """Search LinkedIn posts/feed for intent signals.

        URL: linkedin.com/search/results/content/?keywords=...
        Look for: "looking for developer", "hiring", project announcements
        """
        await self.start()
        leads: list[PlatformLead] = []

        url = f"https://www.linkedin.com/search/results/content/?keywords={quote_plus(keywords)}"
        await self._safe_goto(url)
        await self._scroll_page(self._page, times=4)

        post_containers = await self._page.query_selector_all(
            ".feed-shared-update-v2, .update-components-actor, "
            ".reusable-search__result-container, .search-content__result-container"
        )
        if not post_containers:
            post_containers = await self._page.query_selector_all(
                '[data-urn*="activity"], .occludable-update'
            )

        for container in post_containers:
            if len(leads) >= max_results:
                break
            try:
                # Author info
                author_el = await container.query_selector(
                    ".update-components-actor__name span span, "
                    ".feed-shared-actor__name span span, "
                    ".update-components-actor__title span span"
                )
                author = (await author_el.inner_text()).strip() if author_el else "Unknown"

                # Author subtitle (company/title)
                subtitle_el = await container.query_selector(
                    ".update-components-actor__description span, "
                    ".feed-shared-actor__description span, "
                    ".update-components-actor__sub-description span"
                )
                author_title = (await subtitle_el.inner_text()).strip() if subtitle_el else ""

                # Post text
                text_el = await container.query_selector(
                    ".feed-shared-text__text-view, "
                    ".update-components-text__text-view, "
                    ".break-words span[dir='ltr']"
                )
                post_text = (await text_el.inner_text()).strip() if text_el else ""

                if not post_text or len(post_text) < 20:
                    continue

                # Detect intent signals
                signals = ["linkedin_post"]
                text_lower = post_text.lower()
                signal_keywords = {
                    "hiring": "hiring_signal",
                    "looking for a developer": "needs_developer",
                    "looking for developer": "needs_developer",
                    "need a developer": "needs_developer",
                    "need developer": "needs_developer",
                    "technical co-founder": "needs_cofounder",
                    "technical cofounder": "needs_cofounder",
                    "building": "building_project",
                    "just raised": "funding_announcement",
                    "series a": "funding_announcement",
                    "seed round": "funding_announcement",
                    "launched": "product_launch",
                    "struggling with": "tech_struggle",
                    "broken": "tech_struggle",
                }
                for trigger, signal in signal_keywords.items():
                    if trigger in text_lower and signal not in signals:
                        signals.append(signal)

                # Post link
                link_el = await container.query_selector(
                    "a[href*='activity'], a[href*='ugcPost']"
                )
                post_url = await link_el.get_attribute("href") if link_el else ""

                leads.append(PlatformLead(
                    source="linkedin_stealth_posts",
                    company_name=author,
                    contact_name=author,
                    description=f"{author_title}\n\n{post_text[:1000]}",
                    raw_url=post_url if post_url else url,
                    signals=signals,
                    skills_needed=keywords.split(),
                ))
            except Exception as exc:
                logger.debug("Error parsing post: %s", exc)
                continue

        return leads

    async def close(self):
        """Clean up browser."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._request_count = 0


# ---------------------------------------------------------------------------
# Singleton instance for reuse across MCP tool calls
# ---------------------------------------------------------------------------
_instance: LinkedInStealth | None = None


async def _get_stealth() -> LinkedInStealth:
    global _instance
    if _instance is None:
        _instance = LinkedInStealth()
    return _instance


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

def register(mcp):
    """Register LinkedIn stealth browser tools with the MCP server."""

    @mcp.tool()
    async def linkedin_search_companies(
        keywords: str,
        location: str = "",
        max_results: int = 20,
    ) -> dict:
        """Search LinkedIn directly (via stealth browser) for companies matching keywords.
        Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD to be configured.

        Args:
            keywords: Search keywords (e.g., 'fintech startup', 'healthcare SaaS')
            location: Geographic location filter (e.g., 'San Francisco')
            max_results: Maximum number of results (default 20, max 50)
        """
        if not settings.linkedin_email or not settings.linkedin_password:
            return {"error": "LinkedIn credentials not configured. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD."}
        try:
            stealth = await _get_stealth()
            leads = await stealth.search_companies(keywords, location, min(max_results, 50))
            return {
                "source": "linkedin_stealth",
                "type": "companies",
                "total": len(leads),
                "leads": [lead.to_dict() for lead in leads],
            }
        except Exception as exc:
            logger.exception("linkedin_search_companies failed")
            return {"error": str(exc)}

    @mcp.tool()
    async def linkedin_search_jobs(
        keywords: str,
        location: str = "",
        max_results: int = 20,
    ) -> dict:
        """Search LinkedIn job postings via stealth browser for hiring signals.
        Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD to be configured.

        Args:
            keywords: Job search keywords (e.g., 'software developer', 'CTO')
            location: Geographic location filter
            max_results: Maximum number of results (default 20, max 50)
        """
        if not settings.linkedin_email or not settings.linkedin_password:
            return {"error": "LinkedIn credentials not configured. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD."}
        try:
            stealth = await _get_stealth()
            leads = await stealth.search_jobs(keywords, location, min(max_results, 50))
            return {
                "source": "linkedin_stealth",
                "type": "jobs",
                "total": len(leads),
                "leads": [lead.to_dict() for lead in leads],
            }
        except Exception as exc:
            logger.exception("linkedin_search_jobs failed")
            return {"error": str(exc)}

    @mcp.tool()
    async def linkedin_search_people(
        title: str,
        company: str = "",
        max_results: int = 10,
    ) -> dict:
        """Search LinkedIn for decision makers (people) via stealth browser.
        Great for finding CTOs, VPs of Engineering, founders at target companies.
        Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD to be configured.

        Args:
            title: Job title to search (e.g., 'CTO', 'VP Engineering', 'Founder')
            company: Optional company name to filter by
            max_results: Maximum number of results (default 10, max 25)
        """
        if not settings.linkedin_email or not settings.linkedin_password:
            return {"error": "LinkedIn credentials not configured. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD."}
        try:
            stealth = await _get_stealth()
            people = await stealth.search_people(title, company, min(max_results, 25))
            return {
                "source": "linkedin_stealth",
                "type": "people",
                "total": len(people),
                "people": people,
            }
        except Exception as exc:
            logger.exception("linkedin_search_people failed")
            return {"error": str(exc)}

    @mcp.tool()
    async def linkedin_search_posts(
        keywords: str,
        max_results: int = 20,
    ) -> dict:
        """Search LinkedIn posts/feed for intent signals via stealth browser.
        Finds posts about hiring, needing developers, project announcements, funding.
        Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD to be configured.

        Args:
            keywords: Search keywords (e.g., 'looking for developer', 'need CTO', 'just raised')
            max_results: Maximum number of results (default 20, max 50)
        """
        if not settings.linkedin_email or not settings.linkedin_password:
            return {"error": "LinkedIn credentials not configured. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD."}
        try:
            stealth = await _get_stealth()
            leads = await stealth.search_posts(keywords, min(max_results, 50))
            return {
                "source": "linkedin_stealth",
                "type": "posts",
                "total": len(leads),
                "leads": [lead.to_dict() for lead in leads],
            }
        except Exception as exc:
            logger.exception("linkedin_search_posts failed")
            return {"error": str(exc)}

    @mcp.tool()
    async def linkedin_company_page(url: str) -> dict:
        """Scrape a specific LinkedIn company page for detailed info.
        Extracts: description, website, industry, size, headquarters, specialties, recent posts.
        Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD to be configured.

        Args:
            url: LinkedIn company page URL (e.g., 'https://www.linkedin.com/company/acme-corp/')
        """
        if not settings.linkedin_email or not settings.linkedin_password:
            return {"error": "LinkedIn credentials not configured. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD."}
        if "linkedin.com/company" not in url:
            return {"error": "URL must be a LinkedIn company page (linkedin.com/company/...)"}
        try:
            stealth = await _get_stealth()
            data = await stealth.get_company_page(url)
            return {"source": "linkedin_stealth", "type": "company_page", "data": data}
        except Exception as exc:
            logger.exception("linkedin_company_page failed")
            return {"error": str(exc)}
