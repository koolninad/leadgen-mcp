"""Async client for the self-hosted truemail-rack service.

Truemail-rack (https://github.com/truemail-rb/truemail-rack) performs a
multi-layer email validation pipeline:

    regex -> MX lookup -> SMTP RCPT TO probe -> blacklist / whitelist

We run it as a Docker service (docker-compose.truemail.yml) on
``settings.truemail_url`` and authenticate via ``X-Access-Token``.

Responses are cached in-memory with a TTL to avoid hammering MX servers
(they will start tempfailing / greylisting if we probe the same address
repeatedly).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..config import settings
from ..utils.validators import clean_email, is_valid_email


_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


def _cache_get(email: str) -> dict[str, Any] | None:
    entry = _cache.get(email)
    if not entry:
        return None
    expires_at, payload = entry
    if time.time() > expires_at:
        _cache.pop(email, None)
        return None
    return payload


def _cache_put(email: str, payload: dict[str, Any]) -> None:
    ttl = settings.truemail_cache_ttl
    _cache[email] = (time.time() + ttl, payload)


class TruemailError(RuntimeError):
    """Raised when truemail-rack returns an unexpected response."""


def _normalize_response(email: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten truemail-rack's verbose payload into a simple verdict."""
    success = bool(raw.get("success"))
    errors = raw.get("errors") or {}
    validation_type = raw.get("validation_type", "unknown")

    # Map failure layer -> human-readable reason
    reason = None
    if not success:
        for layer in ("smtp", "mx", "mx_blacklist", "regex", "domain_list_match"):
            if layer in errors:
                reason = f"{layer}: {errors[layer]}"
                break
        if reason is None and errors:
            first_key = next(iter(errors))
            reason = f"{first_key}: {errors[first_key]}"

    return {
        "email": email,
        "valid": success,
        "validation_type": validation_type,
        "reason": reason,
        "errors": errors,
        "smtp_debug": raw.get("smtp_debug"),
        "raw": raw,
    }


async def verify_email(
    email: str,
    *,
    client: httpx.AsyncClient | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Verify a single email via truemail-rack.

    Returns a dict with keys: ``email``, ``valid``, ``validation_type``,
    ``reason``, ``errors``. Never raises for validation failures — only for
    transport/config errors. When truemail is disabled or unreachable, falls
    back to a regex-only verdict so callers can always get a result.
    """
    email = clean_email(email)
    if not is_valid_email(email):
        return {
            "email": email,
            "valid": False,
            "validation_type": "regex",
            "reason": "regex: invalid syntax",
            "errors": {"regex": "invalid syntax"},
        }

    if not settings.truemail_enabled:
        return {
            "email": email,
            "valid": True,
            "validation_type": "regex",
            "reason": None,
            "errors": {},
            "note": "truemail disabled; regex-only verdict",
        }

    if use_cache:
        cached = _cache_get(email)
        if cached is not None:
            return cached

    headers = {"X-Access-Token": settings.truemail_access_token}
    params = {"email": email}
    url = settings.truemail_url.rstrip("/") + "/"

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.truemail_timeout)

    try:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 401:
            raise TruemailError("truemail-rack: invalid X-Access-Token")
        if resp.status_code >= 500:
            # Server-side issue — do NOT cache, fall back to regex verdict.
            return {
                "email": email,
                "valid": True,
                "validation_type": "regex",
                "reason": None,
                "errors": {},
                "note": f"truemail upstream {resp.status_code}; regex-only verdict",
            }
        resp.raise_for_status()
        raw = resp.json()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
        # Service unreachable — regex verdict, don't cache.
        return {
            "email": email,
            "valid": True,
            "validation_type": "regex",
            "reason": None,
            "errors": {},
            "note": f"truemail unreachable ({exc.__class__.__name__}); regex-only verdict",
        }
    finally:
        if own_client:
            await client.aclose()

    result = _normalize_response(email, raw)
    if use_cache:
        async with _cache_lock:
            _cache_put(email, result)
    return result


async def verify_batch(
    emails: list[str],
    *,
    concurrency: int = 5,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Verify many emails concurrently. Concurrency kept modest because every
    SMTP probe hits a real MX server — we do not want to look like a spammer.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=settings.truemail_timeout) as client:
        async def _one(addr: str) -> dict[str, Any]:
            async with semaphore:
                return await verify_email(addr, client=client, use_cache=use_cache)

        return await asyncio.gather(*(_one(e) for e in emails))


async def health_check() -> dict[str, Any]:
    """Return reachability/config status for truemail-rack."""
    url = settings.truemail_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"X-Access-Token": settings.truemail_access_token},
                params={"email": "healthcheck@example.com"},
            )
        return {
            "reachable": True,
            "status_code": resp.status_code,
            "authenticated": resp.status_code != 401,
        }
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}
