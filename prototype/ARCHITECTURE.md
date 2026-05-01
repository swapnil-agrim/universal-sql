# Prototype Internals — what's in this POC and how it works

> Companion to [`README.md`](README.md). The README tells you how to run
> the prototype; this document tells you how it's wired internally —
> module map, API reference, request lifecycle, and extension points.
>
> System-level design (multi-tenant production) lives in
> [`../design/`](../design/). This file is scoped to the
> ~1,300-line prototype.

---

## 1. What this POC actually contains

A working **M1 vertical slice** of the universal SQL platform —
end-to-end query path with every architectural seam present, but with
the production mechanisms simplified to in-process equivalents.

| Capability | Production component | Prototype mechanism |
|---|---|---|
| HTTP gateway + planner | Separate stateless services | One FastAPI process |
| AuthN | OIDC → JWT verification | `X-User-Id` header → policy YAML lookup |
| AuthZ (RLS/CLS) | OPA / Rego DSL | Embedded YAML + Python evaluator |
| Rate limit (3-tier) | Redis + Lua | In-process asyncio token buckets |
| Freshness | L1 + L2 Redis + L3 ETag | In-process LRU + TTL |
| Connectors | Out-of-process worker pool | In-process `Connector` instances |
| Source data | Real GitHub/Jira APIs | Deterministic mock fixtures |
| Materialisation | DuckDB / ClickHouse (planner-decided) | In-memory hash join only |
| Tracing | OTel → Tempo | OTel → ConsoleSpanExporter (logs) |
| Metrics | Prometheus + Grafana | Same — wired in `docker-compose.yml` |
| Audit | Kafka append-log + S3 object-lock | Trace span attributes (audit-shaped) |

What this proves: every M1 exit criterion in
[`../planning/02-execution-plan.md`](../planning/02-execution-plan.md) minus
per-tenant KMS (deferred to M2).

---

## 2. File map (what to read, in what order)

```
prototype/
├── README.md                         ← run me (quickstart, demos)
├── ARCHITECTURE.md                   ← you are here
├── docker-compose.yml                ← 4 services: backend, frontend, prometheus, grafana
├── .env.example                      ← env knobs (rate-limit budgets, TTL, live-mode tokens)
│
├── backend/                          1,281 LOC of Python
│   ├── Dockerfile                    multi-stage; Python 3.11-slim base
│   ├── requirements.txt              FastAPI 0.115, sqlglot 25, OTel 1.27, pytest 8
│   ├── pytest.ini                    asyncio mode, pythonpath=.
│   │
│   ├── app/
│   │   ├── main.py             128   FastAPI app + /v1/query, /healthz, /metrics, /v1/tables
│   │   ├── settings.py          36   env config (rate-limit budgets, TTL, policy path, live-mode tokens)
│   │   ├── errors.py            52   standard error vocabulary (RATE_LIMIT_EXHAUSTED, ENTITLEMENT_DENIED, ...)
│   │   ├── auth.py              34   X-User-Id → User dependency
│   │   ├── observability.py     71   OTel tracer init + 3 Prometheus metrics
│   │   ├── catalog.py           31   schema lookup over connector descriptors
│   │   ├── entitlements.py     100   YAML policy → RLS predicates / CLS masks
│   │   ├── rate_limit.py       107   3-tier token-bucket implementation
│   │   ├── freshness.py         48   TTL+ETag LRU cache
│   │   ├── planner.py          425   the heart — parse SQL, push down, fetch, join, mask, project
│   │   └── connectors/
│   │       ├── base.py          74   Connector protocol + CapabilityDescriptor + FetchSpec + Predicate
│   │       ├── github_mock.py   80   200 deterministic PR rows; pushdown filtering on 4 columns
│   │       ├── jira_mock.py     61   120 deterministic issue rows; pushdown filtering on 3 columns
│   │       └── registry.py      34   table-name → connector lookup
│   │
│   ├── policies/default.yaml         3 users, 1 tenant, 1 RLS rule, 1 CLS mask
│   └── tests/
│       ├── test_query_e2e.py         cross-app join + RLS + CLS + cache-hit-on-repeat
│       └── test_rate_limit.py        bucket exhaustion + RATE_LIMIT_EXHAUSTED surfaced
│
├── frontend/                         Next.js 14 — thin UI, ~150 LOC of TS
│   ├── Dockerfile                    multi-stage; node:20-alpine
│   ├── app/page.tsx                  the only page that matters: editor + run + results + metadata
│   ├── app/layout.tsx                Tailwind-only layout
│   └── ...                           tsconfig, next.config, tailwind config
│
├── monitoring/
│   ├── prometheus.yml                scrapes backend:8000/metrics every 5s
│   └── grafana/
│       ├── provisioning/             auto-wire datasource + dashboard
│       └── dashboards/universal-sql.json   7-panel pre-built dashboard
│
├── load-test/k6.js                   3 query shapes × 3 users at 700 RPS for 60s
└── evidence/                         captured artifacts from a real run
    ├── grafana-dashboard.png         mid-load
    ├── grafana-dashboard-final.png   post-run, full envelope
    ├── load-test-results.md          headline numbers
    ├── k6-summary.txt                raw output
    ├── otel-trace-sample.txt         one trace, three spans, shared trace_id
    ├── sample-metrics.txt            /metrics excerpt
    └── sample-query-response.json    one full POST /v1/query response
```

