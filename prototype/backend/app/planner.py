"""Query planner.

Pipeline (sync path, in-memory join only — DuckDB/ClickHouse modes are roadmap):
  1. Parse SQL with sqlglot
  2. Validate against catalog
  3. Apply entitlements (RLS predicates merge in; CLS masks recorded)
  4. Push down predicates per source (capability-aware)
  5. Acquire rate-limit budget per source
  6. Check freshness cache; fall back to live fetch
  7. Execute join in memory
  8. Apply CLS masks → project → limit
  9. Return rows + metadata (freshness_ms, rate_limit_status, trace_id)
"""
from __future__ import annotations
import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import sqlglot
from sqlglot import exp
from opentelemetry import trace

from .catalog import Catalog
from .connectors.base import FetchSpec, Predicate
from .connectors.registry import ConnectorRegistry
from .entitlements import ColumnMask, EntitlementEngine
from .errors import InvalidQuery, RateLimitExhausted
from .freshness import FreshnessCache
from .observability import CONNECTOR_REQUEST_DURATION, RATE_LIMIT_REJECTIONS, tracer
from .rate_limit import HierarchicalRateLimiter


@dataclass
class TableRef:
    name: str
    alias: str
    predicates: List[Predicate] = field(default_factory=list)


@dataclass
class JoinSpec:
    """Normalised: from_column belongs to plan.tables[0] (FROM side),
    join_column to plan.tables[1] (JOIN side). Independent of the order
    the user wrote the ON clause."""
    from_column: str
    join_column: str


@dataclass
class Plan:
    tables: List[TableRef]
    join: Optional[JoinSpec]
    projection: List[Tuple[str, str]]  # (qualified_name, output_alias)
    limit: Optional[int]


@dataclass
class QueryResponse:
    rows: List[dict]
    columns: List[str]
    freshness_ms: int
    rate_limit_status: str
    trace_id: str
    cache_status: Dict[str, str]      # table -> hit|miss|timeout
    rows_per_source: Dict[str, int]   # table -> raw row count after pushdown
    partial: bool = False             # true if any source timed out
    partial_sources: List[str] = field(default_factory=list)


