"""Email sending rate limiter."""

import asyncio
import time
from collections import defaultdict

from ..config import settings


class EmailRateLimiter:
    """Rate limiter for email sending with per-domain and global limits."""

    def __init__(self):
        self._domain_timestamps: dict[str, list[float]] = defaultdict(list)
        self._global_timestamps: list[float] = []
        self._lock = asyncio.Lock()
        self._per_minute = settings.email_rate_per_minute
        self._per_hour = settings.email_rate_per_hour

    async def acquire(self, recipient_domain: str) -> float:
        """Wait until sending is allowed. Returns wait time in seconds."""
        async with self._lock:
            now = time.monotonic()
            wait_time = 0.0

            # Check per-domain limit (per minute)
            domain_times = self._domain_timestamps[recipient_domain]
            domain_times = [t for t in domain_times if now - t < 60]
            self._domain_timestamps[recipient_domain] = domain_times

            if len(domain_times) >= self._per_minute:
                oldest = domain_times[0]
                wait_time = max(wait_time, 60 - (now - oldest) + 0.1)

            # Check global hourly limit
            self._global_timestamps = [t for t in self._global_timestamps if now - t < 3600]

            if len(self._global_timestamps) >= self._per_hour:
                oldest = self._global_timestamps[0]
                wait_time = max(wait_time, 3600 - (now - oldest) + 0.1)

            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = time.monotonic()

            self._domain_timestamps[recipient_domain].append(now)
            self._global_timestamps.append(now)

            return wait_time

    def get_stats(self) -> dict:
        """Get current rate limiter stats."""
        now = time.monotonic()
        recent_global = [t for t in self._global_timestamps if now - t < 3600]
        return {
            "emails_last_hour": len(recent_global),
            "hourly_limit": self._per_hour,
            "per_minute_limit": self._per_minute,
            "domains_active": len(self._domain_timestamps),
        }


# Global instance
rate_limiter = EmailRateLimiter()
