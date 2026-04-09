"""MCP tool definitions for the Domain Intelligence module."""

import asyncio

from .whois_scanner import lookup_whois, scan_new_domains_feed
from .dns_checker import check_dns
from .ssl_monitor import check_ssl
from .http_monitor import check_http_health, find_broken_links
from ..db.repository import upsert_lead, save_scan_result
from ..utils.validators import normalize_url


def register(mcp):
    """Register all domain intelligence tools with the MCP server."""

    @mcp.tool()
    async def check_domain_whois(domain: str) -> dict:
        """WHOIS lookup with domain age and expiry analysis. Detects newly registered
        domains (< 90 days = new businesses) and expiring/expired domains.

        Args:
            domain: The domain name to look up (e.g., 'example.com')
        """
        result = await lookup_whois(domain)

        # Save to database if there's a signal
        if result.get("signal"):
            lead = await upsert_lead(
                domain=domain,
                source_platform="domain_intel_whois",
                description=result.get("signal_detail", ""),
                signals=[result["signal"]],
                raw_data=result,
            )
            if lead:
                await save_scan_result(
                    lead["id"], "whois", result,
                    severity="warning" if result.get("signal") in ("newly_registered", "expiring_soon") else "critical",
                )
                result["lead_id"] = lead["id"]

        return result

    @mcp.tool()
    async def check_domain_dns(domain: str) -> dict:
        """Full DNS health check: MX records, SPF, DMARC, DKIM, A/AAAA, NS records.
        Missing MX = no email. Missing SPF/DMARC = deliverability and security issues.

        Args:
            domain: The domain name to check (e.g., 'example.com')
        """
        # Run synchronous DNS checks in a thread to avoid blocking the event loop
        result = await asyncio.to_thread(check_dns, domain)

        # Save to database if there are issues
        if result.get("issues"):
            signals = [i["check"] for i in result["issues"]]
            lead = await upsert_lead(
                domain=domain,
                source_platform="domain_intel_dns",
                description=f"DNS health check found {result['issue_count']} issues",
                signals=signals,
                raw_data=result,
            )
            if lead:
                await save_scan_result(
                    lead["id"], "dns_health", result,
                    severity=result.get("severity", "info"),
                )
                result["lead_id"] = lead["id"]

        return result

    @mcp.tool()
    async def check_ssl_certificate(domain: str) -> dict:
        """SSL certificate analysis: expiry warning, issuer (Let's Encrypt vs commercial),
        chain validity, protocol version, cipher strength. Certificates expiring in < 30 days
        are flagged as urgent leads.

        Args:
            domain: The domain name to check (e.g., 'example.com')
        """
        result = await asyncio.to_thread(check_ssl, domain)

        # Save to database if urgent
        if result.get("is_urgent_lead") or result.get("severity") in ("critical", "warning"):
            signals = ["ssl_" + i["issue"].lower().replace(" ", "_")[:40] for i in result.get("issues", [])]
            lead = await upsert_lead(
                domain=domain,
                source_platform="domain_intel_ssl",
                description=f"SSL issues: {', '.join(i['issue'] for i in result.get('issues', [])[:3])}",
                signals=signals,
                raw_data=result,
            )
            if lead:
                await save_scan_result(
                    lead["id"], "ssl_certificate", result,
                    severity=result.get("severity", "info"),
                )
                result["lead_id"] = lead["id"]

        return result

    @mcp.tool()
    async def check_http_health_tool(url: str) -> dict:
        """Check HTTP health: status codes (500/503 = site down), redirect chains,
        response time (> 5s = performance crisis), missing favicon/robots.txt.

        Args:
            url: The full URL to check (e.g., 'https://example.com')
        """
        url = normalize_url(url)
        result = await check_http_health(url)

        # Save to database if there are issues
        if result.get("issues"):
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            signals = [i["issue"][:50] for i in result["issues"]]
            lead = await upsert_lead(
                domain=domain,
                source_platform="domain_intel_http",
                description=f"HTTP health check found {result.get('issue_count', 0)} issues",
                signals=signals,
                raw_data=result,
            )
            if lead:
                await save_scan_result(
                    lead["id"], "http_health", result,
                    severity=result.get("severity", "info"),
                )
                result["lead_id"] = lead["id"]

        return result

    @mcp.tool()
    async def find_broken_links_tool(url: str, max_links: int = 50) -> dict:
        """Spider a page and find broken links (404s). Checks up to max_links URLs
        found on the page. Many broken links = neglected website needing help.

        Args:
            url: The page URL to spider for links
            max_links: Maximum number of links to check (default: 50)
        """
        url = normalize_url(url)
        result = await find_broken_links(url, max_links=max_links)

        if result.get("broken_count", 0) > 0:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            lead = await upsert_lead(
                domain=domain,
                source_platform="domain_intel_links",
                description=f"Found {result['broken_count']} broken links on {url}",
                signals=["broken_links"],
                raw_data=result,
            )
            if lead:
                await save_scan_result(
                    lead["id"], "broken_links", result,
                    severity=result.get("severity", "info"),
                )
                result["lead_id"] = lead["id"]

        return result

    @mcp.tool()
    async def scan_domain_full(domain: str) -> dict:
        """Run ALL domain intelligence checks at once: WHOIS, DNS, SSL, HTTP health,
        and broken links. Provides a comprehensive domain audit.

        Args:
            domain: The domain name to fully scan (e.g., 'example.com')
        """
        url = f"https://{domain}"

        # Run all checks concurrently
        whois_task = lookup_whois(domain)
        dns_task = asyncio.to_thread(check_dns, domain)
        ssl_task = asyncio.to_thread(check_ssl, domain)
        http_task = check_http_health(url)
        links_task = find_broken_links(url, max_links=30)

        whois_result, dns_result, ssl_result, http_result, links_result = (
            await asyncio.gather(
                whois_task, dns_task, ssl_task, http_task, links_task,
                return_exceptions=True,
            )
        )

        # Handle any exceptions gracefully
        def _safe(val, name):
            if isinstance(val, Exception):
                return {"error": f"{name} check failed: {val}"}
            return val

        combined = {
            "domain": domain,
            "whois": _safe(whois_result, "WHOIS"),
            "dns": _safe(dns_result, "DNS"),
            "ssl": _safe(ssl_result, "SSL"),
            "http": _safe(http_result, "HTTP"),
            "broken_links": _safe(links_result, "Broken Links"),
        }

        # Aggregate all issues
        all_issues = []
        for section in ("whois", "dns", "ssl", "http", "broken_links"):
            data = combined[section]
            if isinstance(data, dict) and "issues" in data:
                for issue in data["issues"]:
                    issue["source"] = section
                    all_issues.append(issue)

        severities = [i["severity"] for i in all_issues]
        if "critical" in severities:
            overall = "critical"
        elif "warning" in severities:
            overall = "warning"
        else:
            overall = "good"

        combined["summary"] = {
            "total_issues": len(all_issues),
            "critical_issues": severities.count("critical"),
            "warnings": severities.count("warning"),
            "info": severities.count("info"),
            "overall_severity": overall,
            "all_issues": all_issues,
        }

        # Save combined result to database
        signals = list({i.get("issue", "")[:50] for i in all_issues[:10]})
        lead = await upsert_lead(
            domain=domain,
            source_platform="domain_intel_full",
            description=f"Full domain scan: {len(all_issues)} issues ({overall})",
            signals=signals,
            raw_data=combined,
        )
        if lead:
            await save_scan_result(
                lead["id"], "domain_full_scan", combined,
                severity=overall,
            )
            combined["lead_id"] = lead["id"]

        return combined

    @mcp.tool()
    async def scan_new_domains(tld: str = "com", days_back: int = 7) -> dict:
        """Find newly registered domains from public NRD feeds. These represent
        new businesses that likely need websites, branding, and digital services.

        Args:
            tld: Top-level domain to scan (e.g., 'com', 'io', 'co')
            days_back: How many days back to search (default: 7, max: 30)
        """
        days_back = min(days_back, 30)
        domains = await scan_new_domains_feed(tld=tld, days_back=days_back)

        return {
            "tld": tld,
            "days_back": days_back,
            "domains_found": len(domains),
            "domains": domains[:200],  # Limit response size
            "note": "Use check_domain_whois or scan_domain_full on promising domains for deeper analysis",
        }
