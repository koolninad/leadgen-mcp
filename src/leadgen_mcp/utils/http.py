"""Shared async HTTP client with retry, user-agent rotation, IPv6 rotation, and proxy support."""

from __future__ import annotations

import asyncio
import ipaddress
import random
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-US,en;q=0.9,de;q=0.8",
    "en-US,en;q=0.9,es;q=0.8",
    "en;q=0.9",
]

ACCEPT_ENCODINGS = [
    "gzip, deflate, br",
    "gzip, deflate",
    "gzip, deflate, br, zstd",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


# ---------------------------------------------------------------------------
# IPv6 Rotator
# ---------------------------------------------------------------------------

class IPv6Rotator:
    """Generate random IPv6 addresses within a given subnet.

    If the user has a /48 or /64 block, they have trillions of unique IPs
    to rotate through, making IP-based bans nearly impossible.
    """

    def __init__(self, prefix: str, pool_size: int = 100) -> None:
        self._network = ipaddress.IPv6Network(prefix, strict=False)
        self._pool_size = pool_size
        self._pool: list[str] = []
        self._refresh_pool()

    def _refresh_pool(self) -> None:
        """Pre-generate a pool of random addresses within the subnet."""
        net = self._network
        # Number of host addresses in the subnet
        num_addresses = int(net.num_addresses)
        self._pool = []
        for _ in range(self._pool_size):
            # Generate a random offset within the subnet and add to the
            # network address to get a valid address in range.
            offset = random.randint(0, num_addresses - 1)
            addr = ipaddress.IPv6Address(int(net.network_address) + offset)
            self._pool.append(str(addr))

    def get_random_address(self) -> str:
        """Return a random IPv6 address from the pre-generated pool."""
        return random.choice(self._pool)

    def rotate(self) -> None:
        """Regenerate the pool (call periodically if desired)."""
        self._refresh_pool()


# Module-level rotator, initialised lazily.
_ipv6_rotator: IPv6Rotator | None = None


def _get_ipv6_rotator() -> IPv6Rotator | None:
    """Return the module-level IPv6Rotator (created on first call)."""
    global _ipv6_rotator
    if _ipv6_rotator is not None:
        return _ipv6_rotator
    if settings.ipv6_enabled and settings.ipv6_prefix:
        _ipv6_rotator = IPv6Rotator(
            prefix=settings.ipv6_prefix,
            pool_size=settings.ipv6_pool_size,
        )
    return _ipv6_rotator


# ---------------------------------------------------------------------------
# Proxy rotation
# ---------------------------------------------------------------------------

_proxy_list: list[str] | None = None


def _load_proxy_list() -> list[str]:
    """Load proxies from the configured file (one URL per line)."""
    global _proxy_list
    if _proxy_list is not None:
        return _proxy_list
    _proxy_list = []
    if settings.proxy_list_file:
        path = Path(settings.proxy_list_file)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    _proxy_list.append(line)
    return _proxy_list


def get_random_proxy() -> str | None:
    """Return a random proxy URL from the proxy list, or the single configured proxy."""
    proxies = _load_proxy_list()
    if proxies:
        return random.choice(proxies)
    return settings.http_proxy


# ---------------------------------------------------------------------------
# Identity helper
# ---------------------------------------------------------------------------

@dataclass
class Identity:
    """A bundle of randomised request attributes."""
    user_agent: str
    ipv6_address: str | None = None
    proxy: str | None = None
    accept_language: str = "en-US,en;q=0.9"
    accept_encoding: str = "gzip, deflate, br"


def get_next_identity() -> Identity:
    """Return a random UA, optional random IPv6 address, and randomised headers."""
    rotator = _get_ipv6_rotator()
    return Identity(
        user_agent=random_ua(),
        ipv6_address=rotator.get_random_address() if rotator else None,
        proxy=get_random_proxy(),
        accept_language=random.choice(ACCEPT_LANGUAGES),
        accept_encoding=random.choice(ACCEPT_ENCODINGS),
    )


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def create_client(
    timeout: float = 30.0,
    max_retries: int = 3,
    follow_redirects: bool = True,
    local_address: str | None = None,
    proxy: str | None = ...,  # sentinel: use settings default
) -> httpx.AsyncClient:
    """Create an ``httpx.AsyncClient``.

    Parameters
    ----------
    local_address:
        Optional local IP (v4 or v6) to bind outgoing connections to.
        Useful for IPv6 rotation.
    proxy:
        Explicit proxy URL.  When omitted (default sentinel), falls back to
        ``settings.http_proxy``.  Pass ``None`` to disable.
    """
    transport_kwargs: dict = dict(
        retries=max_retries,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),
    )
    if local_address:
        transport_kwargs["local_address"] = local_address

    transport = httpx.AsyncHTTPTransport(**transport_kwargs)

    resolved_proxy = settings.http_proxy if proxy is ... else proxy

    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        follow_redirects=follow_redirects,
        headers={"User-Agent": random_ua()},
        proxy=resolved_proxy,
    )


def create_stealth_client(
    timeout: float = 30.0,
    max_retries: int = 3,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Create a *stealth* client that combines random UA, IPv6, proxy, and varied headers.

    Designed to minimise fingerprint consistency across requests.
    """
    identity = get_next_identity()

    transport_kwargs: dict = dict(
        retries=max_retries,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),
    )
    if identity.ipv6_address:
        transport_kwargs["local_address"] = identity.ipv6_address

    transport = httpx.AsyncHTTPTransport(**transport_kwargs)

    headers = {
        "User-Agent": identity.user_agent,
        "Accept-Language": identity.accept_language,
        "Accept-Encoding": identity.accept_encoding,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        follow_redirects=follow_redirects,
        headers=headers,
        proxy=identity.proxy,
    )


async def stealth_delay() -> None:
    """Sleep for a random duration between 1-3 seconds to mimic human pacing."""
    await asyncio.sleep(random.uniform(1.0, 3.0))


async def fetch_url(url: str, timeout: float = 30.0) -> httpx.Response:
    async with create_client(timeout=timeout) as client:
        return await client.get(url)


async def stealth_fetch_url(url: str, timeout: float = 30.0) -> httpx.Response:
    """Fetch a URL using the stealth client with a random pre-request delay."""
    await stealth_delay()
    async with create_stealth_client(timeout=timeout) as client:
        return await client.get(url)
