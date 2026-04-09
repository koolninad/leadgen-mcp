"""robots.txt parser with caching."""

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .http import fetch_url

_cache: dict[str, tuple[RobotFileParser, float]] = {}
CACHE_TTL = 86400  # 24 hours


async def can_crawl(url: str, user_agent: str = "*") -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    now = time.time()
    if base in _cache:
        parser, cached_at = _cache[base]
        if now - cached_at < CACHE_TTL:
            return parser.can_fetch(user_agent, url)

    parser = RobotFileParser()
    try:
        resp = await fetch_url(f"{base}/robots.txt", timeout=10.0)
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        else:
            # No robots.txt = everything allowed
            parser.allow_all = True
    except Exception:
        parser.allow_all = True

    _cache[base] = (parser, now)
    return parser.can_fetch(user_agent, url)
