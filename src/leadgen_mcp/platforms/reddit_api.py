"""Reddit scraper using Reddit's public JSON API (no auth needed)."""

import re
import asyncio
from datetime import datetime, timezone

from .base import PlatformCrawler, PlatformLead
from ..utils.http import create_client

REDDIT_USER_AGENT = "LeadGen/1.0 (lead research tool)"

SUBREDDITS = {
    "hiring": ["forhire", "remotejs", "jobbit", "hiring"],
    "startups": ["startups", "entrepreneur", "smallbusiness", "SideProject"],
    "tech_help": ["webdev", "web_design", "freelance", "slavelabour"],
}

SIGNAL_PATTERNS = {
    "hiring": re.compile(
        r"\[hiring\]|\[HIRING\]|looking\s+for\s+(a\s+)?developer|need\s+(a\s+)?developer",
        re.I,
    ),
    "budget_mentioned": re.compile(
        r"\$\s*[\d,]+k?|\$\s*\d+[\d,]*\s*-\s*\$?\s*\d+[\d,]*k?|budget\s*:?\s*\$|pay(ing)?\s+\$|rate\s*:?\s*\$",
        re.I,
    ),
    "needs_developer": re.compile(
        r"need\s+(a\s+)?(web\s+)?dev|looking\s+for\s+freelanc|hiring\s+dev|"
        r"looking\s+for\s+(a\s+)?(developer|designer|agency|programmer|coder)",
        re.I,
    ),
    "needs_website": re.compile(
        r"need\s+(a\s+)?website|build\s+(a\s+)?site|web\s+presence|"
        r"need\s+(a\s+)?(app|software|application)\s+built",
        re.I,
    ),
    "startup_cofounder": re.compile(
        r"(startup|company)\s+looking\s+for\s+(CTO|technical\s+cofounder|tech\s+lead)|"
        r"looking\s+for\s+(a\s+)?(CTO|technical\s+cofounder)",
        re.I,
    ),
    "app_broken": re.compile(
        r"app\s+(is\s+)?broken|site\s+(is\s+)?down|bug(gy)?|not\s+working",
        re.I,
    ),
}

# Budget extraction pattern
BUDGET_PATTERN = re.compile(
    r"\$\s*([\d,]+)\s*k|\$\s*([\d,]+(?:\.\d+)?)", re.I
)


def _extract_budget(text: str) -> int | None:
    """Try to extract a dollar budget from text."""
    match = BUDGET_PATTERN.search(text)
    if not match:
        return None
    if match.group(1):
        # e.g. "$10k" -> 10000
        raw = match.group(1).replace(",", "")
        try:
            return int(float(raw) * 1000)
        except ValueError:
            return None
    if match.group(2):
        raw = match.group(2).replace(",", "")
        try:
            val = int(float(raw))
            return val if val >= 100 else None  # filter noise
        except ValueError:
            return None
    return None


def _detect_signals(text: str) -> list[str]:
    """Detect hiring/need signals from combined title + selftext."""
    signals = []
    for signal_name, pattern in SIGNAL_PATTERNS.items():
        if pattern.search(text):
            signals.append(signal_name)
    return signals


def _post_to_lead(post_data: dict) -> PlatformLead:
    """Convert a Reddit post JSON object to a PlatformLead."""
    title = post_data.get("title", "")
    selftext = post_data.get("selftext", "")
    author = post_data.get("author", "[deleted]")
    subreddit = post_data.get("subreddit", "unknown")
    score = post_data.get("score", 0)
    num_comments = post_data.get("num_comments", 0)
    permalink = post_data.get("permalink", "")
    url = post_data.get("url", "")
    created_utc = post_data.get("created_utc", 0)

    full_url = f"https://www.reddit.com{permalink}" if permalink else url
    combined = f"{title} {selftext}"

    signals = _detect_signals(combined)
    budget = _extract_budget(combined)

    # Build a truncated description
    desc_body = selftext[:500] if selftext else ""
    description = f"[r/{subreddit}] {title}"
    if desc_body:
        description += f"\n{desc_body}"
    if score:
        description += f"\n[Score: {score} | Comments: {num_comments}]"

    # Use post title as company/lead name (cleaned up)
    lead_name = re.sub(r"\[.*?\]\s*", "", title).strip()[:80] or title[:80]

    return PlatformLead(
        source="reddit",
        company_name=lead_name,
        contact_name=author if author != "[deleted]" else None,
        description=description,
        raw_url=full_url,
        signals=signals or ["reddit_post"],
        budget_estimate=budget,
        skills_needed=[],
    )


