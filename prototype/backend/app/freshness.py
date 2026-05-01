"""TTL cache with ETag support — the freshness layer.

A cache hit only counts if the entry's age is within the caller's
`max_staleness_seconds`. Otherwise the planner must re-fetch (subject to
rate limit) and surface freshness_ms in the response.
"""
from __future__ import annotations
import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


@dataclass
class CacheEntry:
    rows: list
    etag: Optional[str]
    fetched_at: float


class FreshnessCache:
    def __init__(self, max_size: int = 1024) -> None:
        self._cache: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str, max_staleness_seconds: int) -> Optional[CacheEntry]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            age = time.time() - entry.fetched_at
            if age > max_staleness_seconds:
                return None
            self._cache.move_to_end(key)
            return entry

    async def put(self, key: str, rows: list, etag: Optional[str]) -> None:
        async with self._lock:
            self._cache[key] = CacheEntry(rows=rows, etag=etag, fetched_at=time.time())
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
