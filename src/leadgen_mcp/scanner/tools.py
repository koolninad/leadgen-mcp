"""MCP tool definitions for the Website Scanner module."""

from .crawler import crawl_url, crawl_batch
from .tech_detector import detect_tech_stack
from .performance import analyze_performance
from .security import analyze_security
from .accessibility import analyze_accessibility
from .features import analyze_features
from ..utils.validators import normalize_url


def register(mcp):
    """Register all scanner tools with the MCP server."""

    @mcp.tool()
    async def scan_website(url: str, full: bool = True) -> dict:
        """Perform a comprehensive website scan including tech stack, performance, security,
        accessibility, and feature analysis. Set full=False for quick tech-only scan.

        Args:
            url: The website URL to scan
            full: Whether to run all scan types (True) or just tech detection (False)
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}

        scan = {
            "url": url,
            "status_code": result.status_code,
            "load_time_ms": result.load_time_ms,
            "tech_stack": detect_tech_stack(result.html, result.headers),
        }

        if full:
            scan["performance"] = analyze_performance(result)
            scan["security"] = analyze_security(result)
            scan["accessibility"] = analyze_accessibility(result.html)
            scan["features"] = await analyze_features(result.html, url, result.headers)

            # Calculate overall opportunity score
            issues = []
            for section in ["performance", "security", "accessibility", "features"]:
                data = scan[section]
                if "issues" in data:
                    issues.extend(data["issues"])
                if "missing_features" in data:
                    issues.extend(data["missing_features"])

            critical = len([i for i in issues if i.get("severity") == "critical" or i.get("impact") == "high"])
            warnings = len([i for i in issues if i.get("severity") == "warning" or i.get("impact") == "medium"])

            scan["opportunity_summary"] = {
                "total_issues": len(issues),
                "critical_issues": critical,
                "warnings": warnings,
                "opportunity_level": "high" if critical >= 3 else "medium" if critical >= 1 or warnings >= 3 else "low",
            }

        return scan

    @mcp.tool()
    async def scan_batch_websites(urls: list[str], concurrency: int = 10) -> dict:
        """Scan multiple websites in parallel for tech stacks and issues.

        Args:
            urls: List of website URLs to scan
            concurrency: Maximum number of concurrent scans (default: 10)
        """
        normalized = [normalize_url(u) for u in urls]
        results = await crawl_batch(normalized, concurrency=concurrency)

        scans = []
        for cr in results:
            if cr.success:
                tech = detect_tech_stack(cr.html, cr.headers)
                perf = analyze_performance(cr)
                scans.append({
                    "url": cr.url,
                    "status": "success",
                    "load_time_ms": cr.load_time_ms,
                    "tech_stack": tech,
                    "performance_severity": perf["severity"],
                    "issue_count": perf["issue_count"],
                })
            else:
                scans.append({
                    "url": cr.url,
                    "status": "failed",
                    "error": cr.error,
                })

        return {
            "total": len(urls),
            "successful": len([s for s in scans if s["status"] == "success"]),
            "failed": len([s for s in scans if s["status"] == "failed"]),
            "results": scans,
        }

    @mcp.tool()
    async def detect_website_tech(url: str) -> dict:
        """Detect the technology stack of a website (CMS, frameworks, server, analytics, CDN).

        Args:
            url: The website URL to analyze
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}
        return detect_tech_stack(result.html, result.headers)

    @mcp.tool()
    async def check_performance(url: str) -> dict:
        """Analyze website performance: load time, page size, render-blocking resources, images, compression.

        Args:
            url: The website URL to analyze
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}
        return analyze_performance(result)

    @mcp.tool()
    async def check_security(url: str) -> dict:
        """Check website security: SSL, security headers, mixed content, cookie flags, info disclosure.

        Args:
            url: The website URL to check
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}
        return analyze_security(result)

    @mcp.tool()
    async def check_accessibility(url: str) -> dict:
        """Analyze website accessibility (WCAG compliance): alt text, labels, headings, ARIA, keyboard navigation.

        Args:
            url: The website URL to analyze
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}
        return analyze_accessibility(result.html)

    @mcp.tool()
    async def check_missing_features(url: str) -> dict:
        """Check for missing modern web features: mobile viewport, PWA, Open Graph, structured data, sitemap, etc.

        Args:
            url: The website URL to check
        """
        url = normalize_url(url)
        result = await crawl_url(url)
        if not result.success:
            return {"error": result.error, "url": url}
        return await analyze_features(result.html, url, result.headers)
