"""Website performance analysis."""

import re

from bs4 import BeautifulSoup

from .crawler import CrawlResult


def analyze_performance(crawl_result: CrawlResult) -> dict:
    """Analyze website performance from crawl data."""
    html = crawl_result.html
    soup = BeautifulSoup(html, "lxml")
    issues = []
    metrics = {}

    # Page load time (from our crawl)
    load_time = crawl_result.load_time_ms
    metrics["load_time_ms"] = load_time
    if load_time > 5000:
        issues.append({
            "issue": "Slow page load",
            "detail": f"Page took {load_time:.0f}ms to load (target: <3000ms)",
            "severity": "critical",
        })
    elif load_time > 3000:
        issues.append({
            "issue": "Moderate page load time",
            "detail": f"Page took {load_time:.0f}ms to load (target: <3000ms)",
            "severity": "warning",
        })

    # Page size estimation
    page_size = len(html.encode("utf-8"))
    metrics["html_size_kb"] = round(page_size / 1024, 1)
    if page_size > 500_000:
        issues.append({
            "issue": "Large HTML document",
            "detail": f"HTML is {page_size/1024:.0f}KB (target: <500KB)",
            "severity": "warning",
        })

    # Image analysis
    images = soup.find_all("img")
    metrics["total_images"] = len(images)
    unoptimized = []
    for img in images:
        src = img.get("src", "")
        # Check for non-optimized formats
        if re.search(r"\.(bmp|tiff?)$", src, re.IGNORECASE):
            unoptimized.append(src)
        # Check for missing lazy loading
        if not img.get("loading") and not img.get("data-lazy"):
            pass  # Count below

    no_lazy = [img for img in images if not img.get("loading") and not img.get("data-lazy") and not img.get("data-src")]
    metrics["images_without_lazy_load"] = len(no_lazy)
    if len(no_lazy) > 5:
        issues.append({
            "issue": "Images missing lazy loading",
            "detail": f"{len(no_lazy)} images lack lazy loading attributes",
            "severity": "warning",
        })

    if unoptimized:
        issues.append({
            "issue": "Unoptimized image formats",
            "detail": f"{len(unoptimized)} images use BMP/TIFF format — use WebP/AVIF instead",
            "severity": "warning",
        })

    # Script analysis
    scripts = soup.find_all("script", src=True)
    metrics["external_scripts"] = len(scripts)
    render_blocking = [s for s in scripts if not s.get("async") and not s.get("defer")]
    metrics["render_blocking_scripts"] = len(render_blocking)
    if len(render_blocking) > 3:
        issues.append({
            "issue": "Render-blocking scripts",
            "detail": f"{len(render_blocking)} scripts lack async/defer attributes",
            "severity": "warning",
        })

    # CSS analysis
    stylesheets = soup.find_all("link", rel="stylesheet")
    metrics["external_stylesheets"] = len(stylesheets)
    if len(stylesheets) > 5:
        issues.append({
            "issue": "Too many CSS files",
            "detail": f"{len(stylesheets)} separate CSS files — consider bundling",
            "severity": "info",
        })

    # Inline styles (indicator of poor optimization)
    inline_styles = soup.find_all(style=True)
    metrics["inline_styles"] = len(inline_styles)

    # Check for minification hints
    if re.search(r"\n\s{4,}.*\n\s{4,}", html[:5000]):
        issues.append({
            "issue": "HTML may not be minified",
            "detail": "HTML contains significant whitespace — consider minification",
            "severity": "info",
        })

    # Compression check from headers
    content_encoding = crawl_result.headers.get("content-encoding", "")
    metrics["compression"] = content_encoding or "none"
    if not content_encoding:
        issues.append({
            "issue": "No compression detected",
            "detail": "Response lacks Content-Encoding header (gzip/brotli)",
            "severity": "warning",
        })

    # Caching headers
    cache_control = crawl_result.headers.get("cache-control", "")
    metrics["cache_control"] = cache_control or "none"
    if not cache_control or "no-cache" in cache_control:
        issues.append({
            "issue": "Poor caching configuration",
            "detail": "Missing or restrictive Cache-Control headers",
            "severity": "info",
        })

    # Determine overall severity
    severities = [i["severity"] for i in issues]
    if "critical" in severities:
        overall = "critical"
    elif "warning" in severities:
        overall = "warning"
    else:
        overall = "good"

    return {
        "metrics": metrics,
        "issues": issues,
        "issue_count": len(issues),
        "severity": overall,
    }
