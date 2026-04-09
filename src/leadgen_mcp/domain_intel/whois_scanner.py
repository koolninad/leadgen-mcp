"""WHOIS domain intelligence — detect new registrations, expiring domains, and registrant info."""

import asyncio
from datetime import datetime, timezone, timedelta

import httpx

from ..utils.http import create_client


WHOIS_API_URLS = [
    "https://whois.freeaitools.org/api/v1/whois",
    "https://api.whoisfreaks.com/v1.0/whois",
]


async def lookup_whois(domain: str) -> dict:
    """Query WHOIS APIs with fallback and return parsed registration data.

    Tries multiple public WHOIS APIs to handle DNS resolution failures
    or service outages gracefully.
    """
    last_error = None
    for api_url in WHOIS_API_URLS:
        try:
            async with create_client(timeout=20.0, use_ipv6=False) as client:
                resp = await client.get(api_url, params={"domain": domain})
                resp.raise_for_status()
                data = resp.json()
                return _parse_whois(domain, data)
        except httpx.HTTPStatusError as e:
            last_error = f"WHOIS API returned {e.response.status_code}"
        except httpx.ConnectError as e:
            last_error = f"WHOIS API connection failed (DNS/network): {e}"
        except httpx.RequestError as e:
            last_error = f"WHOIS request failed: {e}"
        except Exception as e:
            last_error = str(e)

    # All APIs failed — try python-whois as a local fallback
    try:
        import whois as python_whois
        raw = python_whois.whois(domain)
        if raw:
            raw_dict = {}
            for key in ("creation_date", "expiration_date", "updated_date",
                        "registrar", "name_servers", "status",
                        "registrant_name", "registrant_organization",
                        "registrant_country"):
                val = getattr(raw, key, None)
                if val is not None:
                    raw_dict[key] = val
            return _parse_whois(domain, raw_dict)
    except ImportError:
        pass
    except Exception:
        pass

    return {"domain": domain, "error": last_error or "All WHOIS lookups failed"}


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


async def scan_new_domains_feed(tld: str = "com", days_back: int = 3) -> list[dict]:
    """Fetch newly registered domains from multiple NRD sources.

    Tries multiple free NRD feeds in order of reliability.
    """
    now = datetime.now(timezone.utc)
    domains_found = []

    # Source 1: WhoisDS downloadable zip feeds
    # Format: https://whoisds.com/whois-database/newly-registered-domains/YYYY-MM-DD.zip
    try:
        async with create_client(timeout=15.0, use_ipv6=False) as client:
            for day_offset in range(days_back):
                date = now - timedelta(days=day_offset + 1)
                date_str = date.strftime("%Y-%m-%d")

                # Try multiple URL formats
                urls = [
                    f"https://whoisds.com/whois-database/newly-registered-domains/{date_str}.{tld}/nrd",
                    f"https://newly-registered-domains.adrustd.com/{date_str}/{tld}.txt",
                ]

                for feed_url in urls:
                    try:
                        resp = await asyncio.wait_for(client.get(feed_url), timeout=10)
                        if resp.status_code == 200 and len(resp.text) > 10:
                            for line in resp.text.strip().split("\n"):
                                domain = line.strip().lower()
                                if domain and "." in domain and len(domain) > 3 and not domain.startswith("#"):
                                    domains_found.append({
                                        "domain": domain,
                                        "registered_date": date_str,
                                        "tld": tld,
                                        "signal": "newly_registered",
                                    })
                            if domains_found:
                                break
                    except (httpx.RequestError, asyncio.TimeoutError):
                        continue
                if domains_found:
                    break
    except Exception:
        pass

    # Source 2: Use SearXNG to find recently registered domains
    if not domains_found:
        try:
            from ..utils.search import web_search
            results = await web_search(f"newly registered .{tld} domains today", max_results=10)
            for r in results:
                url = r.get("url", "")
                if url and f".{tld}" in url:
                    domain = url.split("//")[-1].split("/")[0].lower()
                    if domain.endswith(f".{tld}"):
                        domains_found.append({
                            "domain": domain,
                            "tld": tld,
                            "signal": "newly_registered",
                        })
        except Exception:
            pass

    return domains_found[:200]
