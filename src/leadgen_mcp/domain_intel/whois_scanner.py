"""WHOIS domain intelligence — detect new registrations, expiring domains, and registrant info."""

import asyncio
from datetime import datetime, timezone, timedelta

import httpx

from ..utils.http import create_client


WHOIS_API_URL = "https://whois.freeaitools.org/api/v1/whois"


async def lookup_whois(domain: str) -> dict:
    """Query a free WHOIS API and return parsed registration data."""
    try:
        async with create_client(timeout=20.0) as client:
            resp = await client.get(WHOIS_API_URL, params={"domain": domain})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"domain": domain, "error": f"WHOIS API returned {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"domain": domain, "error": f"WHOIS request failed: {e}"}
    except Exception as e:
        return {"domain": domain, "error": str(e)}

    return _parse_whois(domain, data)


def _parse_whois(domain: str, raw: dict) -> dict:
    """Extract useful fields from raw WHOIS API response."""
    now = datetime.now(timezone.utc)

    result: dict = {
        "domain": domain,
        "raw_status": raw.get("status"),
    }

    # --- Registrant info ---
    registrant = {}
    for key in ("registrant_name", "registrant_organization", "registrant_email",
                "registrant_country", "registrant_state", "registrant_city"):
        val = raw.get(key) or raw.get(key.replace("registrant_", ""))
        if val and val.lower() not in ("redacted", "redacted for privacy", "not disclosed", ""):
            registrant[key.replace("registrant_", "")] = val
    result["registrant"] = registrant if registrant else None

    # --- Dates ---
    creation_date = _parse_date(raw.get("creation_date") or raw.get("created"))
    expiry_date = _parse_date(raw.get("expiration_date") or raw.get("expires") or raw.get("registry_expiry_date"))
    updated_date = _parse_date(raw.get("updated_date") or raw.get("updated"))

    result["creation_date"] = creation_date.isoformat() if creation_date else None
    result["expiry_date"] = expiry_date.isoformat() if expiry_date else None
    result["updated_date"] = updated_date.isoformat() if updated_date else None

    # --- Age analysis ---
    if creation_date:
        age_days = (now - creation_date).days
        result["age_days"] = age_days
        result["is_new_domain"] = age_days < 90
        if age_days < 90:
            result["signal"] = "newly_registered"
            result["signal_detail"] = f"Domain registered {age_days} days ago — likely a new business needing a website"
    else:
        result["age_days"] = None
        result["is_new_domain"] = None

    # --- Expiry analysis ---
    if expiry_date:
        days_until_expiry = (expiry_date - now).days
        result["days_until_expiry"] = days_until_expiry
        result["is_expired"] = days_until_expiry < 0
        result["is_expiring_soon"] = 0 <= days_until_expiry <= 30
        if days_until_expiry < 0:
            result["signal"] = "expired"
            result["signal_detail"] = f"Domain expired {abs(days_until_expiry)} days ago — business may need rebuilding"
        elif days_until_expiry <= 30:
            result["signal"] = "expiring_soon"
            result["signal_detail"] = f"Domain expires in {days_until_expiry} days"
    else:
        result["days_until_expiry"] = None
        result["is_expired"] = None
        result["is_expiring_soon"] = None

    # --- Registrar ---
    result["registrar"] = raw.get("registrar") or raw.get("registrar_name")
    result["nameservers"] = raw.get("nameservers") or raw.get("name_servers") or []

    return result


def _parse_date(value) -> datetime | None:
    """Parse a date string from WHOIS data (multiple formats)."""
    if not value:
        return None
    if isinstance(value, list):
        value = value[0]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


async def scan_new_domains_feed(tld: str = "com", days_back: int = 7) -> list[dict]:
    """Fetch newly registered domains from public NRD (Newly Registered Domain) feeds.

    Uses the WhoisDS free daily feed or similar public sources.
    """
    results = []
    base_url = "https://whoisds.com/newly-registered-domains"

    now = datetime.now(timezone.utc)
    domains_found = []

    try:
        async with create_client(timeout=30.0) as client:
            # Try the free daily feed from whoisds.com (provides zip of domains)
            for day_offset in range(days_back):
                date = now - timedelta(days=day_offset)
                date_str = date.strftime("%Y-%m-%d")
                feed_url = f"https://whoisds.com/whois-database/newly-registered-domains/{date_str}.{tld}/nrd"

                try:
                    resp = await client.get(feed_url)
                    if resp.status_code == 200:
                        text = resp.text
                        for line in text.strip().split("\n"):
                            domain = line.strip().lower()
                            if domain and domain.endswith(f".{tld}"):
                                domains_found.append({
                                    "domain": domain,
                                    "registered_date": date_str,
                                    "tld": tld,
                                    "signal": "newly_registered",
                                })
                except httpx.RequestError:
                    continue

    except Exception as e:
        return [{"error": f"Failed to fetch NRD feed: {e}"}]

    # Limit to a reasonable number
    return domains_found[:500]
