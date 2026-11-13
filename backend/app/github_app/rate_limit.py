"""A simple in-memory token bucket, one per installation. Good enough for a single
process; not shared across workers/replicas (see README limitations)."""

import threading
import time
from typing import Protocol


class _Clock(Protocol):
    def now(self) -> float: ...


class _SystemClock:
    def now(self) -> float:
        return time.monotonic()


class TokenBucket:
    def __init__(self, capacity: float, refill_per_second: float, clock: _Clock | None = None) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._clock = clock or _SystemClock()
        self._tokens = capacity
        self._last_refill = self._clock.now()
        self._lock = threading.Lock()

    def try_acquire(self, cost: float = 1.0) -> bool:
        with self._lock:
            now = self._clock.now()
            elapsed = max(0.0, now - self._last_refill)
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
            self._last_refill = now
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False


class InstallationRateLimiter:
    """One TokenBucket per installation_id, created lazily on first use."""

    def __init__(self, capacity: float, refill_per_minute: float, clock: _Clock | None = None) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_minute / 60.0
        self._clock = clock
        self._buckets: dict[int, TokenBucket] = {}
        self._guard = threading.Lock()

    def allow(self, installation_id: int) -> bool:
        with self._guard:
            bucket = self._buckets.get(installation_id)
            if bucket is None:
                bucket = TokenBucket(self._capacity, self._refill_per_second, clock=self._clock)
                self._buckets[installation_id] = bucket
        return bucket.try_acquire()
