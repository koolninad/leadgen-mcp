"""Concurrency and rate-limit primitives."""

import asyncio
import time


class Semaphore:
    """Named semaphore for module-level concurrency control."""

    _instances: dict[str, asyncio.Semaphore] = {}

    @classmethod
    def get(cls, name: str, limit: int) -> asyncio.Semaphore:
        if name not in cls._instances:
            cls._instances[name] = asyncio.Semaphore(limit)
        return cls._instances[name]


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate          # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self._last_refill = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class DomainRateLimiter:
    """Per-domain rate limiter for email sending."""

    def __init__(self, rate_per_minute: float = 2.0):
        self._buckets: dict[str, TokenBucket] = {}
        self._rate = rate_per_minute / 60.0  # convert to per-second

    async def acquire(self, domain: str):
        if domain not in self._buckets:
            self._buckets[domain] = TokenBucket(self._rate, 1.0)
        await self._buckets[domain].acquire()