---

## 3. Component diagram (prototype-scoped)

```
                  Browser (Next.js page.tsx)
                          │
                          │  fetch('/v1/query',
                          │   { headers: { 'X-User-Id': 'alice' },
                          │     body: { sql, max_staleness_seconds } })
                          ▼
       ┌─────────────────────────────────────────────────────┐
       │              FastAPI app  (main.py)                 │
       │                                                     │
       │  CORS  →  auth.get_current_user (X-User-Id lookup)  │
       │       →  Planner.execute()                          │
       │       →  QueryResponseModel  ←─── HTTP 200          │
       │                                                     │
       │  Side channels:  /healthz   /metrics   /v1/tables   │
       └──────┬─────────────────────────────────────────────┘
              │
              ▼
       ┌──────────────────────────────────────────────────────┐
       │            Planner  (planner.py — 425 LOC)           │
       │                                                      │
       │  1. _parse(sql)            sqlglot AST → Plan        │
       │  2. _validate              catalog + tenant gate     │
       │  3. _apply_rls             entitlements → predicates │
       │  4. _fetch_table  (per source, in parallel)          │
       │       ├─ rate_limit.acquire   (token buckets)        │
       │       ├─ freshness.get        (cache hit?)           │
       │       └─ connector.fetch      (live)                 │
       │  5. _hash_join             in-memory                 │
       │  6. _apply_cls             column masks              │
       │  7. _project + LIMIT       output rows               │
       └──────┬──────────────┬───────────────┬────────────────┘
              │              │               │
              ▼              ▼               ▼
       ┌────────────┐ ┌────────────┐ ┌────────────────────┐
       │EntitlementE│ │ RateLimit  │ │  FreshnessCache    │
       │   ngine    │ │  (token    │ │  (LRU + TTL)       │
       │  (YAML)    │ │  buckets)  │ │                    │
       └────────────┘ └────────────┘ └────────────────────┘
              │
              ▼
       ┌──────────────────────────────────────────────────────┐
       │  ConnectorRegistry  →  github / jira mock instances  │
       │                        (deterministic fixtures)      │
       └──────────────────────────────────────────────────────┘

  Observability cross-cuts every step:
    OTel spans:    planner.execute → planner.fetch_all →
                   connector.{name}.fetch
    Prometheus:    connector_request_duration_seconds (histogram)
                   queries_total (counter)
                   rate_limit_rejections_total (counter)
```

