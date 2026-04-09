"""Check for modern web features and best practices."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..utils.http import fetch_url


async def analyze_features(html: str, url: str, headers: dict) -> dict:
    """Check for modern web features and common missing elements."""
    soup = BeautifulSoup(html, "lxml")
    findings = {}
    missing = []

    # 1. Mobile responsiveness (viewport meta)
    viewport = soup.find("meta", {"name": "viewport"})
    findings["viewport_meta"] = bool(viewport)
    if not viewport:
        missing.append({
            "feature": "Mobile viewport",
            "detail": "Missing <meta name='viewport'> — site likely not mobile-responsive",
            "impact": "high",
        })

    # 2. PWA manifest
    manifest_link = soup.find("link", {"rel": "manifest"})
    findings["pwa_manifest"] = bool(manifest_link)
    if not manifest_link:
        missing.append({
            "feature": "PWA Manifest",
            "detail": "No web app manifest — cannot be installed as PWA",
            "impact": "medium",
        })

    # 3. Service worker (check for registration script)
    sw_pattern = re.search(r"serviceWorker\.register|navigator\.serviceWorker", html)
    findings["service_worker"] = bool(sw_pattern)

    # 4. Favicon
    favicon = soup.find("link", {"rel": re.compile(r"icon", re.I)})
    findings["favicon"] = bool(favicon)
    if not favicon:
        missing.append({
            "feature": "Favicon",
            "detail": "No favicon defined — poor branding in browser tabs",
            "impact": "low",
        })

    # 5. Open Graph meta tags
    og_tags = soup.find_all("meta", property=re.compile(r"^og:"))
    og_present = {tag.get("property"): tag.get("content") for tag in og_tags}
    findings["open_graph"] = {
        "present": bool(og_tags),
        "tags": list(og_present.keys()),
    }
    required_og = ["og:title", "og:description", "og:image"]
    missing_og = [t for t in required_og if t not in og_present]
    if missing_og:
        missing.append({
            "feature": "Open Graph tags",
            "detail": f"Missing OG tags: {', '.join(missing_og)} — poor social media sharing",
            "impact": "medium",
        })

    # 6. Twitter Card meta
    twitter_tags = soup.find_all("meta", {"name": re.compile(r"^twitter:")})
    findings["twitter_cards"] = bool(twitter_tags)

    # 7. Structured data (JSON-LD)
    json_ld = soup.find_all("script", {"type": "application/ld+json"})
    findings["structured_data"] = {
        "json_ld": len(json_ld),
        "microdata": bool(soup.find(attrs={"itemtype": True})),
    }
    if not json_ld and not soup.find(attrs={"itemtype": True}):
        missing.append({
            "feature": "Structured data",
            "detail": "No JSON-LD or microdata — reduced search engine visibility",
            "impact": "high",
        })

    # 8. Sitemap (check via HTTP)
    sitemap_url = urljoin(url, "/sitemap.xml")
    try:
        resp = await fetch_url(sitemap_url, timeout=10.0)
        findings["sitemap"] = resp.status_code == 200
    except Exception:
        findings["sitemap"] = False
    if not findings["sitemap"]:
        missing.append({
            "feature": "Sitemap",
            "detail": "No sitemap.xml found — search engines may not crawl all pages",
            "impact": "medium",
        })

    # 9. Canonical URL
    canonical = soup.find("link", {"rel": "canonical"})
    findings["canonical_url"] = bool(canonical)
    if not canonical:
        missing.append({
            "feature": "Canonical URL",
            "detail": "Missing canonical link — risk of duplicate content in search results",
            "impact": "medium",
        })

    # 10. Meta description
    meta_desc = soup.find("meta", {"name": "description"})
    findings["meta_description"] = bool(meta_desc)
    if not meta_desc:
        missing.append({
            "feature": "Meta description",
            "detail": "No meta description — poor search engine snippet display",
            "impact": "high",
        })

    # 11. HTTPS redirection (if we're already on HTTPS, check if HTTP redirects)
    findings["uses_https"] = url.startswith("https://")

    # 12. Responsive images (srcset)
    images = soup.find_all("img")
    with_srcset = [img for img in images if img.get("srcset")]
    findings["responsive_images"] = {
        "total": len(images),
        "with_srcset": len(with_srcset),
    }

    # 13. Font loading optimization
    preload_fonts = soup.find_all("link", {"rel": "preload", "as": "font"})
    font_display = bool(re.search(r"font-display\s*:\s*swap", html))
    findings["font_optimization"] = {
        "preloaded_fonts": len(preload_fonts),
        "font_display_swap": font_display,
    }

    return {
        "findings": findings,
        "missing_features": missing,
        "missing_count": len(missing),
        "high_impact_missing": len([m for m in missing if m["impact"] == "high"]),
    }
