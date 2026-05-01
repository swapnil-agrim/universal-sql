"""Connector contract — the seam between the planner and external SaaS sources.

Every connector ships a CapabilityDescriptor (what it can push down, page sizes,
expected latency, rate-limit budget) and a fetch() coroutine that returns
normalized rows. The planner uses the descriptor for pushdown decisions and
join ordering — no source-specific code in the planner.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, Set, Tuple


@dataclass(frozen=True)
class Predicate:
    column: str
    op: str          # =, !=, >, <, >=, <=, IN, LIKE
    value: Any

    def matches(self, row: dict) -> bool:
        v = row.get(self.column)
        if self.op == "=":
            return v == self.value
        if self.op == "!=":
            return v != self.value
        if self.op == ">":
            return v is not None and v > self.value
        if self.op == "<":
            return v is not None and v < self.value
        if self.op == ">=":
            return v is not None and v >= self.value
        if self.op == "<=":
            return v is not None and v <= self.value
        if self.op == "IN":
            return v in self.value
        if self.op == "LIKE":
            if v is None:
                return False
            pattern = str(self.value).replace("%", "")
            return pattern in str(v)
        return False


@dataclass
class FetchSpec:
    columns: List[str]
    predicates: List[Predicate]
    limit: Optional[int] = None
    order_by: Optional[Tuple[str, str]] = None  # (column, ASC|DESC)


@dataclass
class CapabilityDescriptor:
    table_name: str
    columns: List[str]
    pushable_predicates: Set[str]   # columns that can be pushed down server-side
    join_keys: List[str]
    max_page_size: int
    estimated_p99_ms: int
    rate_limit_per_minute: int


@dataclass
class FetchResult:
    rows: List[dict]
    etag: Optional[str]
    latency_ms: float


class Connector(Protocol):
    name: str
    capability: CapabilityDescriptor

    async def fetch(self, spec: FetchSpec, etag: Optional[str] = None) -> FetchResult:
        ...
