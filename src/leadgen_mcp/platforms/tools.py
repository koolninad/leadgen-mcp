"""MCP tool definitions for the Platform Crawler module."""

from .linkedin import LinkedInCrawler
from .clutch import ClutchCrawler
from .upwork import UpworkCrawler
from .wellfound import WellfoundCrawler
from .goodfirms import GoodFirmsCrawler
from .g2 import G2Crawler
from .indiehackers import IndieHackersCrawler
from .producthunt import ProductHuntCrawler
from .reddit import RedditCrawler
from .reddit_api import RedditAPICrawler
from .twitter import TwitterCrawler
from .hackernews import HackerNewsCrawler
from .crunchbase import CrunchbaseCrawler
from .github_projects import GitHubProjectsCrawler
from .google_maps import GoogleMapsCrawler
from .quora import QuoraCrawler
from .ct_log import CTLogCrawler
from .company_registry import CompanyRegistryCrawler
from .yellowpages import YellowPagesCrawler
from .accessibility_scanner import AccessibilityScannerCrawler
from .broken_sites import BrokenSiteDetector
from .tech_debt import TechDebtCrawler
from .gov_tenders import GovTenderCrawler
from .private_tenders import PrivateTenderCrawler
from ..db.repository import upsert_lead


CRAWLERS = {
    "linkedin": LinkedInCrawler,
    "clutch": ClutchCrawler,
    "upwork": UpworkCrawler,
    "wellfound": WellfoundCrawler,
    "goodfirms": GoodFirmsCrawler,
    "g2": G2Crawler,
    "indiehackers": IndieHackersCrawler,
    "producthunt": ProductHuntCrawler,
    "reddit": RedditCrawler,
    "twitter": TwitterCrawler,
    "hackernews": HackerNewsCrawler,
    "crunchbase": CrunchbaseCrawler,
    "github_projects": GitHubProjectsCrawler,
    "github": GitHubProjectsCrawler,
    "google_maps": GoogleMapsCrawler,
    "quora": QuoraCrawler,
    "ct_log": CTLogCrawler,
    "company_registry": CompanyRegistryCrawler,
    "yellowpages": YellowPagesCrawler,
    "accessibility_scanner": AccessibilityScannerCrawler,
    "broken_sites": BrokenSiteDetector,
    "tech_debt": TechDebtCrawler,
    "gov_tenders": GovTenderCrawler,
    "private_tenders": PrivateTenderCrawler,
}


async def _save_leads(leads):
    """Save platform leads to the database and return serializable results."""
    results = []
    for lead in leads:
        db_lead = await upsert_lead(
            domain=lead.domain,
            company_name=lead.company_name,
            source_platform=lead.source,
            source_url=lead.raw_url,
            description=lead.description,
            budget_estimate=lead.budget_estimate,
            signals=lead.signals,
            raw_data=lead.to_dict(),
        )
        results.append({**lead.to_dict(), "lead_id": db_lead["id"]})
    return results


