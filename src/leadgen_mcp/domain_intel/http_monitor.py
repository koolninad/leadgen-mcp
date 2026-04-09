"""HTTP health monitor — status codes, redirects, response time, broken links."""

import time
import asyncio
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from ..utils.http import create_client, random_ua


async def check_http_health(url: str) -> dict:
    """Check HTTP health of a URL: status, redirects, response time, missing resources.

    Returns a dict with status, redirect chain, timing, and issues with severity.
    """
    result: dict = {
        "url": url,
        "issues": [],
    }

    # Use a non-following client to capture the redirect chain manually
    try:
        redirect_chain = []
        final_url = url
        status_code = None
        response_time_ms = None
        headers = {}

        async with create_client(timeout=30.0, follow_redirects=False) as client:
            current_url = url
            start = time.monotonic()
            for _ in range(10):  # max 10 redirects
                resp = await client.get(current_url, headers={"User-Agent": random_ua()})
                elapsed = (time.monotonic() - start) * 1000
                status_code = resp.status_code
                headers = dict(resp.headers)

                if 300 <= status_code < 400:
                    location = resp.headers.get("location", "")
                    if not location:
                        break
                    # Resolve relative redirects
                    if not location.startswith("http"):
                        location = urljoin(current_url, location)
                    redirect_chain.append({
                        "from": current_url,
                        "to": location,
                        "status": status_code,
                    })
                    current_url = location
                else:
                    break

            final_url = current_url
            response_time_ms = round(elapsed, 1)

        result["status_code"] = status_code
        result["final_url"] = final_url
        result["response_time_ms"] = response_time_ms
        result["redirect_chain"] = redirect_chain
        result["redirect_count"] = len(redirect_chain)
        result["headers"] = {
            "server": headers.get("server"),
            "content-type": headers.get("content-type"),
            "x-powered-by": headers.get("x-powered-by"),
        }

    except httpx.ConnectTimeout:
        result["error"] = "Connection timed out"
        result["issues"].append({
            "issue": "Connection timeout",
            "detail": f"{url} did not respond within 30 seconds",
            "severity": "critical",
        })
        result["severity"] = "critical"
        return result
    except httpx.RequestError as e:
        result["error"] = str(e)
        result["issues"].append({
            "issue": "Connection failed",
            "detail": str(e),
            "severity": "critical",
        })
        result["severity"] = "critical"
        return result

    # --- Status code analysis ---
    if status_code and status_code >= 500:
        result["issues"].append({
            "issue": f"Server error: HTTP {status_code}",
            "detail": "Site is returning server errors — may be down or misconfigured. Urgent lead.",
            "severity": "critical",
        })
    elif status_code == 403:
        result["issues"].append({
            "issue": "Access forbidden (403)",
            "detail": "Server is blocking requests — possible misconfiguration",
            "severity": "warning",
        })
    elif status_code == 404:
        result["issues"].append({
            "issue": "Page not found (404)",
            "detail": "The requested URL returns a 404 error",
            "severity": "warning",
        })

    # --- Redirect analysis ---
    if len(redirect_chain) > 3:
        result["issues"].append({
            "issue": f"Excessive redirects ({len(redirect_chain)})",
            "detail": "Too many redirects indicate misconfiguration — hurts SEO and performance",
            "severity": "warning",
        })

    # --- Response time analysis ---
    if response_time_ms and response_time_ms > 5000:
        result["issues"].append({
            "issue": f"Very slow response ({response_time_ms:.0f}ms)",
            "detail": "Response time over 5 seconds indicates a performance crisis",
            "severity": "critical",
        })
    elif response_time_ms and response_time_ms > 2000:
        result["issues"].append({
            "issue": f"Slow response ({response_time_ms:.0f}ms)",
            "detail": "Response time over 2 seconds hurts user experience and SEO",
            "severity": "warning",
        })

    # --- Check for missing common resources ---
    parsed = urlparse(final_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    missing_resources = await _check_common_resources(base)
    result["missing_resources"] = missing_resources
    for resource in missing_resources:
        result["issues"].append({
            "issue": f"Missing {resource['name']}",
            "detail": resource["detail"],
            "severity": resource["severity"],
        })

    # --- Overall severity ---
    severities = [i["severity"] for i in result["issues"]]
    if "critical" in severities:
        result["severity"] = "critical"
    elif "warning" in severities:
        result["severity"] = "warning"
    else:
        result["severity"] = "good"

    result["issue_count"] = len(result["issues"])

    return result


async def _check_common_resources(base_url: str) -> list[dict]:
    """Check for missing favicon, robots.txt, sitemap.xml."""
    missing = []
    checks = [
        ("favicon.ico", "/favicon.ico", "Missing favicon — looks unprofessional in browser tabs", "info"),
        ("robots.txt", "/robots.txt", "Missing robots.txt — search engines have no crawl directives", "warning"),
        ("sitemap.xml", "/sitemap.xml", "Missing sitemap.xml — hurts search engine indexing", "info"),
    ]

    async with create_client(timeout=10.0) as client:
        for name, path, detail, severity in checks:
            try:
                resp = await client.get(f"{base_url}{path}")
                if resp.status_code != 200:
                    missing.append({"name": name, "detail": detail, "severity": severity})
            except httpx.RequestError:
                missing.append({"name": name, "detail": detail, "severity": severity})

    return missing


async def find_broken_links(url: str, max_links: int = 50) -> dict:
    """Spider a page, extract all links, and check each for broken (404/5xx) responses.

    Returns a summary of all links checked with their status.
    """
    result: dict = {
        "url": url,
        "links_checked": 0,
        "broken_links": [],
        "working_links": 0,
        "error_links": [],
    }

    # Fetch the page
    try:
        async with create_client(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.RequestError as e:
        return {"url": url, "error": f"Failed to fetch page: {e}"}
    except httpx.HTTPStatusError as e:
        return {"url": url, "error": f"Page returned HTTP {e.response.status_code}"}

    # Parse links
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(url)
    base_url = f"{parsed_base.scheme}://{parsed_base.netloc}"

    links: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()

        # Skip anchors, javascript, mailto, tel
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Resolve relative URLs
        if not href.startswith("http"):
            href = urljoin(url, href)

        # Deduplicate
        if href not in seen:
            seen.add(href)
            links.append(href)

        if len(links) >= max_links:
            break

    # Check each link concurrently
    semaphore = asyncio.Semaphore(10)

    async def _check_link(link_url: str) -> dict:
        async with semaphore:
            try:
                async with create_client(timeout=15.0) as client:
                    resp = await client.head(link_url)
                    # Some servers don't support HEAD; fall back to GET
                    if resp.status_code == 405:
                        resp = await client.get(link_url)
                    return {"url": link_url, "status": resp.status_code}
            except httpx.RequestError as e:
                return {"url": link_url, "status": None, "error": str(e)}

    tasks = [_check_link(link) for link in links]
    link_results = await asyncio.gather(*tasks)

    for lr in link_results:
        result["links_checked"] += 1
        status = lr.get("status")
        if status and 200 <= status < 400:
            result["working_links"] += 1
        elif status and status == 404:
            result["broken_links"].append(lr)
        elif status and status >= 400:
            result["error_links"].append(lr)
        elif lr.get("error"):
            result["error_links"].append(lr)

    result["broken_count"] = len(result["broken_links"])
    result["error_count"] = len(result["error_links"])

    if result["broken_count"] > 5:
        result["severity"] = "critical"
    elif result["broken_count"] > 0 or result["error_count"] > 3:
        result["severity"] = "warning"
    else:
        result["severity"] = "good"

    return result
