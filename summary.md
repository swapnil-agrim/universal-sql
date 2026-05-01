# Universal SQL — Submission Summary (one-pager)

> Take-home for the Ema Eng Lead role. Three deliverables: design doc,
> 6-month execution plan, prototype. This file is the index.

---

## 1. The ask

Design and prototype a **universal SQL query layer** over many SaaS apps.
Scale assumption: 100s of customers, 1000s of app types, 10M users, ~1k QPS.
Must support cross-app queries with **entitlements (RLS/CLS), per-app rate
limits, freshness controls, multi- and single-tenant deploys**, and an
SLO of P50 < 500 ms / P95 < 1.5 s for single-source predicate-pushdown
queries.

---

## 2. Verdict at a glance

- **Architecture & design**: complete across 4 docs in `design/` covering
  system, freshness/rate-limits, security, capacity at 1k QPS.
- **Execution plan**: 6 milestones × 2 sprints each = 12 sprints with a
  rendered Gantt chart and named tasks per role in `planning/`.
- **Prototype**: working FastAPI + Next.js stack in `prototype/`.
  Verified live — **k6 sustained 700 RPS / 60 s, P95 6.59 ms, 0 failures,
  100 % cache-hit ratio in steady state**. Dashboard screenshot in
  `prototype/evidence/`.

---

## 3. What's implemented vs. pending

| Capability | Status | Where |
|---|---|---|
| `POST /v1/query` returning rows + freshness + rate-limit + trace metadata | ✅ live | `prototype/backend/app/main.py` |
| 2 connectors with capability descriptors (mocked GitHub + Jira) | ✅ live | `prototype/backend/app/connectors/` |
| SQL parsing + predicate pushdown via sqlglot | ✅ live | `prototype/backend/app/planner.py` |
| RLS predicate composition via YAML policy | ✅ live | `entitlements.py` + `policies/default.yaml` |
| CLS column mask (redact / hash) | ✅ live | same module |
| Hierarchical token-bucket rate limiter (global / tenant / user) | ✅ live, in-process | `rate_limit.py` |
| TTL+ETag freshness cache; `cache_status` per source in response | ✅ live, in-process | `freshness.py` |
| **Per-query timeouts + partial-results envelope flag** | ✅ live | `planner.py::_fetch_table_with_timeout` |
| OTel tracing — `planner.execute → fetch_all → connector.{name}.fetch` | ✅ live | `observability.py` |
| Prometheus metric `connector_request_duration_seconds` + Grafana dashboard | ✅ live | `monitoring/` |
| k6 load test 700 RPS × 60 s | ✅ run + screenshots captured | `load-test/k6.js`, `evidence/` |
| Standard error vocabulary + `Retry-After` headers | ✅ live | `errors.py` |
| Pytest suite (6 tests covering RLS, CLS, cache, rate-limit, **partial-results**) | ✅ pass | `tests/` |
| **Head-of-line blocking mitigations (5 layers)** | ✅ documented | `design/05-capacity-1k-qps.md §8` |
| **Operational runbooks** (rate-limit flood, auth failure, cache stampede) | ✅ documented | `design/runbooks/` |
| **Rendered system architecture diagram** (Mermaid → PNG / SVG) | ✅ rendered | `design/diagrams/` |
| **Chaos plan** (12 scenarios with hypothesis + pass criteria; game-day process) | ✅ documented | `design/06-chaos-plan.md` |
| Per-tenant KMS via Vault (envelope encryption) | 📋 design only | covered in `design/04-security.md`, M2 |
| Async overflow path (Temporal workflow + push notification) | 📋 design only | covered in `design/03-freshness-rate-limits.md`, M3 |
| Policy DSL via OPA/Rego with CI validator | 📋 design only | YAML embedded today, M3 |
| DuckDB ephemeral + ClickHouse short-lived materialisation | 📋 design only | in-memory join only today, M4 |
| Multi-tenant Helm chart (same chart, single + multi modes) | 📋 design only | docker-compose today, M2 / M4 |
| 5 production connectors (Salesforce, Zendesk, Notion + the 2) | 📋 design only | 2 today, M5 |
| Admin console UI for tenant / connector / policy management | 📋 design only | API only today, M6 |
| Audit log to Kafka + S3 object-lock | 📋 design only | OTel span attrs today, M3 |
| Crypto-shred drill (KMS revoke = data unrecoverable) | 📋 design only | M5 |
| External pen-test + SOC 2 Type 1 prep | 📋 plan only | M5–M6 |

Legend: ✅ live in code · 📋 specified, on the roadmap.

---

## 4. The approach (six bold calls we defend in the design doc)

1. **Federated by default; ephemeral materialisation on demand.** The
   *planner* picks per query — in-memory join for small results,
   per-query DuckDB for big joins, short-lived ClickHouse table for hot
   repeated queries. Not a config, a planner decision.
