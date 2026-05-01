"""Mock Jira connector — deterministic fixture data."""
from __future__ import annotations
import asyncio
import hashlib
import random
import time
from typing import List, Optional

from .base import CapabilityDescriptor, FetchResult, FetchSpec


def _seed_issues(seed: int = 7) -> List[dict]:
    rng = random.Random(seed)
    statuses = ["To Do", "In Progress", "In Review", "Done"]
    assignees = ["alice", "bob", "carol", "dave", "erin", "frank"]
    issues = []
    for n in range(100, 220):
        issues.append({
            "key": f"PROJ-{n}",
            "status": rng.choice(statuses),
            "assignee": rng.choice(assignees),
            "summary": f"Issue PROJ-{n}: {rng.choice(['login', 'search', 'billing', 'auth', 'ui'])} work",
        })
    return issues


_ISSUES = _seed_issues()


class JiraMockConnector:
    name = "jira"
    capability = CapabilityDescriptor(
        table_name="jira.issues",
        columns=["key", "status", "assignee", "summary"],
        pushable_predicates={"key", "status", "assignee"},
        join_keys=["key"],
        max_page_size=100,
        estimated_p99_ms=400,
        rate_limit_per_minute=300,
    )

    async def fetch(self, spec: FetchSpec, etag: Optional[str] = None) -> FetchResult:
        start = time.monotonic()
        await asyncio.sleep(0.015)

        pushable = self.capability.pushable_predicates
        rows = list(_ISSUES)
        for p in spec.predicates:
            if p.column in pushable:
                rows = [r for r in rows if p.matches(r)]

        if spec.order_by:
            col, direction = spec.order_by
            rows.sort(key=lambda r: r.get(col) or "", reverse=(direction.upper() == "DESC"))

        if spec.limit:
            rows = rows[: spec.limit]

        digest = hashlib.sha1(repr(rows).encode()).hexdigest()
        latency_ms = (time.monotonic() - start) * 1000.0
        return FetchResult(rows=rows, etag=digest, latency_ms=latency_ms)