def register(mcp):
    """Register all platform crawler tools with the MCP server."""

    @mcp.tool()
    async def crawl_platform(platform: str, query: str, max_results: int = 30) -> dict:
        """Crawl any supported platform for leads. Supported platforms:
        linkedin, clutch, upwork, wellfound, goodfirms, g2, indiehackers, producthunt,
        reddit, twitter, hackernews, crunchbase, github_projects, google_maps, quora.

        Args:
            platform: Platform name (linkedin, clutch, upwork, wellfound, goodfirms, g2, indiehackers, producthunt, reddit, twitter, hackernews, crunchbase, github_projects, google_maps, quora)
            query: Search query or keywords
            max_results: Maximum number of results to return
        """
        if platform not in CRAWLERS:
            return {"error": f"Unknown platform: {platform}. Supported: {list(CRAWLERS.keys())}"}

        crawler = CRAWLERS[platform]()
        leads = await crawler.safe_crawl({"keywords": [query], "max_results": max_results})
        results = await _save_leads(leads)
        return {"platform": platform, "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_linkedin_companies(
        industry: str, location: str = "", keywords: list[str] | None = None, max_results: int = 20
    ) -> dict:
        """Search LinkedIn for companies in a specific industry/location that may need software development.

        Args:
            industry: Industry to search (e.g., 'healthcare', 'fintech', 'ecommerce')
            location: Geographic location filter (e.g., 'San Francisco', 'New York')
            keywords: Additional search keywords
            max_results: Maximum results to return
        """
        crawler = LinkedInCrawler()
        leads = await crawler.safe_crawl({
            "action": "companies",
            "industry": industry,
            "location": location,
            "keywords": keywords or [industry],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "linkedin", "type": "companies", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_linkedin_jobs(
        keywords: list[str], location: str = "", max_results: int = 20
    ) -> dict:
        """Search LinkedIn job postings that indicate companies need software development help.

        Args:
            keywords: Job search keywords (e.g., ['software developer', 'web application', 'CTO'])
            location: Geographic location filter
            max_results: Maximum results to return
        """
        crawler = LinkedInCrawler()
        leads = await crawler.safe_crawl({
            "action": "jobs",
            "keywords": keywords,
            "location": location,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "linkedin", "type": "jobs", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_clutch(
        category: str = "web_development", location: str = "", min_budget: int = 0, max_results: int = 30
    ) -> dict:
        """Crawl Clutch.co directory for companies seeking development partners.
        Categories: web_development, mobile_development, custom_software, ecommerce, ui_ux, it_services, cloud, ai_ml.

        Args:
            category: Service category to search
            location: Geographic location filter
            min_budget: Minimum project budget filter
            max_results: Maximum results to return
        """
        crawler = ClutchCrawler()
        leads = await crawler.safe_crawl({
            "category": category,
            "location": location,
            "min_budget": min_budget,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "clutch", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_upwork(
        category: str = "software_development", skills: list[str] | None = None,
        min_budget: int = 5000, max_results: int = 30
    ) -> dict:
        """Crawl Upwork for large software development projects.
        Categories: web_development, mobile_development, software_development, ecommerce, ai_ml, blockchain, devops, data_science.

        Args:
            category: Project category
            skills: Required skills to filter by
            min_budget: Minimum project budget ($)
            max_results: Maximum results to return
        """
        crawler = UpworkCrawler()
        leads = await crawler.safe_crawl({
            "category": category,
            "skills": skills or [],
            "min_budget": min_budget,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "upwork", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_wellfound(
        industry: str = "software", stage: str = "", max_results: int = 20
    ) -> dict:
        """Crawl Wellfound (AngelList) for startups needing development work.

        Args:
            industry: Startup industry (e.g., 'software', 'fintech', 'healthtech')
            stage: Funding stage filter (e.g., 'seed', 'series-a')
            max_results: Maximum results to return
        """
        crawler = WellfoundCrawler()
        leads = await crawler.safe_crawl({
            "industry": industry,
            "stage": stage,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "wellfound", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_goodfirms_reviews(
        category: str = "software-development", location: str = "", max_results: int = 20
    ) -> dict:
        """Crawl GoodFirms for company reviews to find those with tech pain points.

        Args:
            category: Service category (e.g., 'software-development', 'web-development')
            location: Country/location filter
            max_results: Maximum results to return
        """
        crawler = GoodFirmsCrawler()
        leads = await crawler.safe_crawl({
            "category": category,
            "location": location,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "goodfirms", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_g2_reviews(product_category: str = "web-development", max_results: int = 20) -> dict:
        """Crawl G2 reviews to find companies with technology pain points.

        Args:
            product_category: G2 product category to search
            max_results: Maximum results to return
        """
        crawler = G2Crawler()
        leads = await crawler.safe_crawl({
            "product_category": product_category,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "g2", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_indiehackers(keywords: list[str] | None = None, max_results: int = 20) -> dict:
        """Crawl IndieHackers for founders/products needing development help.

        Args:
            keywords: Search keywords (default: 'looking for developer', 'need developer', 'technical cofounder')
            max_results: Maximum results to return
        """
        crawler = IndieHackersCrawler()
        leads = await crawler.safe_crawl({
            "keywords": keywords or ["looking for developer", "need developer", "technical cofounder"],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "indiehackers", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_producthunt(
        topics: list[str] | None = None, days_back: int = 30,
        min_upvotes: int = 50, max_results: int = 20
    ) -> dict:
        """Crawl ProductHunt for recently launched products that may need development support.

        Args:
            topics: ProductHunt topics to search (default: saas, developer-tools, productivity)
            days_back: How many days back to search
            min_upvotes: Minimum upvote threshold
            max_results: Maximum results to return
        """
        crawler = ProductHuntCrawler()
        leads = await crawler.safe_crawl({
            "topics": topics or ["saas", "developer-tools", "productivity"],
            "days_back": days_back,
            "min_upvotes": min_upvotes,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "producthunt", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_reddit(
        keywords: list[str] | None = None,
        subreddits: list[str] | None = None,
        action: str = "search",
        max_results: int = 20,
    ) -> dict:
        """Crawl Reddit for hiring posts and developer-need signals.
        Searches subreddits like r/forhire, r/startups, r/webdev, r/entrepreneur, r/smallbusiness.
        Signals detected: hiring, budget_mentioned, needs_developer, needs_website, app_broken.

        Args:
            keywords: Search keywords (default: 'looking for developer', '[Hiring]')
            subreddits: Subreddits to search (default: forhire, startups, webdev, entrepreneur, smallbusiness)
            action: 'search' for keyword search or 'subreddits' to crawl specific subreddits
            max_results: Maximum results to return
        """
        crawler = RedditCrawler()
        leads = await crawler.safe_crawl({
            "action": action,
            "keywords": keywords or ["looking for developer", "[Hiring]"],
            "subreddits": subreddits or ["forhire", "startups", "webdev", "entrepreneur", "smallbusiness"],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "reddit", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_twitter(
        keywords: list[str] | None = None, max_results: int = 20
    ) -> dict:
        """Search Twitter/X for intent signals — people looking for developers, announcing funding, or struggling with tech.
        Signals detected: hiring_signal, funding_announcement, tech_struggle, needs_developer.

        Args:
            keywords: Search keywords (default: 'looking for developer', 'need a website', 'our app is broken', 'need a CTO')
            max_results: Maximum results to return
        """
        crawler = TwitterCrawler()
        leads = await crawler.safe_crawl({
            "keywords": keywords or [
                "looking for developer", "need a website",
                "our app is broken", "need a CTO",
            ],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "twitter", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_hackernews(
        action: str = "search",
        keywords: list[str] | None = None,
        max_results: int = 20,
    ) -> dict:
        """Crawl Hacker News via the Algolia API for leads.
        Actions: 'search' (general), 'hiring' (Who is Hiring threads), 'show_hn' (new launches), 'ask_hn' (people needing help).
        Signals detected: show_hn_launch, hiring, ask_hn_needs_dev.

        Args:
            action: Type of search — 'search', 'hiring', 'show_hn', or 'ask_hn'
            keywords: Search keywords
            max_results: Maximum results to return
        """
        crawler = HackerNewsCrawler()
        leads = await crawler.safe_crawl({
            "action": action,
            "keywords": keywords or ["looking for developer"],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "hackernews", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_crunchbase(
        stage: str = "",
        industry: str = "",
        keywords: list[str] | None = None,
        max_results: int = 20,
    ) -> dict:
        """Search Crunchbase for recently funded startups that likely need development work.
        Signals detected: recently_funded, seed_stage, series_a, has_budget.

        Args:
            stage: Funding stage filter (e.g., 'seed', 'series a', 'series b')
            industry: Industry filter (e.g., 'fintech', 'healthtech', 'saas')
            keywords: Additional search keywords
            max_results: Maximum results to return
        """
        crawler = CrunchbaseCrawler()
        leads = await crawler.safe_crawl({
            "stage": stage,
            "industry": industry,
            "keywords": keywords or [],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "crunchbase", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_github_projects(
        action: str = "abandoned",
        min_stars: int = 100,
        language: str = "",
        keywords: list[str] | None = None,
        max_results: int = 20,
    ) -> dict:
        """Search GitHub for abandoned popular repos or projects needing help.
        Actions: 'abandoned' (popular repos with no recent commits), 'help_wanted' (repos with help-wanted issues).
        Signals detected: abandoned_popular_repo, needs_maintainer, help_wanted.

        Args:
            action: 'abandoned' to find unmaintained repos, 'help_wanted' for repos seeking contributors
            min_stars: Minimum star count for abandoned repo search
            language: Programming language filter (e.g., 'python', 'javascript')
            keywords: Additional search keywords for help_wanted action
            max_results: Maximum results to return
        """
        crawler = GitHubProjectsCrawler()
        leads = await crawler.safe_crawl({
            "action": action,
            "min_stars": min_stars,
            "language": language,
            "keywords": keywords or ["help wanted"],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "github_projects", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_google_maps(
        category: str = "restaurant",
        city: str = "",
        action: str = "no_website",
        max_results: int = 20,
    ) -> dict:
        """Find local businesses without websites or with weak web presence.
        Actions: 'no_website' (businesses relying on Yelp/Facebook), 'local' (general Google Maps search).
        Signals detected: no_website, needs_web_presence, local_business.

        Args:
            category: Business category (e.g., 'restaurant', 'plumber', 'dentist', 'salon', 'lawyer')
            city: City/location to search in
            action: 'no_website' to find businesses without sites, 'local' for general search
            max_results: Maximum results to return
        """
        crawler = GoogleMapsCrawler()
        leads = await crawler.safe_crawl({
            "action": action,
            "category": category,
            "city": city,
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "google_maps", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_quora(
        keywords: list[str] | None = None, max_results: int = 20
    ) -> dict:
        """Search Quora for people asking about hiring developers, building apps, or finding agencies.
        Signals detected: looking_for_agency, needs_app_built, tech_question.

        Args:
            keywords: Search keywords (default: 'how to find a developer', 'best software agency', 'need app built')
            max_results: Maximum results to return
        """
        crawler = QuoraCrawler()
        leads = await crawler.safe_crawl({
            "keywords": keywords or [
                "how to find a developer", "best software agency",
                "need app built", "cost to build an app",
            ],
            "max_results": max_results,
        })
        results = await _save_leads(leads)
        return {"platform": "quora", "total": len(results), "leads": results}

    @mcp.tool()
    async def crawl_reddit_live(
        subreddits: list[str] | None = None,
        action: str = "monitor_subreddits",
        keywords: list[str] | None = None,
        max_results: int = 30,
    ) -> dict:
        """Monitor Reddit subreddits for LIVE hiring/project posts using Reddit's JSON API.
        No API key required. Pulls directly from Reddit's public JSON endpoints.

        Actions:
        - 'monitor_subreddits': Watch new posts in subreddits for hiring signals
        - 'search': Search subreddits for specific keywords
        - 'hot': Get trending/hot posts from relevant subreddits

        Default subreddits: forhire, remotejs, jobbit, hiring, startups, entrepreneur, smallbusiness, SideProject.

        Signals detected: hiring, budget_mentioned, needs_developer, needs_website, startup_cofounder, app_broken.

        Args:
            subreddits: Subreddits to monitor (default: hiring + startup subreddits)
            action: 'monitor_subreddits', 'search', or 'hot'
            keywords: Search keywords (only used with action='search')
            max_results: Maximum results to return
        """
        crawler = RedditAPICrawler()
        query = {
            "action": action,
            "max_results": max_results,
        }
        if subreddits:
            query["subreddits"] = subreddits
        if keywords:
            query["keywords"] = keywords
        leads = await crawler.safe_crawl(query)
        results = await _save_leads(leads)
        return {"platform": "reddit_live", "action": action, "total": len(results), "leads": results}