2. **Capability-driven planner.** Connectors ship capability
   descriptors (pushable predicates, page sizes, latency hints, rate
   limits). Adding a connector = ship a descriptor, no planner changes.
3. **Hierarchical token buckets with budget borrowing.** Three nested
   buckets (connector → tenant → user) with idle tenants donating up
   to 50 % of unused budget; busy tenants capped at 2× nominal. Solves
   "fairness across tenants" with a hard ceiling.
4. **Freshness as a SQL hint (`max_staleness`), not config.** Per-query
   knob the planner uses to choose cache vs. live vs. async-defer. The
   user sees `freshness_ms` in every response.
5. **Same Helm chart for multi-tenant and single-tenant deploys.** Flag
   change, not code change. Off-boarding = delete namespace + revoke
   tenant KMS key (crypto-shred).
6. **Async overflow path is first-class.** Budget-exhausted query gets
   `202 Accepted` + a job URL; Temporal workflow runs against a
   separate slow pool; push-notification on completion.

---

## 5. Architectural & DB choices

| Decision | Choice | Why |
|---|---|---|
| SQL parser | `sqlglot` | Real AST + transformations; multi-dialect free |
| Policy engine | YAML embedded (proto) → OPA / Rego (prod) | Proto: zero deploy. Prod: standard, auditable, CI-validatable |
| AuthN | `X-User-Id` header (proto) → OIDC JWT + JWKS (prod) | Proto: dev speed. Prod: short-lived JWT + revocation list |
| Metadata catalog | Postgres + row-level security | Mature; per-tenant filtering at storage layer |
| Distributed cache (L2) | Redis cluster | < 2 ms P99; Lua for atomic multi-key ops |
| Rate-limit store | In-process (proto) → Redis + Lua (prod) | Atomic acquire across 3 buckets in one round-trip |
| Materialisation engine | DuckDB ephemeral (per-query, tmpfs) + ClickHouse (per-tenant TTL ≤ 5 min) | DuckDB: vectorised, zero-deploy, fits in worker pod. ClickHouse: shared-state across pods |
| Workflow engine | Temporal Cloud | Durable workflows + retry semantics for async overflow |
| Secrets / keys | Vault + cloud KMS, per-tenant DEK ⊂ tenant KEK | Crypto-shred via KEK revoke |
| Audit log | Kafka topic per tenant → S3 with object-lock | Append-only, tamper-evident, residency-aware |
| Tracing / metrics | OpenTelemetry → Tempo + Prometheus + Grafana | Open standards; same code works locally and in prod |
| Container orchestration | Docker Compose (proto) → k8s + Helm (prod) | Namespace per tenant + NetworkPolicy for isolation |
| IaC | Terraform modules (networking, KMS, RDS, Redis, EKS) | Reproducible per-region deploys |
| Cost target | $0.0082 / 1000 queries (sized 60× under $0.50 GA target) | Headroom funds 2× over-provisioning |

---

## 6. Components — one-liner + small example

