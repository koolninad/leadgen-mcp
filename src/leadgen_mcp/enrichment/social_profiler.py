"""Social profile enrichment - find and verify profiles across platforms."""

import asyncio
import re

import httpx

from ..utils.http import create_client

PLATFORMS = {
    "github": "https://github.com/{username}",
    "twitter": "https://twitter.com/{username}",
    "linkedin": "https://linkedin.com/in/{username}",
    "reddit": "https://reddit.com/user/{username}",
    "producthunt": "https://producthunt.com/@{username}",
    "devto": "https://dev.to/{username}",
    "medium": "https://medium.com/@{username}",
    "dribbble": "https://dribbble.com/{username}",
    "behance": "https://behance.net/{username}",
    "stackoverflow": "https://stackoverflow.com/users/{username}",
}

# GitHub API is public and returns rich profile data without auth
GITHUB_API_URL = "https://api.github.com/users/{username}"
GITHUB_USER_AGENT = "LeadGen/1.0 (social profiling)"


class SocialProfiler:
    """Find and verify social profiles for a username or company."""

    async def _check_profile(
        self,
        client: httpx.AsyncClient,
        platform: str,
        url: str,
    ) -> tuple[str, str | None]:
        """Check if a profile URL returns 200 (exists).

        Returns a tuple of (platform, url_or_none).
        """
        try:
            resp = await client.get(url, follow_redirects=True)
            # Some platforms return 200 with a "not found" page,
            # but most return 404 for non-existent profiles.
            if resp.status_code == 200:
                return (platform, url)
        except (httpx.HTTPError, httpx.TimeoutException):
            pass
        return (platform, None)

    async def find_profiles(self, username: str) -> dict:
        """Check which platforms a username exists on.

        Args:
            username: The username to search for across platforms.

        Returns:
            dict with 'username', 'found' (dict of platform->url),
            and 'checked' (total platforms checked).
        """
        found: dict[str, str] = {}
        urls = {
            platform: template.format(username=username)
            for platform, template in PLATFORMS.items()
        }

        async with create_client(timeout=15.0, proxy=None) as client:
            tasks = [
                self._check_profile(client, platform, url)
                for platform, url in urls.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            platform, url = result
            if url is not None:
                found[platform] = url

        return {
            "username": username,
            "found": found,
            "checked": len(PLATFORMS),
            "found_count": len(found),
        }

    async def enrich_from_github(self, username: str) -> dict:
        """Get detailed info from GitHub's public user API.

        Args:
            username: GitHub username.

        Returns:
            dict with profile fields or error info.
        """
        url = GITHUB_API_URL.format(username=username)

        async with create_client(timeout=15.0, proxy=None) as client:
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": GITHUB_USER_AGENT},
                )
                if resp.status_code != 200:
                    return {"error": f"GitHub returned {resp.status_code}", "username": username}
                data = resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                return {"error": str(exc), "username": username}

        return {
            "username": username,
            "name": data.get("name"),
            "company": data.get("company"),
            "blog": data.get("blog"),
            "location": data.get("location"),
            "bio": data.get("bio"),
            "public_repos": data.get("public_repos"),
            "followers": data.get("followers"),
            "following": data.get("following"),
            "created_at": data.get("created_at"),
            "avatar_url": data.get("avatar_url"),
            "html_url": data.get("html_url"),
            "twitter_username": data.get("twitter_username"),
            "hireable": data.get("hireable"),
        }

    async def find_company_profiles(
        self,
        company_name: str,
        domain: str = "",
    ) -> dict:
        """Find social media profiles for a company.

        Tries common username variations derived from the company name.

        Args:
            company_name: Human-readable company name.
            domain: Optional company domain for additional username guesses.

        Returns:
            dict mapping each candidate username to its found profiles.
        """
        # Generate candidate usernames
        base = re.sub(r"[^a-zA-Z0-9\s]", "", company_name).strip()
        words = base.lower().split()

        candidates: list[str] = []
        if words:
            candidates.append("".join(words))          # "acmecorp"
            candidates.append("_".join(words))          # "acme_corp"
            candidates.append("-".join(words))          # "acme-corp"
            if len(words) > 1:
                candidates.append(words[0])             # first word only

        # Derive username from domain (e.g., "acme.com" -> "acme")
        if domain:
            domain_name = domain.split(".")[0].lower()
            if domain_name and domain_name not in candidates:
                candidates.append(domain_name)

        # De-duplicate while preserving order
        seen: set[str] = set()
        unique_candidates: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)

        all_results: dict[str, dict] = {}
        for candidate in unique_candidates[:5]:  # limit to 5 variations
            result = await self.find_profiles(candidate)
            if result["found_count"] > 0:
                all_results[candidate] = result["found"]

        return {
            "company_name": company_name,
            "domain": domain,
            "candidates_checked": unique_candidates[:5],
            "profiles_found": all_results,
        }
