"""Email discovery and verification for lead domains."""

import asyncio
import json
import re
from pathlib import Path

import dns.resolver
from bs4 import BeautifulSoup

from ..utils.http import create_client
from ..utils.validators import is_valid_email, clean_email


_PATTERNS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "email_patterns.json"
_patterns: list[str] | None = None


def _load_patterns() -> list[str]:
    global _patterns
    if _patterns is None:
        try:
            _patterns = json.loads(_PATTERNS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _patterns = [
                "{first}@{domain}",
                "{first}.{last}@{domain}",
                "{first}{last}@{domain}",
                "{f}{last}@{domain}",
                "{first}_{last}@{domain}",
                "{first}-{last}@{domain}",
                "{last}@{domain}",
                "info@{domain}",
                "contact@{domain}",
                "hello@{domain}",
                "sales@{domain}",
                "support@{domain}",
            ]
    return _patterns


async def find_emails_on_page(url: str) -> list[str]:
    """Extract email addresses from a webpage."""
    try:
        async with create_client(timeout=15.0) as client:
            resp = await client.get(url)
            html = resp.text
    except Exception:
        return []

    emails = set()

    # Regex extraction from HTML
    found = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
    for email in found:
        cleaned = clean_email(email)
        if is_valid_email(cleaned) and not _is_junk_email(cleaned):
            emails.add(cleaned)

    # mailto: links
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        href = link["href"]
        email = href.replace("mailto:", "").split("?")[0].strip()
        cleaned = clean_email(email)
        if is_valid_email(cleaned):
            emails.add(cleaned)

    return list(emails)


async def generate_candidate_emails(
    domain: str, first_name: str = "", last_name: str = ""
) -> list[str]:
    """Generate candidate email addresses using common patterns."""
    patterns = _load_patterns()
    candidates = []

    first = first_name.lower().strip()
    last = last_name.lower().strip()
    f = first[0] if first else ""

    for pattern in patterns:
        try:
            email = pattern.format(
                first=first, last=last, f=f,
                domain=domain,
            )
            if is_valid_email(email):
                candidates.append(email)
        except (KeyError, IndexError):
            continue

    return list(dict.fromkeys(candidates))  # deduplicate preserving order


async def verify_mx_record(domain: str) -> dict:
    """Check if domain has valid MX records."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5
        answers = resolver.resolve(domain, "MX")
        mx_records = [str(r.exchange).rstrip(".") for r in answers]
        return {
            "has_mx": True,
            "mx_records": mx_records,
            "is_catch_all": _detect_catch_all(mx_records),
        }
    except dns.resolver.NXDOMAIN:
        return {"has_mx": False, "error": "Domain does not exist"}
    except dns.resolver.NoAnswer:
        return {"has_mx": False, "error": "No MX records"}
    except Exception as e:
        return {"has_mx": False, "error": str(e)}


def _detect_catch_all(mx_records: list[str]) -> bool:
    """Heuristic check for catch-all mail servers."""
    # Common catch-all indicators
    catch_all_providers = ["improvmx.com", "forwardemail.net", "mailgun.org"]
    for mx in mx_records:
        for provider in catch_all_providers:
            if provider in mx.lower():
                return True
    return False


async def find_emails_for_domain(
    domain: str, contact_name: str | None = None
) -> dict:
    """Full email discovery pipeline for a domain."""
    results = {
        "domain": domain,
        "emails_found": [],
        "candidates_generated": [],
        "mx_info": {},
    }

    # 1. Check MX records
    mx_info = await verify_mx_record(domain)
    results["mx_info"] = mx_info

    if not mx_info.get("has_mx"):
        return results

    # 2. Scrape emails from website pages
    pages_to_check = [
        f"https://{domain}",
        f"https://{domain}/contact",
        f"https://{domain}/about",
        f"https://{domain}/team",
        f"https://{domain}/contact-us",
        f"https://{domain}/about-us",
    ]

    tasks = [find_emails_on_page(url) for url in pages_to_check]
    page_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_emails = set()
    for result in page_results:
        if isinstance(result, list):
            all_emails.update(result)

    results["emails_found"] = list(all_emails)

    # 3. Generate candidate emails if we have a contact name
    if contact_name:
        parts = contact_name.strip().split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""
        candidates = await generate_candidate_emails(domain, first, last)
        results["candidates_generated"] = candidates

    return results


def _is_junk_email(email: str) -> bool:
    """Filter out common junk/placeholder emails."""
    junk_patterns = [
        r"@example\.",
        r"@test\.",
        r"@localhost",
        r"noreply@",
        r"no-reply@",
        r"mailer-daemon@",
        r"postmaster@",
        r"@sentry\.",
        r"@wixpress\.",
        r"@placeholder\.",
        r".*@.*\.png$",
        r".*@.*\.jpg$",
    ]
    for pattern in junk_patterns:
        if re.search(pattern, email, re.I):
            return True
    return False
