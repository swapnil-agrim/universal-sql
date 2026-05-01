# Universal SQL — Architecture (V0)

> Status: draft. Locks scenario + system design before prototype work begins.
>
> **Companion documents** (depth on rubric-weighted areas):
> - [03-freshness-rate-limits.md](03-freshness-rate-limits.md) — freshness contract + rate-limit governance
> - [04-security.md](04-security.md) — STRIDE, isolation layers, audit, residency, crypto-shred
> - [05-capacity-1k-qps.md](05-capacity-1k-qps.md) — sizing math, cost model, bottleneck succession
> - [06-chaos-plan.md](06-chaos-plan.md) — 12 chaos scenarios, game-day process, claim-to-test mapping
>
> **Planning artefacts** (operational, in [`../planning/`](../planning/)):
> - [02-execution-plan.md](../planning/02-execution-plan.md) — six-month roadmap, team, risks
> - [sprint_planning.md](../planning/sprint_planning.md) — sprint-by-sprint task allocation + Gantt

## 1. Scenario

**GitHub ↔ Jira (PRs ↔ issues).**

Rationale:
- Free APIs, PAT/Cloud-token auth (no OAuth dance burning the time budget).
- Both sources support rich server-side filtering (GitHub Search API, Jira JQL) — gives a real predicate-pushdown story instead of fetch-and-filter.
- Real, well-documented rate limits (GitHub 5000/h authenticated + secondary, Jira 10/s burst). Concrete numbers to size against.
- Natural but non-trivial join key (PR title/branch references issue keys like `PROJ-123`, plus GitHub's linked-issue API). Forces the planner to be more than a hash-join.
- Universally understood demo query.

### Target end-to-end query

```sql
SELECT pr.number, pr.title, pr.merged_at,
       jira.key, jira.status, jira.assignee
FROM   github.pull_requests AS pr
JOIN   jira.issues          AS jira ON jira.key = pr.linked_issue_key
WHERE  pr.repo = 'acme/api'
  AND  pr.merged_at > NOW() - INTERVAL '7 days'
  AND  jira.status != 'Done'
WITH   max_staleness = '5m'
LIMIT  50;
```

This single query exercises every required surface: predicate pushdown on both sides, cross-source join, RLS (private repos), CLS (mask `assignee`), `max_staleness` knob, rate-limit handling, freshness metadata in response.

---

## 2. System Architecture

**Rendered diagram:** [`diagrams/system-architecture.png`](diagrams/system-architecture.png)
· [`.svg`](diagrams/system-architecture.svg)
· [`.mmd`](diagrams/system-architecture.mmd) (Mermaid source).

ASCII version below for terminals and plain-text viewers:

```
                          ┌─────────────────────────────────────────────────┐
                          │                  CONTROL PLANE                  │
                          │                                                 │
                          │  Tenant Registry │ Schema Catalog │ Policy Store│
                          │  Connector Reg.  │ Rate Policies  │ Audit Log   │
                          │  Secrets (Vault) │ KMS (per-tenant keys)        │
                          └──────────────▲──────────────────────────────────┘
                                         │ (read-mostly, cached)
                                         │
   ┌──────────┐  HTTPS    ┌──────────────┴──────────────┐
   │  Client  ├──────────►│       Query Gateway         │  OIDC AuthN
   │ (CLI/UI) │  +JWT     │   (stateless, autoscaled)   │  request shaping
   └──────────┘           └──────┬───────────────┬──────┘  timeouts
                                 │               │
                                 ▼               ▼
                       ┌──────────────────┐  ┌──────────────────┐
                       │  Query Planner   │◄─┤ Entitlement Svc  │
                       │  parse → plan    │  │ user×table → RLS │
                       │  pushdown → exec │  │ + CLS predicates │
                       └────┬────────┬────┘  └──────────────────┘
                            │        │
              ┌─────────────┘        └─────────────┐
              ▼                                    ▼
   ┌─────────────────────┐               ┌─────────────────────┐
   │ Rate-Limit Service  │               │  Freshness Layer    │
   │ hierarchical buckets│               │  Redis hot / S3 warm│
   │ (conn / tenant / usr│               │  ETag-aware fetch   │
   └──────────┬──────────┘               └──────────┬──────────┘
              │                                     │
              ▼                                     ▼
        ┌──────────────────────────────────────────────────┐
        │            Connector Worker Pool                 │
        │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
        │  │  GitHub    │  │   Jira     │  │   ...      │  │
        │  │  worker    │  │   worker   │  │            │  │
        │  └─────┬──────┘  └─────┬──────┘  └────────────┘  │
        │   per-connector circuit breakers, isolated pools │
        └────────┼─────────────────┼───────────────────────┘
                 │                 │
                 ▼                 ▼
            external SaaS APIs (GitHub, Jira)

           ┌────────────────────────────────────┐
           │  Materialization (on-demand only)  │  ephemeral DuckDB
           │  triggered for join-heavy plans    │  TTL ≤ 5 min
           └────────────────────────────────────┘  per-tenant encryption

   Async overflow: Temporal workflow → push notification on completion
   Observability: OTel traces → Tempo · Prom metrics → Grafana · structured logs
```

---

## 3. Six Bold Design Calls

### 3.1 Federated by default; ephemeral materialization on demand
The planner picks per-query, not per-connector, based on a cardinality estimate (post-pushdown row count × source latency budget):

- **Single-source or small join** → in-memory hash join in the planner.
- **Large join** → spill to a per-query DuckDB instance in the worker pod, discarded after response.
- **Hot repeated query (same tenant, within TTL)** → short-lived ClickHouse table per tenant, TTL ≤ 5 min.

Trade-off accepted: planner has to maintain a cardinality estimator. Win: never pay for materialization storage on cheap queries, always pay for it on the queries that need it.

### 3.2 Capability-driven planner
Connectors ship a capability descriptor (YAML in the registry):
```yaml
github.pull_requests:
  pushable_predicates: [repo, author, state, merged_at, base, head]
  max_page_size: 100
  sort: [merged_at, created_at]
  rate_limit:
    requests_per_hour: 5000
    secondary_throttle: true
  estimated_p99_ms: 600
```
Planner uses this for pushdown choice, join ordering (smaller side first), and to reject queries it can't satisfy with helpful messages. Adding a new connector = ship a descriptor + a thin worker; no planner changes.

### 3.3 Hierarchical token buckets with budget borrowing
Three nested buckets per connector: **connector-global → tenant → user**. Idle tenant budget is lendable to busy tenants, with a per-tenant borrow ceiling so no one can monopolize. Redis + Lua for atomicity. This is how we satisfy the explicit "fairness across tenants" requirement.

### 3.4 Freshness as a SQL hint, not a config knob
`WITH max_staleness = '5m'` is a planner input, not a global setting:
- Cache hit within window → return cached, `freshness_ms` reflects age.
- Cache miss + budget available → live fetch.
- Cache miss + budget exhausted → return cached + `STALE_DATA` warning + `Retry-After`, OR reroute to async if the client opted in.

Per-query observability beats hidden config every time.

### 3.5 Single-tenant deployment is the same Helm chart
Multi-tenant: shared cluster, namespace per tenant, per-tenant KMS data keys.
Single-tenant: same chart with `values.tenancy=single`, dedicated namespace, optionally dedicated cluster.
Off-boarding: delete namespace + revoke KMS key → crypto-shred.
**Zero code branches.**

### 3.6 Async overflow path is first-class
When budget is exhausted and the query is expensive, gateway returns `202 Accepted` with `{job_id, status_url}`. Temporal workflow runs the query against a separate, slower-budget pool; result lands in tenant-scoped S3; push notification fires. Keeps sync-path tail latency clean.

---

## 4. Request Flow (sync path)

1. Client → Gateway (`POST /v1/query` with JWT, SQL, optional `max_staleness`).
2. Gateway: OIDC verify → tenant resolve → trace ID → forward to Planner.
3. Planner: parse SQL → validate against Catalog → fetch capability descriptors.
4. Planner ↔ Entitlement Service: get RLS predicates + CLS masks for `(user, tables)`.
5. Planner: rewrite plan — push entitlement + user predicates into source calls; pick federated vs. materialize.
6. Planner ↔ Rate-Limit Service: reserve budget per connector call (atomic Lua check-and-decrement).
7. Connector Workers (parallel): Freshness check → if stale, fetch with ETag → normalize.
8. Planner: execute join → apply CLS masks → return.
9. Gateway: emit OTel spans, Prometheus metrics → respond `{rows, columns, freshness_ms, rate_limit_status, trace_id}`.

### Error vocabulary
| Code | Meaning | UX guidance |
|---|---|---|
| `RATE_LIMIT_EXHAUSTED` | Budget gone for connector/tenant/user | Returns `Retry-After`; suggest async path |
| `STALE_DATA` | Returned cached past `max_staleness` | Returns `freshness_ms`; client may retry without staleness hint |
| `ENTITLEMENT_DENIED` | RLS removed all rows OR table not visible | Specific column/row guidance suppressed (info leak) |
| `SOURCE_TIMEOUT` | One source timed out | Partial results included with `partial: true` flag |
| `SCHEMA_DRIFT` | Capability mismatch with live source | Connector version pinned; admin alert raised |

---

## 5. Tenant Isolation

| Layer | Multi-tenant | Single-tenant |
|---|---|---|
| Compute | Shared cluster, namespace per tenant | Dedicated cluster (or namespace) |
| Storage | Shared Postgres/Redis, tenant ID in every key | Dedicated instances |
| Encryption | Per-tenant DEK wrapped by tenant KMS key | Same |
| Network | NetworkPolicy per ns, deny cross-tenant | Same + optional VPC peering |
| Off-boarding | Delete ns + revoke KMS key (crypto-shred) | Same |

Same Helm chart drives both via `values.yaml`.

---

## 6. What this implies for the prototype

The prototype only needs to demonstrate this architecture's *seams*, not all of it:
- Gateway + Planner collapsed into one Python/Go service (FastAPI is fine).
- Entitlement Service = embedded module reading a YAML policy file.
- Rate-Limit Service = in-process token bucket (Redis-style API; can swap to Redis later).
- Freshness Layer = in-process LRU + TTL.
- 2 connectors: GitHub real API + Jira real API (or mocked if tokens are friction).
- 1 OTel trace, 1 Prometheus metric (`connector_request_duration_seconds`).
- k6 script driving 500–1k QPS for 60s against a mocked-source variant.

Mapping to the architecture above is explicit so the reviewer sees the path from prototype to production.

---

## 7. Open questions to resolve next

- [ ] Pick a SQL parser: `sqlglot` (Python) vs. write a tiny PEG for the SELECT subset. Lean toward `sqlglot` — it gives us AST + transformation primitives for free.
- [ ] Policy DSL: Rego (OPA) vs. a smaller embedded DSL. Lean toward a tiny embedded DSL for the prototype, OPA in the production design.
- [ ] Materialization engine for prototype: skip entirely (in-memory join only) — call it out as a deferred design point.
- [ ] Async path: prototype with Postgres + cron worker; mention Temporal as the production target.
