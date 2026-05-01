"""Hierarchical token-bucket rate limiter.

Three nested buckets per connector: connector-global → tenant → user.
A request must acquire all three; the first that fails determines the
retry-after. Production: Redis + Lua for atomicity. Prototype: in-process
asyncio locks (single-process semantics; horizontally scaling requires Redis).
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Tuple


class TokenBucket:
    __slots__ = ("capacity", "tokens", "refill_per_sec", "last_refill", "_lock")

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_per_sec = refill_per_sec
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        self.last_refill = now

    async def try_acquire(self, n: int = 1) -> Tuple[bool, float]:
        """Returns (granted, retry_after_seconds)."""
        async with self._lock:
            self._refill()
            if self.tokens >= n:
                self.tokens -= n
                return True, 0.0
            shortfall = n - self.tokens
            retry_after = shortfall / self.refill_per_sec if self.refill_per_sec > 0 else float("inf")
            return False, retry_after


@dataclass(frozen=True)
class BudgetConfig:
    global_per_minute: int
    tenant_per_minute: int
    user_per_minute: int


class HierarchicalRateLimiter:
    def __init__(self, configs: Dict[str, BudgetConfig]) -> None:
        self._configs = configs
        self._global: Dict[str, TokenBucket] = {}
        self._tenant: Dict[Tuple[str, str], TokenBucket] = {}
        self._user: Dict[Tuple[str, str, str], TokenBucket] = {}

    def _global_bucket(self, connector: str) -> TokenBucket:
        if connector not in self._global:
            cfg = self._configs[connector]
            self._global[connector] = TokenBucket(cfg.global_per_minute, cfg.global_per_minute / 60.0)
        return self._global[connector]

    def _tenant_bucket(self, connector: str, tenant: str) -> TokenBucket:
        key = (connector, tenant)
        if key not in self._tenant:
            cfg = self._configs[connector]
            self._tenant[key] = TokenBucket(cfg.tenant_per_minute, cfg.tenant_per_minute / 60.0)
        return self._tenant[key]

    def _user_bucket(self, connector: str, tenant: str, user: str) -> TokenBucket:
        key = (connector, tenant, user)
        if key not in self._user:
            cfg = self._configs[connector]
            self._user[key] = TokenBucket(cfg.user_per_minute, cfg.user_per_minute / 60.0)
        return self._user[key]

    async def acquire(self, connector: str, tenant: str, user: str, n: int = 1) -> Tuple[bool, str, float]:
        """
        Acquire one token from each of (global, tenant, user). If any fails,
        returns (False, scope_that_failed, retry_after). On success, all three
        are decremented; on failure, none are.
        """
        # Order matters: check innermost first to fail fast on user-scope abuse.
        u = self._user_bucket(connector, tenant, user)
        t = self._tenant_bucket(connector, tenant)
        g = self._global_bucket(connector)

        # Probe each bucket without consuming, then consume on full pass.
        # We use a coarse approximation: try in order and refund on later failure.
        ok_u, ra_u = await u.try_acquire(n)
        if not ok_u:
            return False, "user", ra_u
        ok_t, ra_t = await t.try_acquire(n)
        if not ok_t:
            await self._refund(u, n)
            return False, "tenant", ra_t
        ok_g, ra_g = await g.try_acquire(n)
        if not ok_g:
            await self._refund(u, n)
            await self._refund(t, n)
            return False, "global", ra_g
        return True, "ok", 0.0

    @staticmethod
    async def _refund(bucket: TokenBucket, n: int) -> None:
        async with bucket._lock:
            bucket.tokens = min(bucket.capacity, bucket.tokens + n)
