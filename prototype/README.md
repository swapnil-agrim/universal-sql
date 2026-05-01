# Universal SQL — Prototype

End-to-end M1 prototype for the take-home design: cross-app SQL query
(GitHub PRs ↔ Jira issues) with entitlements, rate limits, freshness,
tracing, and metrics. **Backend in Python (FastAPI)**, **frontend in Next.js**.
All business logic lives server-side; the UI is a thin shell.

> Three doc surfaces, written for different readers:
> - **This file** — how to run it, demos for each capability, layout.
> - **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — internals reference: module map,
>   API spec, request lifecycle, data shapes, extension points.
> - **[`../design/`](../design/)** — system-level design (multi-tenant
>   production architecture, security, capacity, six-month plan).

---

## What the prototype demonstrates

| Capability | Where it lives |
|---|---|
| `POST /v1/query` returning `rows + freshness_ms + rate_limit_status + trace_id` | `backend/app/main.py` |
| SQL parsing + predicate pushdown | `backend/app/planner.py` (uses `sqlglot`) |
| 2 connectors with capability descriptors | `backend/app/connectors/{github_mock,jira_mock}.py` |
| RLS predicate + CLS column mask via YAML policy | `backend/policies/default.yaml` + `backend/app/entitlements.py` |
| Hierarchical token-bucket rate limit (global/tenant/user) | `backend/app/rate_limit.py` |
| TTL freshness cache with cache-status surfaced per source | `backend/app/freshness.py` |
| OpenTelemetry traces (one per query, one span per connector fetch) | `backend/app/observability.py` |
| Prometheus metric `connector_request_duration_seconds` | `backend/app/observability.py` |
| Standard error vocabulary (`RATE_LIMIT_EXHAUSTED`, `ENTITLEMENT_DENIED`, etc.) | `backend/app/errors.py` |
| k6 load test driving ~700 QPS for 60 s | `load-test/k6.js` |
| Thin Next.js UI | `frontend/app/page.tsx` |

---

## Quickstart

### Option A — Docker Compose (recommended)

```bash
cd prototype
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Frontend | <http://localhost:4000> | Thin Next.js UI |
| Backend  | <http://localhost:8000> | FastAPI gateway + `/v1/query` |
| Backend metrics | <http://localhost:8000/metrics> | Prometheus exposition |
| Backend Swagger | <http://localhost:8000/docs> | Auto-generated API docs |
| Prometheus | <http://localhost:9090> | Scrapes backend every 5 s |
| Grafana | <http://localhost:4001/d/universal-sql-main/universal-sql-gateway> | Pre-provisioned dashboard, anonymous Admin |

Open the UI, pick a user, click **Run query**.

### Option B — Native (faster iteration)

Backend:
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

### Smoke test (no UI)

```bash
curl -s -X POST http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: alice' \
  -d '{
    "sql": "SELECT pr.number, pr.title, jira.key, jira.status, jira.assignee FROM github.pull_requests AS pr JOIN jira.issues AS jira ON jira.key = pr.linked_issue_key WHERE pr.repo = '\''acme/api'\'' LIMIT 5",
    "max_staleness_seconds": 300
  }' | jq
```

---

## Try the failure modes

The architecture's worth comes from how it behaves under stress. Four scripted demos:

### 1. Entitlement enforcement (RLS)
Run the same query as `alice` (allowed `acme/api` + `acme/web`) and `bob` (only `acme/api`).
Bob's response will show fewer rows even with no `WHERE` filter — RLS pruned them
before the connector fetch.

```bash
curl -s -X POST http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' -H 'X-User-Id: bob' \
  -d '{"sql":"SELECT pr.repo, pr.number FROM github.pull_requests AS pr LIMIT 50"}' \
  | jq '.rows[] | .repo' | sort -u
# → only "acme/api"
```

### 2. Column-level mask (CLS)
`bob` (engineer) and `manager` (engineer + manager) running the same Jira query
will see different `assignee` values — `bob` gets `[REDACTED]`, manager gets the real value.

```bash
for u in bob manager; do
  echo "as $u:"
  curl -s -X POST http://localhost:8000/v1/query \
    -H 'Content-Type: application/json' -H "X-User-Id: $u" \
    -d '{"sql":"SELECT j.key, j.assignee FROM jira.issues AS j LIMIT 3"}' \
    | jq -c '.rows'
