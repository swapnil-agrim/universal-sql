"""End-to-end test: parse SQL → entitlements → fetch (mock) → join → mask → return.

Verifies every prototype-relevant axis of the architecture in one query."""
from __future__ import annotations
import pytest

from app.auth import User
from app.catalog import Catalog
from app.connectors.registry import build_default_registry
from app.entitlements import EntitlementEngine
from app.freshness import FreshnessCache
from app.planner import Planner
from app.rate_limit import BudgetConfig, HierarchicalRateLimiter


@pytest.fixture
def planner():
    registry = build_default_registry()
    cat = Catalog(registry)
    ents = EntitlementEngine("policies/default.yaml")
    rl = HierarchicalRateLimiter({
        "github": BudgetConfig(1000, 1000, 1000),
        "jira": BudgetConfig(1000, 1000, 1000),
    })
    return Planner(cat, registry, ents, rl, FreshnessCache())


@pytest.mark.asyncio
async def test_cross_app_join_with_entitlements_and_mask(planner):
    user = User(id="bob", tenant="acme", roles=["engineer"], attrs={"allowed_repos": ["acme/api"]})
    sql = """
    SELECT pr.number, pr.title, pr.repo,
           jira.key, jira.status, jira.assignee
    FROM   github.pull_requests AS pr
    JOIN   jira.issues          AS jira ON jira.key = pr.linked_issue_key
    WHERE  pr.repo = 'acme/api'
    LIMIT  20
    """
    resp = await planner.execute(sql, user, max_staleness_seconds=300)

    # Pushdown + RLS: every row is from acme/api (Bob's only allowed repo)
    assert all(r["repo"] == "acme/api" for r in resp.rows)
    # CLS: bob is not a manager → assignee redacted
    assert all(r["assignee"] == "[REDACTED]" for r in resp.rows)
    # Trace + freshness metadata present
    assert resp.trace_id and len(resp.trace_id) >= 16
    assert resp.cache_status == {"github.pull_requests": "miss", "jira.issues": "miss"}
    assert resp.rows_per_source["github.pull_requests"] > 0
    assert resp.rows_per_source["jira.issues"] > 0


@pytest.mark.asyncio
async def test_cache_hit_on_repeat_query(planner):
    user = User(id="alice", tenant="acme", roles=["engineer"],
                attrs={"allowed_repos": ["acme/api", "acme/web"]})
    sql = "SELECT pr.number, pr.title FROM github.pull_requests AS pr WHERE pr.repo = 'acme/api' LIMIT 5"

    first = await planner.execute(sql, user, max_staleness_seconds=300)
    second = await planner.execute(sql, user, max_staleness_seconds=300)

    assert first.cache_status["github.pull_requests"] == "miss"
    assert second.cache_status["github.pull_requests"] == "hit"
    assert second.freshness_ms >= 0


@pytest.mark.asyncio
async def test_manager_sees_assignee_unmasked(planner):
    mgr = User(id="manager", tenant="acme", roles=["engineer", "manager"],
               attrs={"allowed_repos": ["acme/api", "acme/web"]})
    sql = "SELECT j.key, j.assignee FROM jira.issues AS j LIMIT 5"
    resp = await planner.execute(sql, mgr, max_staleness_seconds=300)
    assert all(r["assignee"] != "[REDACTED]" for r in resp.rows)


@pytest.mark.asyncio
async def test_slow_source_returns_partial(planner, monkeypatch):
    """Source that exceeds the per-query timeout → partial=true; other source's
    rows still flow through. Honours FR: 'timeouts and partial results for
    slow sources'."""
    import asyncio
    from app.connectors.github_mock import GitHubMockConnector

    async def slow_fetch(self, spec, etag=None):
        await asyncio.sleep(5)  # well past the 0.1s budget below
        raise RuntimeError("should never reach here")

    monkeypatch.setattr(GitHubMockConnector, "fetch", slow_fetch)

    user = User(id="alice", tenant="acme", roles=["engineer"],
                attrs={"allowed_repos": ["acme/api", "acme/web"]})
    sql = ("SELECT pr.number, pr.title, jira.key "
           "FROM github.pull_requests AS pr "
           "JOIN jira.issues AS jira ON jira.key = pr.linked_issue_key "
           "LIMIT 5")
    resp = await planner.execute(sql, user, max_staleness_seconds=300, timeout_seconds=0.1)

    # Partial flag set, GitHub identified as the slow side, response still 200-OK shape
    assert resp.partial is True
    assert resp.partial_sources == ["github.pull_requests"]
    assert resp.cache_status["github.pull_requests"] == "timeout"
    # Jira side completed normally
    assert resp.cache_status["jira.issues"] in {"hit", "miss"}
    # No rows from the join because the GitHub side returned 0 rows on timeout
    assert resp.rows == []
