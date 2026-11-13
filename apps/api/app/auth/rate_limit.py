"""A small in-process sliding-window rate limiter.

Suitable for a single API instance. With several instances each keeps its own count, so the
effective limit is per instance.
"""

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int = 1) -> tuple[bool, float]:
        """Return (allowed, seconds until a request would be allowed)."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) + cost > self.limit:
                retry = self.window_s - (now - hits[0]) if hits else self.window_s
                return False, max(retry, 0.0)
            hits.extend([now] * cost)
            if len(self._hits) > 10_000:  # forget keys that have gone quiet
                for stale in [
                    k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s
                ]:
                    del self._hits[stale]
            return True, 0.0
