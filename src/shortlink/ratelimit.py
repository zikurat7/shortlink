"""Per-key token-bucket rate limiter.

Each key owns a bucket holding up to `capacity` tokens that refills at `rate`
tokens/second. A request spends one token; no token means rejected. Refill is
computed lazily from elapsed time, so there is no background thread.
"""

import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Dict, Tuple


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    def __init__(
        self,
        rate: float,
        capacity: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self._rate = rate
        self._capacity = capacity
        self._clock = clock
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = Lock()

    def acquire(self, key: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds). retry_after is 0 when allowed."""
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = _Bucket(float(self._capacity), now)
            else:
                elapsed = now - bucket.updated
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate)
                bucket.updated = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0
            return False, math.ceil((1 - bucket.tokens) / self._rate)