| Component | Role (one line) | Tiny example |
|---|---|---|
| **Query Gateway** | HTTP entry point; OIDC verify, request shaping, response envelope, OTel server span | `POST /v1/query {sql,...}` → 200 with `rows + freshness_ms + rate_limit_status + trace_id` |
| **Query Planner** | Parse SQL, push predicates down, decide execution mode, fetch in parallel, join, mask, project | Sees `SELECT…JOIN…WHERE pr.repo='acme/api'` → calls GitHub + Jira concurrently with pushed-down filters; hash-joins in memory |
| **Connector SDK + Registry** | Capability descriptor + `fetch()` contract; registry maps `table → connector` | `github.pull_requests` declares `pushable: [repo, author, merged_at]`, `max_page_size: 100`, `rate_limit: 5000/h` |
| **Entitlement Service** | Compose `source perms ∩ tenant policy` → RLS predicates + CLS column masks per `(user, table)` | Bob (engineer) → service appends `repo IN ['acme/api']` to fetch; for non-managers, `assignee` column gets `[REDACTED]` |
| **Rate-Limit Service** | Hierarchical token buckets per connector × tenant × user; budget borrowing across idle tenants; one-call-roll-back on partial failure | Bob's user-bucket empty → `429 RATE_LIMIT_EXHAUSTED` with `Retry-After: 13` and `details.scope: "user"` |
| **Freshness Layer** | TTL + ETag cache (L1 in-mem, L2 Redis, L3 conditional ETag); honours per-query `max_staleness` | Same query within 5 min → cache hit; `cache_status: "hit"`, `freshness_ms: 17` |
| **Materialisation Layer** | Ephemeral DuckDB (per-query, ≤ seconds) or short-lived ClickHouse (per-tenant, TTL ≤ 5 min) for joins/aggregations the planner can't fit in memory | 50k × 50k join → spill to per-pod DuckDB, drop after response. Hot dashboard query (3rd hit in 5 min) → promote to ClickHouse table |
| **Tenant Registry** | Tenant metadata, allowed tables, residency tag, tenant KEK reference, off-boarding state | `acme` → `{tables: [github.pull_requests, jira.issues], residency: us, kek: arn:…/acme}` |
| **Schema Catalog** | `table → columns, join keys, capability descriptor`; versioned | `github.pull_requests → columns: [number, title, repo, ...], join_keys: [linked_issue_key]` |
| **Policy Store** | Versioned RLS + CLS rules per tenant; signed commits in git-backed Vault | YAML (proto) — see `policies/default.yaml`. Rego (prod) — `package universal_sql.rls` files per tenant |
| **Secrets & Keys** | Vault dynamic secrets for source credentials; per-tenant DEK wrapped by tenant KMS KEK; rotation every 90 d | Off-board `acme` → revoke `arn:…/acme` KEK → all tenant ciphertext (cache, S3, ClickHouse) becomes structurally unrecoverable |
| **Audit Log** | One append-only record per cross-system access; predicate values are hashed, not stored | `{ts, tenant, user, trace_id, table, predicates_applied: [{col,op,value_hash}], rls_rules, rows_returned}` |
| **Async Job Runner** | Temporal workflow for budget-exhausted or long queries; runs against separate slow-pool | `429` with `async_url` → client opts in → `/v1/jobs/abc-123` → push notification when result lands in tenant S3 |
| **Observability** | OTel traces (one per query, spans per stage), Prometheus histograms (`cache_status` label), Grafana dashboards | Single trace shows `planner.execute → fetch_all → connector.github.fetch + connector.jira.fetch` with shared `trace_id` |

---

## 7. Repo layout

```
universal-sql/
├── summary.md           ← you are here (one-pager)
├── design/              ← system architecture — 4 docs
│   ├── 01-architecture.md            scenario, 6 bold calls, request flow
│   ├── 03-freshness-rate-limits.md   3-layer cache, hierarchical buckets, borrowing
│   ├── 04-security.md                STRIDE, isolation layers, audit, residency
│   └── 05-capacity-1k-qps.md         sizing math, $21k/mo cost model, bottleneck succession
├── planning/            ← operational plan
│   ├── 02-execution-plan.md          north-stars → themes → milestones → risks
│   ├── sprint_planning.md            12 × 2-week sprints, deps, sprint-review template
│   ├── gantt.png · gantt.svg         rendered Gantt chart
│   └── gantt.mmd                     Mermaid source
└── prototype/           ← working M1 vertical slice
    ├── ARCHITECTURE.md               module map, API ref, request lifecycle
    ├── README.md                     quickstart, demos, testing
    ├── backend/                      FastAPI + sqlglot + OTel + 1281 LOC Python
    ├── frontend/                     Next.js, ~150 LOC TS, no business logic
    ├── monitoring/                   Prometheus + provisioned Grafana dashboard
    ├── load-test/k6.js               700 RPS × 60 s scenario
    ├── docker-compose.yml            4 services: backend, frontend, prometheus, grafana
    └── evidence/                     captured artifacts (Grafana PNG, k6 summary, OTel trace)
```

---

## 8. Key numbers

| Metric | Value |
|---|---|
| Prototype LOC | ~1,281 Python + ~150 TypeScript |
| Live load test | **700 RPS sustained × 60 s** (700 RPS configured, 700 measured by k6) |
| P95 latency under load | **6.59 ms** (vs SLO 1500 ms) |
| Cache hit ratio in steady state | **100 %** (56,201 hits / 23 misses over 60 s) |
| Failures under load | **0** (42,001 / 42,001 successful) |
| GA cluster size at 1k QPS | ~150 vCPU / ~280 GB / 12 m6i.4xlarge nodes |
| GA cost | ~$21,200/month → **$0.0082 per 1000 queries** (60× under $0.50 target) |
| Team | 7.5 FTE × 6 months ≈ $2.25M annualised |
| Roadmap | 12 sprints × 2 weeks; 6 milestones; 9 risks tracked; 5 connectors at GA |

---

## 9. Where to start reading

| You have | Read this |
|---|---|
| 5 minutes | This file |
| 15 minutes | `design/01-architecture.md` + `prototype/evidence/load-test-results.md` |
| 30 minutes | All 4 design docs in order |
| 60 minutes | + `planning/02-execution-plan.md` + `planning/sprint_planning.md` + `prototype/ARCHITECTURE.md` |
| Want to run it | `cd prototype && docker compose up --build` then <http://localhost:4000> |

Submission goes to `souvik-sen@` and `careers@ema.co`.