---

## 4. HTTP API reference

Base URL: `http://localhost:8000`. Auth: every non-health endpoint
requires the `X-User-Id` header.

### `GET /healthz`
Liveness check. No auth.
```json
{ "status": "ok" }
```

### `GET /metrics`
Prometheus exposition. No auth. Used by the bundled Prometheus scraper.

### `GET /v1/tables`
Lists tables visible to the calling user's tenant.

```bash
curl -H 'X-User-Id: alice' http://localhost:8000/v1/tables
```

```json
{
  "tables": [
    {
      "name": "github.pull_requests",
      "columns": ["number", "title", "repo", "author", "author_email",
                  "merged_at", "linked_issue_key"],
      "join_keys": ["linked_issue_key"]
    },
    {
      "name": "jira.issues",
      "columns": ["key", "status", "assignee", "summary"],
      "join_keys": ["key"]
    }
  ]
}
```

### `POST /v1/query`
Execute a query.

**Request**
```json
{
  "sql": "SELECT pr.number FROM github.pull_requests AS pr WHERE pr.repo = 'acme/api' LIMIT 5",
  "max_staleness_seconds": 300
}
```

| Field | Type | Constraint | Default |
|---|---|---|---|
| `sql` | string | SELECT subset (see §6) | required |
| `max_staleness_seconds` | int | 0 ≤ x ≤ 3600 | 300 |

**Headers**
| Header | Required | Notes |
|---|---|---|
| `X-User-Id` | yes | one of `alice`, `bob`, `manager` (defined in policy YAML) |
| `Content-Type` | yes | `application/json` |

**Response — 200 OK**
```json
{
  "rows":           [ { "...": "..." }, ... ],
  "columns":        ["number", "title", ...],
  "freshness_ms":   17,
  "rate_limit_status": "ok",
  "trace_id":       "3a8159e28c126b06ef3d393ca9d055a3",
  "cache_status":   { "github.pull_requests": "miss", "jira.issues": "hit" },
  "rows_per_source":{ "github.pull_requests": 50, "jira.issues": 50 }
}
```

| Field | Meaning |
|---|---|
| `rows` | Result rows after RLS filter, CLS mask, projection, and LIMIT |
| `columns` | Output column aliases in projection order |
| `freshness_ms` | Age of the **stalest** source in the result (max across sources) |
| `rate_limit_status` | `"ok"`; production also emits `"borrowed"` and `"async_rerouted"` |
| `trace_id` | OTel trace ID — find this in logs / Tempo |
| `cache_status` | Per-source: `"hit"` or `"miss"` |
| `rows_per_source` | Raw row count returned by each source after pushdown |

**Error responses** (FastAPI wraps the payload in `detail`)
```json
HTTP/1.1 429
Retry-After: 13

{
  "detail": {
    "code": "RATE_LIMIT_EXHAUSTED",
    "message": "Rate limit exhausted at user scope for connector 'github'",
    "retry_after": 12.3,
    "details": { "scope": "user", "connector": "github" }
  }
}
```

| Code | HTTP | When |
|---|---|---|
| `RATE_LIMIT_EXHAUSTED` | 429 | Token bucket empty for this connector × scope |
| `ENTITLEMENT_DENIED` | 403 | Tenant not authorised for table, OR RLS produces no rows |
| `INVALID_QUERY` | 400 | sqlglot parse fail, unsupported clause, bad column reference |
| `SOURCE_TIMEOUT` | 504 | Connector fetch deadline exceeded |
| `STALE_DATA` | 200 | Returned cached past `max_staleness` (production: warning, not error) |
| `SCHEMA_DRIFT` | 502 | Source returned shape mismatching the descriptor |

---

## 5. Request lifecycle — `POST /v1/query` step by step