class RedditAPICrawler(PlatformCrawler):
    """Crawler using Reddit's public JSON endpoints (no authentication required)."""

    platform_name = "reddit"
    rate_limit = 1.0  # ~60 req/min for public API
    max_concurrency = 2

    def _headers(self) -> dict:
        return {"User-Agent": REDDIT_USER_AGENT}

    async def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        """Fetch a Reddit JSON endpoint and return parsed data."""
        await self._bucket.acquire()
        async with create_client(timeout=30.0, proxy=None) as client:
            resp = await client.get(
                url,
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def crawl(self, query: dict) -> list[PlatformLead]:
        action = query.get("action", "search")
        if action == "search":
            return await self._search(query)
        elif action == "monitor_subreddits":
            return await self._monitor_subreddits(query)
        elif action == "hot":
            return await self._get_hot(query)
        return []

    async def _search(self, query: dict) -> list[PlatformLead]:
        """Search specific subreddits for hiring/project posts."""
        keywords = query.get("keywords", [
            "hiring developer", "looking for developer", "need website",
        ])
        subreddits = query.get("subreddits", SUBREDDITS["hiring"])
        max_results = query.get("max_results", 30)

        all_leads: list[PlatformLead] = []

        for sub in subreddits:
            for kw in keywords[:3]:
                if len(all_leads) >= max_results:
                    break

                url = f"https://www.reddit.com/r/{sub}/search.json"
                params = {
                    "q": kw,
                    "sort": "new",
                    "restrict_sr": "on",
                    "limit": 10,
                    "t": "month",
                }

                try:
                    data = await self._fetch_json(url, params)
                except Exception:
                    continue

                children = data.get("data", {}).get("children", [])
                for child in children:
                    if len(all_leads) >= max_results:
                        break
                    post = child.get("data", {})
                    if not post.get("title"):
                        continue
                    lead = _post_to_lead(post)
                    # Only include posts with real signals (skip generic)
                    if any(s != "reddit_post" for s in lead.signals):
                        all_leads.append(lead)
                    elif lead.budget_estimate:
                        all_leads.append(lead)
                    else:
                        # Still include, just lower priority
                        all_leads.append(lead)

                # Rate limit between requests
                await asyncio.sleep(1.0)

            if len(all_leads) >= max_results:
                break

        return all_leads[:max_results]

    async def _monitor_subreddits(self, query: dict) -> list[PlatformLead]:
        """Monitor subreddit new posts for hiring signals."""
        subreddits = query.get(
            "subreddits",
            SUBREDDITS["hiring"] + SUBREDDITS["startups"],
        )
        max_results = query.get("max_results", 30)

        all_leads: list[PlatformLead] = []

        for sub in subreddits:
            if len(all_leads) >= max_results:
                break

            url = f"https://www.reddit.com/r/{sub}/new.json"
            params = {"limit": 25}

            try:
                data = await self._fetch_json(url, params)
            except Exception:
                continue

            children = data.get("data", {}).get("children", [])
            for child in children:
                if len(all_leads) >= max_results:
                    break
                post = child.get("data", {})
                if not post.get("title"):
                    continue

                lead = _post_to_lead(post)
                # For monitoring, only include posts with hiring signals
                if any(s != "reddit_post" for s in lead.signals):
                    all_leads.append(lead)

            await asyncio.sleep(1.0)

        return all_leads[:max_results]

    async def _get_hot(self, query: dict) -> list[PlatformLead]:
        """Get hot/trending posts from relevant subreddits."""
        subreddits = query.get(
            "subreddits",
            SUBREDDITS["hiring"] + SUBREDDITS["tech_help"],
        )
        max_results = query.get("max_results", 30)

        all_leads: list[PlatformLead] = []

        for sub in subreddits:
            if len(all_leads) >= max_results:
                break

            url = f"https://www.reddit.com/r/{sub}/hot.json"
            params = {"limit": 25}

            try:
                data = await self._fetch_json(url, params)
            except Exception:
                continue

            children = data.get("data", {}).get("children", [])
            for child in children:
                if len(all_leads) >= max_results:
                    break
                post = child.get("data", {})
                if not post.get("title"):
                    continue
                # Skip stickied/pinned posts
                if post.get("stickied"):
                    continue

                lead = _post_to_lead(post)
                all_leads.append(lead)

            await asyncio.sleep(1.0)

        return all_leads[:max_results]
