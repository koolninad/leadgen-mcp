"""Detect technology stacks from HTML, headers, and scripts."""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


# Load tech signatures
_SIGNATURES_PATH = Path(__file__).parent.parent.parent.parent / "data" / "tech_signatures.json"
_signatures: dict | None = None


def _load_signatures() -> dict:
    global _signatures
    if _signatures is None:
        try:
            data = json.loads(_SIGNATURES_PATH.read_text(encoding="utf-8"))
            # Validate it has actual tech categories (not just metadata)
            if "cms" in data or "framework" in data:
                _signatures = data
            else:
                _signatures = _get_default_signatures()
        except (FileNotFoundError, json.JSONDecodeError):
            _signatures = _get_default_signatures()
    return _signatures


def _get_default_signatures() -> dict:
    return {
        "cms": {
            "WordPress": {
                "html": [r"wp-content", r"wp-includes", r'<meta name="generator" content="WordPress'],
                "headers": {"x-powered-by": "WordPress"},
                "scripts": [r"wp-content/themes", r"wp-content/plugins"],
            },
            "Drupal": {
                "html": [r"Drupal.settings", r'<meta name="generator" content="Drupal'],
                "headers": {"x-generator": "Drupal"},
                "scripts": [r"drupal\.js", r"/sites/default/files"],
            },
            "Joomla": {
                "html": [r"/media/jui/", r'<meta name="generator" content="Joomla'],
                "scripts": [r"media/system/js"],
            },
            "Shopify": {
                "html": [r"cdn\.shopify\.com", r"Shopify\.theme"],
                "headers": {"x-shopify-stage": ""},
                "scripts": [r"cdn\.shopify\.com"],
            },
            "Wix": {
                "html": [r"wixsite\.com", r"static\.wixstatic\.com", r"X-Wix-"],
                "scripts": [r"static\.parastorage\.com"],
            },
            "Squarespace": {
                "html": [r"squarespace\.com", r"static\.squarespace\.com"],
                "scripts": [r"static\.squarespace\.com"],
            },
            "Ghost": {
                "html": [r'<meta name="generator" content="Ghost'],
                "headers": {"x-powered-by": "Ghost"},
            },
            "Webflow": {
                "html": [r"webflow\.com", r'class="w-'],
                "scripts": [r"assets\.website-files\.com"],
            },
        },
        "framework": {
            "React": {
                "html": [r"__next", r"_react", r"react-root", r'data-reactroot'],
                "scripts": [r"react\.production\.min\.js", r"react-dom"],
            },
            "Next.js": {
                "html": [r"__next", r"_next/static", r"__NEXT_DATA__"],
                "headers": {"x-powered-by": "Next.js"},
            },
            "Vue.js": {
                "html": [r"__vue", r"v-cloak", r"data-v-"],
                "scripts": [r"vue\.min\.js", r"vue\.runtime"],
            },
            "Nuxt.js": {
                "html": [r"__nuxt", r"_nuxt/"],
                "headers": {"x-powered-by": "Nuxt"},
            },
            "Angular": {
                "html": [r"ng-version", r"ng-app", r"angular\.js"],
                "scripts": [r"angular\.min\.js", r"zone\.js"],
            },
            "Svelte": {
                "html": [r"svelte-", r"__svelte"],
                "scripts": [r"svelte"],
            },
            "Django": {
                "html": [r"csrfmiddlewaretoken", r"__django__"],
                "headers": {"x-frame-options": ""},
            },
            "Ruby on Rails": {
                "html": [r"csrf-token", r"authenticity_token"],
                "headers": {"x-powered-by": "Phusion Passenger"},
            },
            "Laravel": {
                "html": [r"laravel_session", r"csrf-token"],
                "headers": {"x-powered-by": "Laravel"},
            },
            "ASP.NET": {
                "html": [r"__VIEWSTATE", r"__EVENTVALIDATION", r"aspnetForm"],
                "headers": {"x-powered-by": "ASP.NET", "x-aspnet-version": ""},
            },
            "Spring Boot": {
                "headers": {"x-application-context": ""},
            },
            "Express.js": {
                "headers": {"x-powered-by": "Express"},
            },
            "Flask": {
                "headers": {"server": "Werkzeug"},
            },
        },
        "server": {
            "Nginx": {"headers": {"server": "nginx"}},
            "Apache": {"headers": {"server": "Apache"}},
            "Cloudflare": {"headers": {"server": "cloudflare", "cf-ray": ""}},
            "IIS": {"headers": {"server": "Microsoft-IIS"}},
            "LiteSpeed": {"headers": {"server": "LiteSpeed"}},
        },
        "analytics": {
            "Google Analytics": {
                "scripts": [r"google-analytics\.com", r"googletagmanager\.com", r"gtag/js"],
            },
            "Hotjar": {"scripts": [r"hotjar\.com", r"static\.hotjar\.com"]},
            "Mixpanel": {"scripts": [r"mixpanel\.com"]},
            "Segment": {"scripts": [r"segment\.com", r"cdn\.segment\.io"]},
        },
        "cdn": {
            "Cloudflare CDN": {"headers": {"cf-cache-status": ""}},
            "AWS CloudFront": {"headers": {"x-amz-cf-id": "", "via": "cloudfront"}},
            "Fastly": {"headers": {"x-served-by": "", "via": "varnish"}},
            "Vercel": {"headers": {"x-vercel-id": "", "server": "Vercel"}},
            "Netlify": {"headers": {"server": "Netlify", "x-nf-request-id": ""}},
        },
        "ecommerce": {
            "WooCommerce": {
                "html": [r"woocommerce", r"wc-cart"],
                "scripts": [r"woocommerce"],
            },
            "Magento": {
                "html": [r"Magento", r"mage/cookies"],
                "scripts": [r"mage/"],
            },
            "BigCommerce": {
                "html": [r"bigcommerce\.com"],
                "scripts": [r"bigcommerce\.com"],
            },
            "Stripe": {
                "scripts": [r"js\.stripe\.com", r"stripe\.js"],
            },
        },
    }


