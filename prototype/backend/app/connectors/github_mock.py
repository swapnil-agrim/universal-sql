"""Mock GitHub connector — deterministic fixture data for tests and load runs."""
from __future__ import annotations
import asyncio
import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .base import CapabilityDescriptor, Connector, FetchResult, FetchSpec


def _seed_prs(seed: int = 42) -> List[dict]:
    """Generate 200 deterministic PRs across two repos."""
    rng = random.Random(seed)
    repos = ["acme/api", "acme/web"]
    authors = ["alice", "bob", "carol", "dave", "erin"]
    issue_keys = [f"PROJ-{n}" for n in range(100, 220)]
    base_time = datetime(2026, 4, 1, tzinfo=timezone.utc)

    prs = []
    for i in range(1, 201):
        repo = rng.choice(repos)
        author = rng.choice(authors)
        merged_offset_minutes = rng.randint(0, 60 * 24 * 30)
        merged_at = base_time + timedelta(minutes=merged_offset_minutes)
        # Most PRs reference exactly one issue; some reference none
        linked = rng.choice(issue_keys + [None] * 5)
        prs.append({
            "number": i,
            "title": f"{linked or 'misc'}: {rng.choice(['fix', 'feat', 'chore'])} change #{i}",
            "repo": repo,
            "author": author,
            "author_email": f"{author}@acme.example",
            "merged_at": merged_at.isoformat(),
            "linked_issue_key": linked,
        })
    return prs


_PRS = _seed_prs()


class GitHubMockConnector:
    name = "github"
    capability = CapabilityDescriptor(
        table_name="github.pull_requests",
        columns=["number", "title", "repo", "author", "author_email", "merged_at", "linked_issue_key"],
        pushable_predicates={"repo", "author", "merged_at", "linked_issue_key"},
        join_keys=["linked_issue_key"],
        max_page_size=100,
        estimated_p99_ms=600,
        rate_limit_per_minute=300,  # mock budget; live would be 5000/h
    )

    async def fetch(self, spec: FetchSpec, etag: Optional[str] = None) -> FetchResult:
        start = time.monotonic()
        # Simulate realistic source latency so traces show meaningful spans
        await asyncio.sleep(0.02)

        # Server-side filtering for pushable predicates
        pushable = self.capability.pushable_predicates
        rows = list(_PRS)
        for p in spec.predicates:
            if p.column in pushable:
                rows = [r for r in rows if p.matches(r)]

        # Sort
        if spec.order_by:
            col, direction = spec.order_by
            rows.sort(key=lambda r: r.get(col) or "", reverse=(direction.upper() == "DESC"))

        # Limit
        if spec.limit:
            rows = rows[: spec.limit]

        # ETag — content-addressable so cache validation works
        digest = hashlib.sha1(repr(rows).encode()).hexdigest()
        latency_ms = (time.monotonic() - start) * 1000.0
        return FetchResult(rows=rows, etag=digest, latency_ms=latency_ms)