Reference query (the demo):
```sql
SELECT pr.number, pr.title, jira.key, jira.status, jira.assignee
FROM   github.pull_requests AS pr
JOIN   jira.issues          AS jira ON jira.key = pr.linked_issue_key
WHERE  pr.repo = 'acme/api'
LIMIT  5
```
Header: `X-User-Id: bob`. `max_staleness_seconds: 300`.

| # | Step | Code | What happens |
|---|------|------|---|
| 1 | HTTP receive | `main.py:query()` | FastAPI deserializes body into `QueryRequest`. CORS middleware passes through. OTel `FastAPIInstrumentor` opens a server span. |
| 2 | Auth | `auth.py:get_current_user` | Read `X-User-Id`. Look up `bob` in policy YAML. Build `User(id="bob", tenant="acme", roles=["engineer"], attrs={"allowed_repos":["acme/api"]})`. |
| 3 | Span open | `planner.py:execute` | Open `planner.execute` span. Tag `user.id`, `user.tenant`. Generate `trace_id`. |
| 4 | Parse | `planner.py:_parse` | `sqlglot.parse_one(sql, dialect="postgres")`. Walk AST: extract FROM (`github.pull_requests` AS `pr`), JOIN (`jira.issues` AS `jira` ON `jira.key = pr.linked_issue_key`), WHERE (`pr.repo = 'acme/api'`), LIMIT 5. Build `Plan` dataclass. |
| 5 | Validate | `planner.py:_validate` | Each table exists in catalog. `entitlements.assert_table_allowed("acme", "github.pull_requests")` and `("acme", "jira.issues")` — both pass since `acme` is allowed both. |
| 6 | RLS | `planner.py:_apply_rls` | For `pr`: policy YAML has `apply_to_roles: [engineer]` AND Bob is an engineer → append `Predicate(repo, IN, ["acme/api"])`. For `jira`: no RLS rule applies. **At this point Bob's WHERE `pr.repo='acme/api'` and the RLS predicate `pr.repo IN ['acme/api']` are both attached — they intersect to the same set.** |
| 7 | Parallel fetch | `planner.py:execute` | `asyncio.gather` two `_fetch_table` coroutines. |
| 7a | Cache check | `planner.py:_fetch_table` | `freshness.get(key="acme::github.pull_requests::<hash>", max_staleness=300)`. First call: miss. Histogram observed with `cache_status="hit"` is not yet incremented. |
| 7b | Rate-limit acquire | `rate_limit.py:HierarchicalRateLimiter.acquire` | User → tenant → global token-bucket sequence. All three pass. On any failure the prior decrements are refunded. |
| 7c | Connector fetch | `connectors/github_mock.py:fetch` | Open `connector.github.fetch` span. Apply pushable predicates (`repo IN ['acme/api']`) to the 200-row fixture → ~100 rows. Compute ETag (sha1 of body). Sleep 20ms to simulate API latency. Return `FetchResult(rows, etag, latency_ms)`. Histogram observed with `cache_status="miss"`. |
| 7d | Cache put | `freshness.py:put` | Insert into LRU. |
| 7e | Same for Jira | as above | But on Jira, no WHERE filter → 120 rows returned. |
| 8 | Hash join | `planner.py:_hash_join` | Build hash table on Jira rows keyed by `jira.key`. Probe with each PR's `linked_issue_key`. Emit merged rows with prefixed keys (`pr.number`, `jira.key`, …). |
| 9 | CLS | `planner.py:_apply_cls` | Bob is not in `manager` role → policy says redact `assignee` on `jira.issues`. For each merged row, replace `jira.assignee` with `"[REDACTED]"`. |
| 10 | Project + LIMIT | `planner.py:_project` | Drop alias prefixes per the SELECT list, take first 5 rows. |
| 11 | Build response | `planner.py:execute` | Compose `QueryResponse` with rows, columns, `freshness_ms` = max source age (here: 0 because both were live fetches), `rate_limit_status="ok"`, `trace_id`, `cache_status`, `rows_per_source`. |
| 12 | Metrics increment | `main.py:query` | `QUERY_COUNTER.labels(tenant="acme", result="ok").inc()`. |
| 13 | HTTP serialize | FastAPI | Pydantic `QueryResponseModel` → JSON. Server span closes. OTel batch exports the trace. |

