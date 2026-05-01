"""Rate-limit governance tests."""
from __future__ import annotations
import pytest

from app.auth import User
from app.catalog import Catalog
from app.connectors.registry import build_default_registry
from app.entitlements import EntitlementEngine
from app.errors import RateLimitExhausted
from app.freshness import FreshnessCache
from app.planner import Planner
from app.rate_limit import BudgetConfig, HierarchicalRateLimiter, TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_grants_then_denies():
    bucket = TokenBucket(capacity=2, refill_per_sec=0.0)
    ok1, _ = await bucket.try_acquire()
    ok2, _ = await bucket.try_acquire()
    ok3, retry = await bucket.try_acquire()
    assert ok1 and ok2
    assert not ok3
    # With zero refill, retry_after is infinite — sentinel
    assert retry == float("inf")


@pytest.mark.asyncio
async def test_user_scope_exhausted_returns_friendly_error():
    """User bucket of 1 → second query in same tenant from same user should reject."""
    registry = build_default_registry()
    cat = Catalog(registry)
    ents = EntitlementEngine("policies/default.yaml")
    rl = HierarchicalRateLimiter({
        "github": BudgetConfig(global_per_minute=1000, tenant_per_minute=1000, user_per_minute=1),
        "jira": BudgetConfig(global_per_minute=1000, tenant_per_minute=1000, user_per_minute=1000),
    })
    planner = Planner(cat, registry, ents, rl, FreshnessCache())
    user = User(id="alice", tenant="acme", roles=["engineer"],
                attrs={"allowed_repos": ["acme/api", "acme/web"]})

    sql_a = "SELECT pr.number FROM github.pull_requests AS pr WHERE pr.repo = 'acme/api' LIMIT 1"
    sql_b = "SELECT pr.number FROM github.pull_requests AS pr WHERE pr.repo = 'acme/web' LIMIT 1"

    # First query consumes the only github user-token. Different predicate -> different cache key,
    # forcing the second query to attempt a live fetch and hit the limit.
    await planner.execute(sql_a, user, max_staleness_seconds=300)
    with pytest.raises(RateLimitExhausted) as exc:
        await planner.execute(sql_b, user, max_staleness_seconds=300)
    err = exc.value
    assert err.code == "RATE_LIMIT_EXHAUSTED"
    assert err.retry_after is not None and err.retry_after > 0
    assert err.details["scope"] == "user"