def detect_tech_stack(html: str, headers: dict) -> dict:
    """Detect technologies from HTML content and HTTP headers."""
    sigs = _load_signatures()
    soup = BeautifulSoup(html, "lxml")
    detected: dict[str, list[dict]] = {}

    # Extract all script src values
    script_srcs = []
    for tag in soup.find_all("script", src=True):
        script_srcs.append(tag["src"])
    scripts_text = " ".join(script_srcs)

    # Normalize headers to lowercase
    norm_headers = {k.lower(): v.lower() for k, v in headers.items()}

    for category, techs in sigs.items():
        cat_detections = []
        for tech_name, rules in techs.items():
            confidence = 0
            signals = []

            # Check HTML patterns
            for pattern in rules.get("html", []):
                if re.search(pattern, html, re.IGNORECASE):
                    confidence += 40
                    signals.append(f"html:{pattern}")

            # Check header patterns
            for header_key, header_val in rules.get("headers", {}).items():
                if header_key in norm_headers:
                    if not header_val or header_val.lower() in norm_headers[header_key]:
                        confidence += 50
                        signals.append(f"header:{header_key}")

            # Check script patterns
            for pattern in rules.get("scripts", []):
                if re.search(pattern, scripts_text, re.IGNORECASE):
                    confidence += 30
                    signals.append(f"script:{pattern}")

            if confidence > 0:
                cat_detections.append({
                    "name": tech_name,
                    "confidence": min(confidence, 100),
                    "signals": signals,
                })

        if cat_detections:
            detected[category] = sorted(
                cat_detections, key=lambda x: x["confidence"], reverse=True
            )

    # Detect outdated patterns
    outdated = _check_outdated(html, norm_headers)

    return {
        "technologies": detected,
        "outdated": outdated,
        "total_detected": sum(len(v) for v in detected.values()),
    }


def _check_outdated(html: str, headers: dict) -> list[dict]:
    """Check for signs of outdated technology."""
    outdated = []

    patterns = [
        (r"jquery[/-]1\.", "jQuery 1.x", "jQuery 1.x is severely outdated and has known security vulnerabilities"),
        (r"jquery[/-]2\.", "jQuery 2.x", "jQuery 2.x is outdated — consider jQuery 3.x+ or modern alternatives"),
        (r"bootstrap[/-][23]\.", "Bootstrap 2/3", "Bootstrap 2-3 is outdated — current version is 5.x"),
        (r"angular\.js", "AngularJS 1.x", "AngularJS 1.x reached end-of-life in January 2022"),
        (r"font-awesome[/-][34]\.", "Font Awesome 3/4", "Font Awesome 3-4 is outdated"),
        (r"php/5\.", "PHP 5.x", "PHP 5.x is end-of-life and has critical security vulnerabilities"),
        (r"php/7\.[0-3]", "PHP 7.0-7.3", "PHP 7.0-7.3 is end-of-life"),
    ]

    for pattern, name, reason in patterns:
        if re.search(pattern, html, re.IGNORECASE):
            outdated.append({"technology": name, "reason": reason, "severity": "warning"})

    # Check server header for old versions
    server = headers.get("server", "")
    if re.search(r"apache/2\.[02]", server):
        outdated.append({"technology": "Apache 2.0/2.2", "reason": "Very old Apache version", "severity": "critical"})
    if re.search(r"nginx/1\.[0-9]\.", server):
        outdated.append({"technology": f"Nginx ({server})", "reason": "Outdated Nginx version", "severity": "warning"})

    return outdated