class Planner:
    def __init__(
        self,
        catalog: Catalog,
        registry: ConnectorRegistry,
        entitlements: EntitlementEngine,
        rate_limiter: HierarchicalRateLimiter,
        freshness: FreshnessCache,
    ) -> None:
        self.catalog = catalog
        self.registry = registry
        self.entitlements = entitlements
        self.rate_limiter = rate_limiter
        self.freshness = freshness

    # ---------------- public entry point ----------------
    async def execute(
        self,
        sql: str,
        user,
        max_staleness_seconds: int,
        timeout_seconds: float = 30.0,
    ) -> QueryResponse:
        """Execute a query.

        timeout_seconds applies per source-fetch — sources that exceed it return
        empty rows and the response carries `partial=true` with `partial_sources`
        listing which sources timed out. This honours the FR for "timeouts and
        partial results for slow sources".
        """
        with tracer().start_as_current_span("planner.execute") as span:
            trace_id = self._trace_id(span)
            span.set_attribute("user.id", user.id)
            span.set_attribute("user.tenant", user.tenant)
            span.set_attribute("query.timeout_seconds", timeout_seconds)

            plan = self._parse(sql)
            self._validate(plan, user)
            self._apply_rls(plan, user)

            # Fan out to sources in parallel; per-source deadlines so one slow
            # source doesn't drag the whole query.
            with tracer().start_as_current_span("planner.fetch_all"):
                fetch_tasks = [
                    self._fetch_table_with_timeout(t, user, max_staleness_seconds, timeout_seconds)
                    for t in plan.tables
                ]
                fetched = await asyncio.gather(*fetch_tasks)

            cache_status = {t.name: status for t, (_, _, status) in zip(plan.tables, fetched)}
            rows_per_source = {t.name: len(rows) for t, (rows, _, _) in zip(plan.tables, fetched)}
            max_age_ms = max(age for _, age, _ in fetched) if fetched else 0

            partial_sources = [t.name for t, (_, _, status) in zip(plan.tables, fetched) if status == "timeout"]
            partial = len(partial_sources) > 0
            if partial:
                span.set_attribute("query.partial", True)
                span.set_attribute("query.partial_sources", ",".join(partial_sources))

            # Join (in-memory hash join) or single-source pass-through.
            # If a side returned 0 rows due to timeout, the join naturally yields
            # 0 joined rows — best-effort partial result.
            if plan.join:
                joined = self._hash_join(plan, fetched)
            else:
                joined = list(fetched[0][0])

            # CLS masks
            joined = self._apply_cls(plan, joined, user)

            # Projection + limit
            joined = self._project(plan, joined)
            if plan.limit is not None:
                joined = joined[: plan.limit]

            return QueryResponse(
                rows=joined,
                columns=[alias for _, alias in plan.projection],
                freshness_ms=int(max_age_ms),
                rate_limit_status="ok",
                trace_id=trace_id,
                cache_status=cache_status,
                rows_per_source=rows_per_source,
                partial=partial,
                partial_sources=partial_sources,
            )

    async def _fetch_table_with_timeout(
        self,
        table: "TableRef",
        user,
        max_staleness_seconds: int,
        timeout_seconds: float,
    ) -> Tuple[List[dict], int, str]:
        """Wrap _fetch_table with a per-source deadline.

        On timeout: return empty rows, age=0, status='timeout'. The query
        still succeeds with `partial=true` set on the response.
        """
        try:
            return await asyncio.wait_for(
                self._fetch_table(table, user, max_staleness_seconds),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Span attributes for diagnostics
            span = trace.get_current_span()
            span.set_attribute("source.timeout", True)
            span.set_attribute("source.table", table.name)
            return [], 0, "timeout"

    # ---------------- parsing ----------------
    def _parse(self, sql: str) -> Plan:
        try:
            ast = sqlglot.parse_one(sql, dialect="postgres")
        except Exception as e:
            raise InvalidQuery(f"Could not parse SQL: {e}")
        if not isinstance(ast, exp.Select):
            raise InvalidQuery("Only SELECT statements are supported")

        # FROM + optional JOIN. sqlglot exposes the first FROM table via .this;
        # comma-separated extras (not supported here) live in .expressions.
        from_expr = ast.args.get("from")
        if not from_expr:
            raise InvalidQuery("FROM clause required")
        primary = from_expr.this
        primary_table, primary_alias = self._extract_table(primary)

        joins = ast.args.get("joins") or []
        join_spec: Optional[JoinSpec] = None
        join_table: Optional[Tuple[str, str]] = None
        if joins:
            if len(joins) > 1:
                raise InvalidQuery("Only one JOIN is supported in the prototype")
            j = joins[0]
            join_table = self._extract_table(j.this)
            on_expr = j.args.get("on")
            if on_expr is None or not isinstance(on_expr, exp.EQ):
                raise InvalidQuery("JOIN must have an ON clause of the form a.x = b.y")
            tbl_pairs = [(primary_table, primary_alias), join_table]
            left_tbl = self._resolve_alias(on_expr.this, tbl_pairs)
            right_tbl = self._resolve_alias(on_expr.expression, tbl_pairs)
            # Normalise: from_column on FROM side, join_column on JOIN side
            if left_tbl == primary_table:
                from_col, join_col = on_expr.this.name, on_expr.expression.name
            else:
                from_col, join_col = on_expr.expression.name, on_expr.this.name
            join_spec = JoinSpec(from_column=from_col, join_column=join_col)

        tables: List[TableRef] = [TableRef(name=primary_table, alias=primary_alias)]
        if join_table:
            tables.append(TableRef(name=join_table[0], alias=join_table[1]))

        # WHERE → predicates per source
        where = ast.args.get("where")
        if where is not None:
            self._extract_predicates(where.this, tables)

        # SELECT projection
        projection: List[Tuple[str, str]] = []
        for sel in ast.expressions:
            qualified, output = self._extract_projection(sel, tables)
            projection.append((qualified, output))

        # LIMIT
        limit_expr = ast.args.get("limit")
        limit_val = int(limit_expr.expression.this) if limit_expr is not None else None

        return Plan(tables=tables, join=join_spec, projection=projection, limit=limit_val)

    @staticmethod
    def _extract_table(node: exp.Expression) -> Tuple[str, str]:
        if isinstance(node, exp.Table):
            db = node.args.get("db")
            name = f"{db.name}.{node.name}" if db else node.name
            alias = node.alias or node.name
            return name, alias
        # Handle aliased subquery wrapper
        if hasattr(node, "this") and isinstance(node.this, exp.Table):
            return Planner._extract_table(node.this)
        raise InvalidQuery(f"Unsupported FROM expression: {node}")

    @staticmethod
    def _resolve_alias(col_expr: exp.Expression, tables: List[Tuple[str, str]]) -> str:
        # tables is a list of (table_name, alias)
        if isinstance(col_expr, exp.Column):
            tbl_alias = col_expr.table
            for name, alias in tables:
                if alias == tbl_alias or name.endswith("." + tbl_alias) or name == tbl_alias:
                    return name
        raise InvalidQuery(f"Could not resolve column reference: {col_expr}")

    def _extract_predicates(self, node: exp.Expression, tables: List[TableRef]) -> None:
        """Walk a WHERE expression, splitting on AND, attaching predicates to tables."""
        if isinstance(node, exp.And):
            self._extract_predicates(node.this, tables)
            self._extract_predicates(node.expression, tables)
            return

        op_map = {
            exp.EQ: "=", exp.NEQ: "!=",
            exp.GT: ">", exp.LT: "<",
            exp.GTE: ">=", exp.LTE: "<=",
            exp.Like: "LIKE",
        }
        if isinstance(node, exp.In):
            col = node.this
            values = [self._literal(v) for v in node.expressions]
            tbl, column = self._resolve_column(col, tables)
            tbl.predicates.append(Predicate(column=column, op="IN", value=values))
            return

        for cls, op in op_map.items():
            if isinstance(node, cls):
                col = node.this
                lit = node.expression
                tbl, column = self._resolve_column(col, tables)
                tbl.predicates.append(Predicate(column=column, op=op, value=self._literal(lit)))
                return

        raise InvalidQuery(f"Unsupported WHERE clause fragment: {node}")

    @staticmethod
    def _resolve_column(col: exp.Expression, tables: List[TableRef]) -> Tuple[TableRef, str]:
        if not isinstance(col, exp.Column):
            raise InvalidQuery(f"Column reference required: {col}")
        alias = col.table
        if not alias:
            # No table qualifier — only valid for single-table queries
            if len(tables) != 1:
                raise InvalidQuery(f"Column {col.name} must be qualified with a table alias")
            return tables[0], col.name
        for tbl in tables:
            if tbl.alias == alias or tbl.name == alias or tbl.name.endswith("." + alias):
                return tbl, col.name
        raise InvalidQuery(f"Unknown table alias '{alias}'")

    @staticmethod
    def _literal(node: exp.Expression) -> Any:
        if isinstance(node, exp.Literal):
            if node.is_string:
                return node.this
            try:
                if "." in node.this:
                    return float(node.this)
                return int(node.this)
            except ValueError:
                return node.this
        if isinstance(node, exp.Boolean):
            return node.this
        if isinstance(node, exp.Null):
            return None
        return node.sql()

    def _extract_projection(self, sel: exp.Expression, tables: List[TableRef]) -> Tuple[str, str]:
        # Handle aliased select (foo AS bar)
        if isinstance(sel, exp.Alias):
            inner = sel.this
            output = sel.alias
        else:
            inner = sel
            output = sel.alias_or_name
        if isinstance(inner, exp.Column):
            tbl, column = self._resolve_column(inner, tables)
            return f"{tbl.alias}.{column}", output or column
        raise InvalidQuery(f"Only simple column projections are supported: {sel}")

    # ---------------- validation + entitlements ----------------
    def _validate(self, plan: Plan, user) -> None:
        for t in plan.tables:
            if not self.catalog.has_table(t.name):
                raise InvalidQuery(f"Unknown table {t.name}")
            self.entitlements.assert_table_allowed(user.tenant, t.name)

    def _apply_rls(self, plan: Plan, user) -> None:
        for t in plan.tables:
            t.predicates.extend(self.entitlements.rls_predicates_for(user, t.name))

    # ---------------- per-table fetch with rate-limit + freshness ----------------
    async def _fetch_table(self, table: TableRef, user, max_staleness_seconds: int) -> Tuple[List[dict], int, str]:
        connector = self.registry.get(table.name)
        spec = FetchSpec(
            columns=self.catalog.table_columns(table.name),
            predicates=table.predicates,
            limit=None,
        )

        cache_key = self._cache_key(user.tenant, table.name, spec)

        # Cache check
        cached = await self.freshness.get(cache_key, max_staleness_seconds)
        if cached is not None:
            age_ms = int((time.time() - cached.fetched_at) * 1000)
            CONNECTOR_REQUEST_DURATION.labels(
                connector=connector.name, tenant=user.tenant, cache_status="hit"
            ).observe(0.0)
            return cached.rows, age_ms, "hit"

        # Rate-limit acquire
        ok, scope, retry_after = await self.rate_limiter.acquire(connector.name, user.tenant, user.id)
        if not ok:
            RATE_LIMIT_REJECTIONS.labels(connector=connector.name, scope=scope).inc()
            raise RateLimitExhausted(
                f"Rate limit exhausted at {scope} scope for connector '{connector.name}'",
                retry_after=retry_after,
                details={"scope": scope, "connector": connector.name},
            )

        # Live fetch (instrumented)
        with tracer().start_as_current_span(f"connector.{connector.name}.fetch") as span:
            span.set_attribute("connector.name", connector.name)
            span.set_attribute("predicates.count", len(spec.predicates))
            start = time.monotonic()
            result = await connector.fetch(spec)
            duration = time.monotonic() - start
            span.set_attribute("rows.count", len(result.rows))
            CONNECTOR_REQUEST_DURATION.labels(
                connector=connector.name, tenant=user.tenant, cache_status="miss"
            ).observe(duration)

        await self.freshness.put(cache_key, result.rows, result.etag)
        return result.rows, 0, "miss"

    @staticmethod
    def _cache_key(tenant: str, table: str, spec: FetchSpec) -> str:
        # Tenant-scoped key so cache leakage is structurally impossible
        digest = hashlib.sha256(repr((tenant, table, [(p.column, p.op, p.value) for p in spec.predicates])).encode()).hexdigest()
        return f"{tenant}::{table}::{digest[:16]}"

    # ---------------- join + project + mask ----------------
    def _hash_join(self, plan: Plan, fetched: List[Tuple[List[dict], int, str]]) -> List[dict]:
        assert plan.join is not None
        from_alias = plan.tables[0].alias
        join_alias = plan.tables[1].alias
        from_rows = fetched[0][0]
        join_rows = fetched[1][0]

        from_col = plan.join.from_column
        join_col = plan.join.join_column

        # Hash the JOIN side (production: hash the smaller side; we'd consult cardinality estimator)
        index: Dict[Any, List[dict]] = {}
        for r in join_rows:
            key = r.get(join_col)
            if key is None:
                continue
            index.setdefault(key, []).append(r)

        out: List[dict] = []
        for l in from_rows:
            key = l.get(from_col)
            if key is None:
                continue
            for r in index.get(key, []):
                merged = {f"{from_alias}.{k}": v for k, v in l.items()}
                merged.update({f"{join_alias}.{k}": v for k, v in r.items()})
                out.append(merged)
        return out

    def _apply_cls(self, plan: Plan, rows: List[dict], user) -> List[dict]:
        if not rows:
            return rows
        # Collect masks per alias
        masks_by_alias: Dict[str, List[ColumnMask]] = {}
        for tref in plan.tables:
            masks = self.entitlements.cls_masks_for(user, tref.name)
            if masks:
                masks_by_alias[tref.alias] = masks

        if not masks_by_alias:
            return rows

        # Detect join vs single-source row shape
        is_joined = plan.join is not None
        for r in rows:
            for alias, masks in masks_by_alias.items():
                for m in masks:
                    if is_joined:
                        k = f"{alias}.{m.column}"
                        if k in r:
                            r[k] = m.apply(r[k])
                    else:
                        if m.column in r:
                            r[m.column] = m.apply(r[m.column])
        return rows

    def _project(self, plan: Plan, rows: List[dict]) -> List[dict]:
        out: List[dict] = []
        is_joined = plan.join is not None
        for r in rows:
            projected = {}
            for qualified, alias in plan.projection:
                if is_joined:
                    projected[alias] = r.get(qualified)
                else:
                    # Single-source: strip alias prefix
                    _, col = qualified.split(".", 1)
                    projected[alias] = r.get(col)
            out.append(projected)
        return out

    @staticmethod
    def _trace_id(span) -> str:
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return f"{ctx.trace_id:032x}"
        return uuid.uuid4().hex