A repeat of the same query within 5 minutes hits the cache at step 7a
and returns immediately, with `cache_status: "hit"` and a non-zero
`freshness_ms`.

---

## 6. SQL surface supported

The prototype implements a deliberate subset.

**Supported**
- `SELECT` with one or more projected columns
- Column projections must be `alias.column` (qualified) for joined queries
- `FROM table AS alias` — aliases required
- One optional `JOIN table AS alias ON a.x = b.y` — equality join only
- `WHERE` with AND-combined predicates; ops: `=`, `!=`, `<`, `>`, `<=`, `>=`, `IN (...)`, `LIKE`
- `LIMIT n`

**Not yet supported**
- Subqueries / CTEs
- Aggregations (`COUNT`, `SUM`, `GROUP BY`) — single-source predicate-pushdown queries don't need them; cross-source aggregations are part of the materialization story (M4)
- More than one JOIN
- `OR` in WHERE
- Function calls in projection
- `ORDER BY` (the API accepts it via spec but only single-source order is honoured)

These are deferred, not impossible — sqlglot already provides AST nodes
for all of them.

---

## 7. Data shapes (Python dataclasses)

```python
# auth.py
@dataclass(frozen=True)
class User:
    id: str            # the X-User-Id value
    tenant: str        # resolved from policy YAML
    roles: List[str]   # ["engineer"], ["engineer","manager"], ...
    attrs: dict        # arbitrary user attributes referenced by RLS

# connectors/base.py
@dataclass(frozen=True)
class Predicate:
    column: str
    op: str            # =, !=, >, <, >=, <=, IN, LIKE
    value: Any

@dataclass
class FetchSpec:
    columns: List[str]
    predicates: List[Predicate]
    limit: Optional[int]

@dataclass
class CapabilityDescriptor:
    table_name: str
    columns: List[str]
    pushable_predicates: Set[str]
    join_keys: List[str]
    max_page_size: int
    estimated_p99_ms: int
    rate_limit_per_minute: int

# planner.py
@dataclass
class Plan:
    tables: List[TableRef]
    join: Optional[JoinSpec]
    projection: List[Tuple[str, str]]  # (qualified, output_alias)
    limit: Optional[int]

@dataclass
class QueryResponse:
    rows: List[dict]
    columns: List[str]
    freshness_ms: int
    rate_limit_status: str
    trace_id: str
    cache_status: Dict[str, str]
    rows_per_source: Dict[str, int]
```

---

## 8. Configuration surface

### Environment variables (read in `settings.py`)

| Name | Default | Purpose |
|---|---|---|
| `CONNECTOR_MODE` | `mock` | `mock` (default) or `live` (real GitHub/Jira) |
| `GITHUB_TOKEN` | — | Live mode only |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_TOKEN` | — | Live mode only |
| `GITHUB_RPM_GLOBAL` / `_TENANT` / `_USER` | 1200/600/300 | Token-bucket capacity per minute, per scope |
| `JIRA_RPM_GLOBAL` / `_TENANT` / `_USER` | 1200/600/300 | Same for Jira |
| `DEFAULT_TTL_SECONDS` | 300 | Default `max_staleness_seconds` if the request doesn't pass one |
| `DEV_AUTH` | `true` | Use `X-User-Id` header instead of OIDC |
| `POLICY_PATH` | `policies/default.yaml` | Where to load entitlement policies |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Optional; ships traces to a real collector |

### Policy YAML shape (`policies/default.yaml`)

```yaml
users:
  <user_id>:
    tenant: <tenant_id>
    roles: [<role>, ...]
    attrs:
      <key>: <value-or-list>      # referenced by RLS via value_from_user

