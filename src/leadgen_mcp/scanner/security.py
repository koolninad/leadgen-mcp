"""Website security analysis."""

import re
import ssl
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .crawler import CrawlResult


def analyze_security(crawl_result: CrawlResult) -> dict:
    """Analyze website security from crawl data and SSL certificate."""
    issues = []
    findings = {}

    url = crawl_result.url
    parsed = urlparse(url)
    headers = {k.lower(): v for k, v in crawl_result.headers.items()}

    # --- SSL Certificate Check ---
    ssl_info = _check_ssl(parsed.netloc)
    findings["ssl"] = ssl_info
    if ssl_info.get("error"):
        issues.append({
            "issue": "SSL certificate problem",
            "detail": ssl_info["error"],
            "severity": "critical",
        })
    elif ssl_info.get("days_until_expiry", 999) < 30:
        issues.append({
            "issue": "SSL certificate expiring soon",
            "detail": f"Certificate expires in {ssl_info['days_until_expiry']} days",
            "severity": "warning",
        })

    # HTTPS check
    if parsed.scheme != "https":
        issues.append({
            "issue": "Not using HTTPS",
            "detail": "Site is served over HTTP — all data transmitted in plaintext",
            "severity": "critical",
        })
        findings["https"] = False
    else:
        findings["https"] = True

    # --- Security Headers ---
    security_headers = {
        "strict-transport-security": {
            "name": "HSTS",
            "severity": "warning",
            "detail": "Missing Strict-Transport-Security header — browsers won't enforce HTTPS",
        },
        "content-security-policy": {
            "name": "CSP",
            "severity": "warning",
            "detail": "Missing Content-Security-Policy — vulnerable to XSS attacks",
        },
        "x-content-type-options": {
            "name": "X-Content-Type-Options",
            "severity": "info",
            "detail": "Missing X-Content-Type-Options: nosniff header",
        },
        "x-frame-options": {
            "name": "X-Frame-Options",
            "severity": "info",
            "detail": "Missing X-Frame-Options — vulnerable to clickjacking",
        },
        "referrer-policy": {
            "name": "Referrer-Policy",
            "severity": "info",
            "detail": "Missing Referrer-Policy header",
        },
        "permissions-policy": {
            "name": "Permissions-Policy",
            "severity": "info",
            "detail": "Missing Permissions-Policy header",
        },
    }

    findings["headers_present"] = {}
    for header_key, info in security_headers.items():
        present = header_key in headers
        findings["headers_present"][info["name"]] = present
        if not present:
            issues.append({
                "issue": f"Missing {info['name']} header",
                "detail": info["detail"],
                "severity": info["severity"],
            })

    # --- Mixed Content Check ---
    if parsed.scheme == "https":
        soup = BeautifulSoup(crawl_result.html, "lxml")
        mixed = _check_mixed_content(soup)
        findings["mixed_content"] = mixed
        if mixed:
            issues.append({
                "issue": "Mixed content detected",
                "detail": f"{len(mixed)} resources loaded over HTTP on HTTPS page",
                "severity": "warning",
            })

    # --- Information Disclosure ---
    server = headers.get("server", "")
    x_powered = headers.get("x-powered-by", "")
    if server and re.search(r"\d+\.\d+", server):
        issues.append({
            "issue": "Server version disclosed",
            "detail": f"Server header reveals version: {server}",
            "severity": "info",
        })
    if x_powered:
        issues.append({
            "issue": "Technology stack disclosed",
            "detail": f"X-Powered-By reveals: {x_powered}",
            "severity": "info",
        })

    # --- Cookie Flags ---
    set_cookie = headers.get("set-cookie", "")
    if set_cookie:
        cookie_issues = _check_cookies(set_cookie)
        findings["cookie_issues"] = cookie_issues
        for ci in cookie_issues:
            issues.append(ci)

    severities = [i["severity"] for i in issues]
    if "critical" in severities:
        overall = "critical"
    elif "warning" in severities:
        overall = "warning"
    else:
        overall = "good"

    return {
        "findings": findings,
        "issues": issues,
        "issue_count": len(issues),
        "severity": overall,
    }


def _check_ssl(hostname: str) -> dict:
    """Check SSL certificate validity and expiry."""
    if ":" in hostname:
        hostname = hostname.split(":")[0]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return {"error": "No certificate returned"}

                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                not_after = not_after.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_left = (not_after - now).days

                return {
                    "valid": True,
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "expires": not_after.isoformat(),
                    "days_until_expiry": days_left,
                }
    except ssl.SSLCertVerificationError as e:
        return {"valid": False, "error": f"Certificate verification failed: {e}"}
    except Exception as e:
        return {"error": f"SSL check failed: {e}"}


def _check_mixed_content(soup: BeautifulSoup) -> list[str]:
    """Find HTTP resources on an HTTPS page."""
    mixed = []
    for tag in soup.find_all(["img", "script", "link", "iframe", "video", "audio", "source"]):
        src = tag.get("src") or tag.get("href") or ""
        if src.startswith("http://"):
            mixed.append(src)
    return mixed[:20]  # Limit to first 20


def _check_cookies(set_cookie: str) -> list[dict]:
    """Check cookie security flags."""
    issues = []
    if "secure" not in set_cookie.lower():
        issues.append({
            "issue": "Cookie missing Secure flag",
            "detail": "Cookies may be transmitted over unencrypted connections",
            "severity": "warning",
        })
    if "httponly" not in set_cookie.lower():
        issues.append({
            "issue": "Cookie missing HttpOnly flag",
            "detail": "Cookies accessible to JavaScript — risk of XSS theft",
            "severity": "info",
        })
    if "samesite" not in set_cookie.lower():
        issues.append({
            "issue": "Cookie missing SameSite flag",
            "detail": "Cookies may be sent in cross-site requests — CSRF risk",
            "severity": "info",
        })
    return issues
