"""GitHub crawling for abandoned repos and help-wanted projects via GitHub API."""

import json
import re
from datetime import datetime, timedelta, timezone

from .base import PlatformCrawler, PlatformLead


GITHUB_API = "https://api.github.com"

SIGNAL_KEYWORDS = {
    "abandoned_popular_repo": ["archived", "unmaintained", "deprecated", "inactive"],
    "needs_maintainer": ["looking for maintainer", "maintainer wanted", "new maintainer"],
    "help_wanted": ["help wanted", "good first issue", "contributions welcome"],
}


class GitHubProjectsCrawler(PlatformCrawler):
    platform_name = "github_projects"
    rate_limit = 5.0  # GitHub unauthenticated: 10 req/min for search
    max_concurrency = 3

    async def crawl(self, query: dict) -> list[PlatformLead]:
        action = query.get("action", "abandoned")
        if action == "abandoned":
            return await self._find_abandoned_repos(query)
        elif action == "help_wanted":
            return await self._find_help_wanted(query)
        return await self._find_abandoned_repos(query)

    async def _find_abandoned_repos(self, query: dict) -> list[PlatformLead]:
        """Find popular repos that haven't been updated recently."""
        min_stars = query.get("min_stars", 100)
        max_results = query.get("max_results", 20)
        language = query.get("language", "")

        # Calculate cutoff date: repos not pushed in the last 12 months
        cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

        q_parts = [f"stars:>{min_stars}", f"pushed:<{cutoff}"]
        if language:
            q_parts.append(f"language:{language}")

        search_query = "+".join(q_parts)
        url = (
            f"{GITHUB_API}/search/repositories"
            f"?q={search_query}&sort=stars&order=desc&per_page={min(max_results, 30)}"
        )

        headers = {"Accept": "application/vnd.github.v3+json"}
        raw = await self._throttled_fetch(url, headers=headers)
        data = json.loads(raw)

        leads = []
        for repo in data.get("items", [])[:max_results]:
            name = repo.get("full_name", "")
            description = repo.get("description") or ""
            stars = repo.get("stargazers_count", 0)
            open_issues = repo.get("open_issues_count", 0)
            pushed_at = repo.get("pushed_at", "")
            html_url = repo.get("html_url", "")
            homepage = repo.get("homepage") or ""
            lang = repo.get("language") or ""
            owner = repo.get("owner", {})
            owner_login = owner.get("login", "unknown")

            # Extract domain from homepage
            domain = None
            if homepage:
                dm = re.search(r"https?://(?:www\.)?([^/]+)", homepage)
                if dm and "github" not in dm.group(1):
                    domain = dm.group(1)

            signals = ["abandoned_popular_repo"]
            if open_issues > 50:
                signals.append("many_open_issues")

            leads.append(PlatformLead(
                source="github_projects",
                company_name=name,
                contact_name=owner_login,
                domain=domain,
                description=(
                    f"{description}\n"
                    f"Stars: {stars} | Open Issues: {open_issues} | "
                    f"Last pushed: {pushed_at} | Language: {lang}"
                ),
                raw_url=html_url,
                signals=signals,
                skills_needed=[lang] if lang else [],
            ))

        return leads

    async def _find_help_wanted(self, query: dict) -> list[PlatformLead]:
        """Find repos with many 'help wanted' issues."""
        max_results = query.get("max_results", 20)
        language = query.get("language", "")
        keywords = query.get("keywords", ["help wanted"])

        search_query_parts = ['label:"help wanted"', "state:open"]
        if language:
            search_query_parts.append(f"language:{language}")
        if keywords and keywords != ["help wanted"]:
            kw_str = " ".join(keywords)
            search_query_parts.append(kw_str)

        search_query = "+".join(search_query_parts)
        url = (
            f"{GITHUB_API}/search/issues"
            f"?q={search_query}&sort=created&order=desc&per_page={min(max_results, 30)}"
        )

        headers = {"Accept": "application/vnd.github.v3+json"}
        raw = await self._throttled_fetch(url, headers=headers)
        data = json.loads(raw)

        leads = []
        seen_repos = set()
        for issue in data.get("items", []):
            repo_url = issue.get("repository_url", "")
            # Deduplicate by repo
            if repo_url in seen_repos:
                continue
            seen_repos.add(repo_url)

            title = issue.get("title", "")
            html_url = issue.get("html_url", "")
            user = issue.get("user", {})
            user_login = user.get("login", "unknown")
            labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]

            # Extract repo name from URL
            repo_name = "/".join(repo_url.rsplit("/", 2)[-2:]) if repo_url else "unknown"

            signals = ["help_wanted"]
            if "good first issue" in labels:
                signals.append("good_first_issue")
            if "bug" in labels:
                signals.append("has_bugs")

            leads.append(PlatformLead(
                source="github_projects",
                company_name=repo_name,
                contact_name=user_login,
                description=f"Issue: {title}\nLabels: {', '.join(labels)}",
                raw_url=html_url,
                signals=signals,
            ))

            if len(leads) >= max_results:
                break

        return leads
