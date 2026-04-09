"""WHOIS lookup via self-hosted who-dat API.

who-dat provides a REST API for WHOIS lookups:
  - GET /{domain}       — single domain lookup
  - GET /multi?domains= — batch lookup (comma-separated)

We rate-limit requests to avoid overwhelming the service and
parse the response into a normalized structure for scoring.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import aiosqlite

from ..config import settings
from .models import NRD_SCHEMA_SQL

logger = logging.getLogger("leadgen.nrd.whois")

WHODAT_BASE_URL = "http://localhost:8890"

# Rate limiting: max requests per second to who-dat
MAX_RPS = 10
_request_times: list[float] = []


async def _rate_limit():
    """Simple sliding-window rate limiter."""
    global _request_times
    now = time.monotonic()
    # Remove entries older than 1 second
    _request_times = [t for t in _request_times if now - t < 1.0]
    if len(_request_times) >= MAX_RPS:
        wait = 1.0 - (now - _request_times[0])
        if wait > 0:
            await asyncio.sleep(wait)
    _request_times.append(time.monotonic())


async def _get_nrd_db() -> aiosqlite.Connection:
    """Get a connection to the shared DB with NRD tables initialized."""
    db_path = settings.db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(NRD_SCHEMA_SQL)
    await db.commit()
    return db


def _parse_whois_response(data: dict) -> dict:
    """Extract useful fields from a who-dat WHOIS JSON response.

    who-dat returns a fairly raw WHOIS structure. We normalize it into
    the fields we care about for scoring and outreach.
    """
    result = {
        "registrar": None,
        "creation_date": None,
        "expiry_date": None,
        "registrant_name": None,
        "registrant_email": None,
        "registrant_org": None,
        "nameservers": [],
        "raw": data,
    }

    if not data or not isinstance(data, dict):
        return result

    # who-dat response structure can vary; handle common shapes
    # Try direct fields first
    whois = data.get("whois", data)

    # Registrar
    result["registrar"] = (
        whois.get("registrar", {}).get("name")
        or whois.get("registrar_name")
        or whois.get("registrar")
        if isinstance(whois.get("registrar"), str) else None
    )
    if not result["registrar"] and isinstance(whois.get("registrar"), dict):
        result["registrar"] = whois["registrar"].get("name") or whois["registrar"].get("organization")

    # Dates
    result["creation_date"] = (
        whois.get("creation_date")
        or whois.get("created")
        or whois.get("createdDate")
        or whois.get("created_date")
    )
    result["expiry_date"] = (
        whois.get("expiration_date")
        or whois.get("expires")
        or whois.get("expiryDate")
        or whois.get("expiry_date")
    )

    # Registrant info — can be nested under "registrant" or at top level
    registrant = whois.get("registrant", {})
    if isinstance(registrant, dict):
        result["registrant_name"] = (
            registrant.get("name")
            or registrant.get("contact_name")
        )
        result["registrant_email"] = (
            registrant.get("email")
            or registrant.get("contact_email")
        )
        result["registrant_org"] = (
            registrant.get("organization")
            or registrant.get("org")
            or registrant.get("company")
        )

    # Fall back to top-level fields
    if not result["registrant_email"]:
        result["registrant_email"] = (
            whois.get("registrant_email")
            or whois.get("email")
            or whois.get("abuse_email")
        )
    if not result["registrant_name"]:
        result["registrant_name"] = whois.get("registrant_name")
    if not result["registrant_org"]:
        result["registrant_org"] = (
            whois.get("registrant_organization")
            or whois.get("registrant_org")
        )

    # Nameservers
    ns = whois.get("nameservers", whois.get("name_servers", []))
    if isinstance(ns, list):
        result["nameservers"] = [str(n).lower() for n in ns if n]
    elif isinstance(ns, str):
        result["nameservers"] = [n.strip().lower() for n in ns.split(",") if n.strip()]

    return result


async def lookup_single(domain: str, client: httpx.AsyncClient | None = None) -> dict:
    """Look up WHOIS for a single domain via who-dat."""
    await _rate_limit()

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        close_client = True

    try:
        url = f"{WHODAT_BASE_URL}/{domain}"
        resp = await client.get(url)

        if resp.status_code == 200:
            data = resp.json()
            return _parse_whois_response(data)
        elif resp.status_code == 429:
            logger.warning("who-dat rate limited, backing off...")
            await asyncio.sleep(5.0)
            return {"error": "rate_limited", "raw": {}}
        else:
            logger.debug("who-dat returned %d for %s", resp.status_code, domain)
            return {"error": f"http_{resp.status_code}", "raw": {}}

    except httpx.TimeoutException:
        logger.debug("who-dat timeout for %s", domain)
        return {"error": "timeout", "raw": {}}
    except Exception as e:
        logger.debug("who-dat error for %s: %s", domain, e)
        return {"error": str(e), "raw": {}}
    finally:
        if close_client:
            await client.aclose()


async def lookup_batch(
    domains: list[str],
    concurrency: int = 5,
) -> dict[str, dict]:
    """Look up WHOIS for multiple domains with concurrency control.

    Uses individual lookups with a semaphore for controlled parallelism,
    since the /multi endpoint may not be available in all who-dat versions.

    Returns: {domain: parsed_whois_data}
    """
    results: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def _lookup_one(domain: str, client: httpx.AsyncClient):
        async with semaphore:
            result = await lookup_single(domain, client)
            results[domain] = result

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        # Try the /multi endpoint first for efficiency
        try:
            multi_result = await _try_multi_lookup(domains, client)
            if multi_result:
                return multi_result
        except Exception:
            pass  # Fall back to individual lookups

        # Individual lookups with controlled concurrency
        tasks = [_lookup_one(d, client) for d in domains]
        await asyncio.gather(*tasks, return_exceptions=True)

    return results


async def _try_multi_lookup(
    domains: list[str],
    client: httpx.AsyncClient,
) -> dict[str, dict] | None:
    """Try the /multi endpoint for batch lookups.

    Returns None if the endpoint is not available.
    """
    await _rate_limit()

    try:
        # who-dat /multi expects comma-separated domains
        domain_str = ",".join(domains[:50])  # Cap at 50 per request
        resp = await client.get(
            f"{WHODAT_BASE_URL}/multi",
            params={"domains": domain_str},
            timeout=httpx.Timeout(60.0),
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = {}

        # Handle different response formats
        if isinstance(data, dict):
            for domain, whois_data in data.items():
                results[domain] = _parse_whois_response(whois_data)
        elif isinstance(data, list):
            for i, whois_data in enumerate(data):
                if i < len(domains):
                    results[domains[i]] = _parse_whois_response(whois_data)

        return results if results else None

    except Exception as e:
        logger.debug("/multi endpoint not available: %s", e)
        return None


PRIVACY_KEYWORDS = [
    "privacy", "proxy", "whoisguard", "protect", "redacted",
    "domainsbyproxy", "contactprivacy", "withheld", "not disclosed",
    "data protected", "gdpr", "registrant not", "shieldwhois",
    "whoisprivacy", "domainprivacy", "identityprotect", "privacydotlink",
    "whoisproxy", "1and1-private", "networksolutionsprivate",
    "godaddy.com/whois", "abuse@", "noreply@",
]


def _has_real_email(email: str | None) -> bool:
    """Check if email is a real registrant email (not privacy/proxy)."""
    if not email or "@" not in email:
        return False
    email_lower = email.lower()
    return not any(kw in email_lower for kw in PRIVACY_KEYWORDS)


async def save_whois_to_db(domain: str, whois_data: dict, registered_date: str = "") -> None:
    """Save WHOIS data — real emails go to nrd_domains, rest to nrd_domains_ref."""
    db = await _get_nrd_db()
    try:
        raw_json = json.dumps(whois_data.get("raw", {}), default=str)
        nameservers_json = json.dumps(whois_data.get("nameservers", []))
        registrant_email = whois_data.get("registrant_email")
        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""

        if _has_real_email(registrant_email):
            # Actionable lead → nrd_domains
            await db.execute(
                """INSERT OR REPLACE INTO nrd_domains
                   (domain, tld, registered_date, whois_data, registrant_email,
                    registrant_name, registrant_org, registrar, creation_date,
                    expiry_date, nameservers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    domain, tld, registered_date or "", raw_json,
                    registrant_email,
                    whois_data.get("registrant_name"),
                    whois_data.get("registrant_org"),
                    whois_data.get("registrar"),
                    whois_data.get("creation_date"),
                    whois_data.get("expiry_date"),
                    nameservers_json,
                ),
            )
        else:
            # No actionable email → reference table only
            await db.execute(
                """INSERT OR IGNORE INTO nrd_domains_ref
                   (domain, tld, registered_date, registrant_email,
                    registrar, nameservers)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    domain, tld, registered_date or "", registrant_email,
                    whois_data.get("registrar"), nameservers_json,
                ),
            )
            # Also remove from nrd_domains if it was there from initial ingest
            await db.execute("DELETE FROM nrd_domains WHERE domain = ?", (domain,))

        await db.commit()
    finally:
        await db.close()


async def process_whois_batch(
    domains: list[str],
    concurrency: int = 5,
) -> dict[str, dict]:
    """Look up WHOIS for a batch of domains and save results to DB.

    Domains with real emails → nrd_domains
    Domains without → nrd_domains_ref
    """
    # Get registered_date from staging for each domain
    db = await _get_nrd_db()
    date_map = {}
    try:
        for domain in domains:
            rows = await db.execute_fetchall(
                "SELECT registered_date FROM nrd_staging WHERE domain = ?", (domain,)
            )
            if rows:
                date_map[domain] = rows[0][0]
    finally:
        await db.close()

    results = await lookup_batch(domains, concurrency=concurrency)

    # Save all results — real emails go to nrd_domains, rest to nrd_domains_ref
    for domain, whois_data in results.items():
        reg_date = date_map.get(domain, "")
        try:
            await save_whois_to_db(domain, whois_data, registered_date=reg_date)
        except Exception as e:
            logger.warning("Failed to save WHOIS for %s: %s", domain, e)

    return results