tenants:
  <tenant_id>:
    allowed_tables: [<table>, ...]

policies:
  - table: <table>
    rls:                          # optional
      apply_to_roles: [<role>, ...]
      predicate:
        column: <col>
        op: <=, !=, IN, ...>
        value: <literal>          # OR
        value_from_user: <attr>   # bind from user.attrs
    cls:                          # optional
      apply_to_roles: [<role>, ...]            # CLS applies if any role matches
      apply_to_roles_not_in: [<role>, ...]     # CLS applies if NO role matches
      mask:
        column: <col>
        strategy: redact | hash
```

`apply_to_roles` and `apply_to_roles_not_in` are mutually exclusive in
intent; if both are set, the engine evaluates both gates.

---

## 9. Feature → code map

For reviewers tracing each rubric requirement to the code that
demonstrates it:

| Feature | Defined in | Compiled in | Applied in | Tested in |
|---|---|---|---|---|
| RLS predicate | `policies/default.yaml` | `entitlements.py:rls_predicates_for` | `planner.py:_apply_rls` (extends per-table predicates) | `tests/test_query_e2e.py::test_cross_app_join_with_entitlements_and_mask` (Bob restricted to `acme/api` even with no WHERE) |
| CLS column mask | `policies/default.yaml` | `entitlements.py:cls_masks_for` | `planner.py:_apply_cls` (post-join, pre-projection) | `tests/test_query_e2e.py::test_manager_sees_assignee_unmasked` (manager sees real value, others see `[REDACTED]`) |
| Predicate pushdown | sqlglot AST walk | `planner.py:_extract_predicates` | `connectors/*.py:fetch` checks `pushable_predicates` | implicit in e2e — Bob's RLS predicate becomes a `repo IN ['acme/api']` filter inside the GitHub mock |
| Hierarchical rate limit | env vars | `rate_limit.py:HierarchicalRateLimiter.__init__` | `planner.py:_fetch_table` calls `acquire()` | `tests/test_rate_limit.py::test_user_scope_exhausted_returns_friendly_error` |
| Token-bucket refund on partial failure | n/a | `rate_limit.py:_refund` | called on user/tenant pass + global fail | implicit in same test |
| Freshness TTL | request `max_staleness_seconds` | `freshness.py:FreshnessCache` | `planner.py:_fetch_table` checks before fetch | `tests/test_query_e2e.py::test_cache_hit_on_repeat_query` |
| Tenant-scoped cache key | n/a | `planner.py:_cache_key` | every cache get/put | implicit — keys begin with `{tenant}::` |
| Standard error vocabulary | `errors.py` | n/a | `main.py:query` catches `QueryError` and emits `Retry-After` | rate-limit test |
| OTel tracing | `observability.py:init_tracing` | wired at startup | three nested spans per query | `evidence/otel-trace-sample.txt` |
| Prometheus metric | `observability.py` | wired at startup | `_fetch_table` emits histogram with `cache_status` label | `evidence/sample-metrics.txt`, dashboard panels |

---

## 10. Mocked vs real

### Mocked
- **Source data**: deterministic fixtures (200 PRs + 120 issues, seeded
  RNG). Server-side filtering is real for the columns listed in the
  capability descriptor; everything else falls through to client-side.
- **Auth**: `X-User-Id` header instead of JWT.
- **Vault / KMS**: nothing — settings come from env vars.
- **Materialization layer**: not implemented (in-memory join only).

### Real
- **HTTP framework**: FastAPI with async I/O.
- **SQL parsing**: `sqlglot` real AST + transformations.
- **Rate limiter**: real token-bucket logic — just in-process state.
- **Cache**: real LRU + TTL.
- **OTel**: real spans, real trace IDs (visible in logs).
- **Prometheus**: real histogram + counters scraped by real Prometheus.
- **Grafana**: real dashboard with real PromQL.
- **k6**: real HTTP load.

### Switching to live mode

```bash
export CONNECTOR_MODE=live
export GITHUB_TOKEN=ghp_xxx
export JIRA_BASE_URL=https://acme.atlassian.net
export JIRA_EMAIL=you@acme.com
export JIRA_TOKEN=xxx
docker compose up
```

(Live connectors are the obvious extension point — see §11. The mock
connectors implement the same `Connector` protocol, so swapping is a
file change, not a rewrite.)

---

## 11. Extension points

### Adding a new connector

1. Create `app/connectors/<name>.py` implementing the `Connector`
   protocol (`base.py`):
   - `name: str` (lowercase, used in metric labels)
   - `capability: CapabilityDescriptor` (column list, pushables, etc.)
   - `async def fetch(self, spec, etag=None) -> FetchResult`
2. Register it in `connectors/registry.py:build_default_registry`.
3. Add a rate-limit `BudgetConfig` in `main.py` (or generalise to read
   from settings).
4. Update `policies/default.yaml` to include the new table in
   `allowed_tables`.

The planner needs no changes — it discovers the new table via the
catalog.

### Adding a new policy rule

Edit `policies/default.yaml`. The format is documented in §8. Rules
take effect on the next request (no restart needed for hot reload —
not yet implemented; see roadmap).

### Adding a new SQL feature

Most extensions live in two places in `planner.py`:
- `_parse` — recognise the new AST node from sqlglot
- `_extract_predicates` (for new operators) or `_hash_join` (for new
  join types) — wire the semantics

The capability descriptor's `pushable_predicates` set governs which
predicates a connector accepts server-side; a new operator must be
listed here AND handled in `Predicate.matches`.

### Switching the rate-limit backend to Redis

Replace `HierarchicalRateLimiter` with a Redis-backed implementation
that runs the Lua script described in
[`../design/03-freshness-rate-limits.md`](../design/03-freshness-rate-limits.md§3.1).
The interface (`acquire(connector, tenant, user, n)`) is unchanged.

---

## 12. Tests

Two pytest files, both run in <0.5 s.

```bash
cd backend
.venv/bin/python -m pytest -v
```

| Test | What it asserts |
|---|---|
| `test_cross_app_join_with_entitlements_and_mask` | Cross-source join works; RLS prunes Bob to `acme/api`; CLS redacts `assignee` for non-managers |
| `test_cache_hit_on_repeat_query` | First call → cache miss; second identical call → cache hit with `freshness_ms ≥ 0` |
| `test_manager_sees_assignee_unmasked` | `manager` role exempts CLS — real assignee values visible |
| `test_token_bucket_grants_then_denies` | Bucket of 2: two grants, third denial; `retry_after = ∞` when refill rate is 0 |
| `test_user_scope_exhausted_returns_friendly_error` | User-scope exhaustion raises `RateLimitExhausted` with `code`, `retry_after`, and `details.scope == "user"` |

CI integration is straightforward (`pytest` returns a non-zero exit on
any failure); GitHub Actions / GitLab CI is a one-day job, not done in
the prototype.

---

## 13. Where to look first as a reviewer

| Question | Look at |
|---|---|
| "Does it actually work?" | `evidence/sample-query-response.json` and `evidence/grafana-dashboard-final.png` |
| "Show me the architecture seams" | This file's §3 component diagram + §5 lifecycle table |
| "How is RLS enforced?" | `policies/default.yaml` → `entitlements.py:rls_predicates_for` → `planner.py:_apply_rls` |
| "How is the rate limit hierarchical?" | `rate_limit.py:HierarchicalRateLimiter.acquire` |
| "How is freshness handled?" | `planner.py:_fetch_table` (lines tagged "Cache check") + `freshness.py` |
| "What's the production gap?" | `README.md` "Trade-offs" table + `../planning/02-execution-plan.md` milestones |
| "Did the load test pass?" | `evidence/load-test-results.md` |