done
```

### 3. Rate-limit exhaustion
Set `GITHUB_RPM_USER=2` in `docker-compose.yml`, restart, and run a few different
queries (different `WHERE` clauses to bypass the cache). The 3rd unique query
returns `429` with:

```json
{
  "code": "RATE_LIMIT_EXHAUSTED",
  "message": "Rate limit exhausted at user scope for connector 'github'",
  "retry_after": 12.3,
  "details": { "scope": "user", "connector": "github" }
}
```

…and a `Retry-After` header.

### 4. Freshness control
First call: `cache_status: {"github.pull_requests": "miss"}`. Repeat within
`max_staleness_seconds`: `"hit"`. Set `max_staleness_seconds: 0` and the cache
is bypassed every time.

---

## Tests

```bash
cd backend
.venv/bin/python -m pytest -v
```

Two test files:
- `test_query_e2e.py` — cross-app join + RLS + CLS + cache hit on repeat
- `test_rate_limit.py` — token bucket exhaustion + `RATE_LIMIT_EXHAUSTED` surfaced cleanly

---

## Load test

With the backend running:

```bash
# Native k6
k6 run load-test/k6.js

# Or via Docker (no install needed)
docker run --network host -v "$PWD/load-test":/scripts -i grafana/k6 \
  run /scripts/k6.js
```

Drives 700 QPS for 60 s across three query shapes and three users. Passes if
`http_req_duration p(95) < 1500ms` and `http_req_failed < 5%` (matches the
design's SLOs). The k6 summary also reports `cache_hits` vs `cache_misses` —
expected steady-state ratio after warm-up is >95% hits.

---

## Tracing & metrics

- **Traces**: emitted via OTel; default exporter is `ConsoleSpanExporter` (visible
  in backend logs). Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://your-collector:4317`
  to ship to Tempo/Jaeger. Each `/v1/query` produces one trace with spans
  `planner.execute → planner.fetch_all → connector.{github,jira}.fetch`.
- **Metrics**: <http://localhost:8000/metrics> exposes:
  - `connector_request_duration_seconds{connector,tenant,cache_status}` (histogram)
  - `queries_total{tenant,result}` (counter)
  - `rate_limit_rejections_total{connector,scope}` (counter)
  - default FastAPI/Python runtime metrics

### Bundled Grafana dashboard

`docker compose up` boots Prometheus (scraping the backend every 5 s) and a
Grafana instance with a provisioned datasource and a dashboard at
[/d/universal-sql-main](http://localhost:4001/d/universal-sql-main/universal-sql-gateway).
Anonymous Admin auth is enabled so it loads without a login.

The dashboard has seven panels:
1. **Queries / second** — sum(rate(queries_total))
2. **P95 connector latency (live fetch)** — histogram_quantile over `cache_status="miss"` only
3. **Cache hit ratio** — proves the freshness layer is doing work
4. **Rate-limit rejections** — should be zero in normal load
5. **P50 / P95 by cache status** — proves cached reads are ~0 ms vs ~20 ms live
6. **Throughput** — stacked by `result` label so failures stand out
7. **Connector fetch volume (hit vs miss)** — stacked area, shows freshness budget at work

A 700-RPS / 60-second k6 run produces the screenshots in `evidence/`. See
[`evidence/load-test-results.md`](evidence/load-test-results.md) for the headline
numbers (P95 = 6.59 ms, 0 % failures, 100 % cache hit ratio in steady state).

---

## Trade-offs and what's deferred

The prototype intentionally stays inside M1 scope (see `../planning/02-execution-plan.md`):

| Production design | Prototype simplification |
|---|---|
| Redis-backed token buckets w/ Lua atomicity | In-process asyncio buckets (single-process semantics only) |
| Per-tenant KMS DEKs via Vault | Tenant ID scoped cache keys; no encryption at rest |
| OPA/Rego policy DSL | Embedded YAML policy + Python evaluator |
| Cardinality estimator → DuckDB / ClickHouse modes | In-memory hash join only; modes referenced in design doc |
| OIDC JWT verification | `X-User-Id` header → policy YAML lookup |
| Async overflow path via Temporal | Sync only; design doc covers the full path |
| Postgres metadata catalog with versioning | In-memory catalog populated from connector descriptors |

Each row above maps to a roadmap milestone in `../planning/02-execution-plan.md`
so the prototype-to-production path is explicit.

---

## Layout

```
prototype/
├── backend/
│   ├── app/
│   │   ├── main.py                FastAPI gateway, /v1/query
│   │   ├── planner.py             SQL → AST → pushdown → fetch → join
│   │   ├── connectors/            base + 2 mock connectors + registry
│   │   ├── entitlements.py        YAML policy → RLS predicates / CLS masks
│   │   ├── rate_limit.py          hierarchical token buckets
│   │   ├── freshness.py           TTL+ETag cache
│   │   ├── catalog.py             schema lookup
│   │   ├── auth.py                X-User-Id → User
│   │   ├── observability.py       OTel + Prometheus
│   │   ├── errors.py              standard error vocabulary
│   │   └── settings.py            env config
│   ├── policies/default.yaml      one RLS + one CLS rule
│   ├── tests/                     2 pytest files
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app/                       Next.js App Router (page.tsx + layout.tsx)
│   ├── package.json
│   └── Dockerfile
├── load-test/k6.js                700 QPS × 60 s scenario
├── docker-compose.yml
└── README.md                      ← you are here
```
