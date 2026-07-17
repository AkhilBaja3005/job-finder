"""
Thread-safe TTL cache with bounded size, shared by every in-memory cache in
main.py. Without a size cap, a cache that only expires entries lazily (on read
or on write) can still grow without bound if it's written far more often than
it's read with the same key — exactly what happened with the job-search cache,
which was never pruned at all.
"""

import threading
import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: float, max_size: int = 1000):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._store: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _prune_expired(self, now: float) -> None:
        expired = [k for k, (ts, _) in self._store.items() if now - ts >= self._ttl]
        for k in expired:
            self._store.pop(k, None)

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, value = entry
            if time.time() - ts >= self._ttl:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            now = time.time()
            self._prune_expired(now)
            # If still at/over capacity after pruning expired entries, evict
            # the oldest entries (by insertion/last-write order) until there's
            # room, so a burst of distinct keys can't grow the cache forever.
            if len(self._store) >= self._max_size:
                oldest_keys = sorted(self._store.keys(), key=lambda k: self._store[k][0])
                for k in oldest_keys[: len(self._store) - self._max_size + 1]:
                    self._store.pop(k, None)
            self._store[key] = (now, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
