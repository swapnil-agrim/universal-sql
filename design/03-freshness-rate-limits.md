# Freshness & Rate-Limit Governance — Deep Dive

> Companion to [01-architecture.md](01-architecture.md). Targets the
> "Freshness & Rate-Limits" rubric line (15%) with explicit decision trees,
> failure modes, and concrete numbers.

## 1. Why this is its own document

Every cross-source query trades two scarce resources against each other:

- **Source rate-limit budget** — finite, per-app, per-customer
- **Data freshness** — implicit user expectation that "now" means "now"

These resources interact: burn budget for freshness, tolerate staleness to
save budget. The platform's job is to make the trade-off **explicit and
per-query**, not hidden in connector code.

---

## 2. The freshness contract

### 2.1 Three cache layers, three TTLs

| Layer | Scope | Storage | Default TTL | Eviction |
|---|---|---|---|---|
| **L1** in-memory | Per pod | Python LRU + asyncio lock | 60 s | LRU + TTL |
| **L2** distributed | Cluster-wide | Redis cluster | 300 s | TTL + LFU |
| **L3** conditional | Source HTTP | ETag store in Redis | indefinite | beat by `Last-Modified` |

L1 absorbs same-pod repeated queries (dashboard refreshes hitting the
same backend pod). L2 is the cross-pod cache. L3 turns "cached but not
fresh enough for this query" into a 304 Not Modified probe — preserves
freshness without burning the rate-limit budget.

### 2.2 The `max_staleness` SQL hint

```sql
SELECT ... WITH max_staleness = '5m'
```

The planner walks this state machine **per source, per query**:

```
                     max_staleness arrives
                              │
                              ▼
                   ┌────────────────────┐
                   │ cache.age ≤ Δ?     │── yes ──► return cache (L1/L2 hit)
                   └────────┬───────────┘
                            no
                            │
                            ▼
                   ┌────────────────────┐
                   │ ETag + budget for  │── yes ──► conditional fetch
                   │ a probe (1 unit)?  │            ├ 304 → touch + return
                   └────────┬───────────┘            └ 200 → cache + return
                            no                       (L3 hit)
                            │
                            ▼
                   ┌────────────────────┐
                   │ Budget for a full  │── yes ──► full fetch + cache
                   │ fetch?             │
                   └────────┬───────────┘
                            no
                            │
                            ▼
                   ┌────────────────────┐
                   │ allow_stale_on_    │── yes ──► return cache + STALE_DATA
                   │ throttle?          │            (warning, not failure)
                   └────────┬───────────┘
                            no
                            ▼
                  RATE_LIMIT_EXHAUSTED + Retry-After
```

Four outcomes, each observable in the response envelope:
`cache_status` per source, `freshness_ms`, `rate_limit_status`. No
hidden state — the user can always see why their query landed where it
did.

### 2.3 Cache-stampede protection

A naive design fails on TTL expiry: 50 concurrent queries all miss the
cache and hit the source simultaneously. Three controls:

- **Single-flight**: one in-flight fetch per cache key. Concurrent waiters
  attach to the same future. (`asyncio.Lock` keyed by `(tenant, table,
  predicate-hash)`; production uses a Redis-backed dedupe key with TTL.)
- **Jittered TTL**: actual expiry = `TTL ± 10%` random jitter. Prevents
  synchronised expiry of related keys.
- **Stale-while-revalidate**: when `cache.age > 0.8 × TTL`, fetch in the
  background and return cached immediately. Foreground latency stays
  flat across the refresh boundary.

### 2.4 Per-source freshness contracts

Connectors carry a recommended floor in their capability descriptor:

```yaml
github.pull_requests:
  freshness:
    min_recommended_max_staleness: 60s   # don't promise fresher than this
    typical_update_lag: 5-30s            # advisory metric
    etag_supported: true                 # enables L3
    last_modified_supported: false       # GitHub does not expose this
```

Planner refuses `max_staleness < min_recommended_max_staleness` with
`STALE_DATA_PROMISE_VIOLATION`. Better to push back than lie.

---

## 3. Rate-limit governance

### 3.1 Three nested buckets, atomic Lua

Production: token buckets in Redis with one Lua script that acquires
across all three scopes atomically, decrements on full pass, and rolls
back on any failure.

```lua
-- pseudocode; real implementation handles refill from elapsed time
local function try_acquire(key, n)
    local b = redis.call('HMGET', key, 'tokens', 'last')
    refill(b, now)
    if b.tokens < n then
        return {false, retry_after(b, n)}
    end
    redis.call('HMSET', key, 'tokens', b.tokens - n, 'last', now)
    return {true, 0}
end

local g = try_acquire(KEYS[1], ARGV[1])  -- global
if not g[1] then return {false, 'global', g[2]} end

local t = try_acquire(KEYS[2], ARGV[1])  -- tenant
if not t[1] then refund(KEYS[1], ARGV[1]); return {false, 'tenant', t[2]} end

local u = try_acquire(KEYS[3], ARGV[1])  -- user
if not u[1] then refund(KEYS[1], ARGV[1]); refund(KEYS[2], ARGV[1])
                return {false, 'user', u[2]} end

return {true, 'ok', 0}
```

One Redis round-trip = no race window. The prototype's
[`app/rate_limit.py`](../prototype/backend/app/rate_limit.py) implements
the same logic in-process; the production swap is identical semantics
across pods.

### 3.2 Budget borrowing — the fairness multiplier

Default token-bucket quotas leave money on the table when one tenant is
idle and another is busy. Idle tenants donate **up to 50% of their
unused budget per minute** to a per-connector borrowing pool. Busy
tenants can draw from the pool **up to 2× their nominal quota**, capped
per minute.

| Tenant | Nominal | Actual usage | Net via borrowing |
|---|---|---|---|
| A (idle dev tenant) | 100/min | 5/min | Donates 47/min |
| B (production traffic) | 100/min | 195/min | Borrowed 95/min |

The hard cap (`2 × nominal`) prevents one greedy tenant from
monopolising the source-side budget when a second busy tenant arrives.

The response envelope exposes `effective_budget` and `borrow_consumed`
so users see why their query succeeded under throttling.

### 3.3 Per-source shaping

Each connector ships its source's known limits:

```yaml
github:
  source_limits:
    requests_per_hour: 5000              # GitHub authenticated cap
    secondary_throttle: true              # GitHub's mystery throttle
    burst_capacity: 100                   # token-bucket capacity
  budget_split:
    sync_share: 0.6                       # 60% reserved for sync queries
    async_share: 0.4                      # 40% reserved for async overflow
```

The async pool is intentionally separate so dashboard queries don't
starve a long-running export. Sync vs async budgets are enforced as
sibling buckets, not by quota borrowing.

### 3.4 Friendly error vocabulary

```json
HTTP/1.1 429 Too Many Requests
Retry-After: 13
X-RateLimit-Connector: github
X-RateLimit-Scope: user

{
  "code": "RATE_LIMIT_EXHAUSTED",
  "message": "GitHub user-scope budget exhausted",
  "retry_after": 12.3,
  "details": {
    "scope": "user",
    "connector": "github",
    "consumed": 60,
    "budget": 60,
    "borrow_attempted": true,
    "borrow_available": 0,
    "async_url": "/v1/jobs/abc-123"
  }
}
```

`async_url` is always present when the query is async-eligible, so the
client can opt into the slower path with one redirect.

### 3.5 Noisy-neighbour isolation test

Required before GA (M5 acceptance criterion):

| Setup | Expected |
|---|---|
| Tenant A: 50% of nominal global budget, normal load | P95 latency stable |
| Tenant B: spam at 5× their quota | Rejected at 2× nominal ceiling |
| Tenant A's P95 degradation | < 10% |

Without budget borrowing this test fails (B starves A). With borrowing
capped at 2× nominal, B is contained at exactly that ceiling and A
keeps its fair share.

---

## 4. The freshness × budget interaction

The single decision the planner actually makes:

```
                       max_staleness
                         /         \
                    < floor        ≥ floor
                     /                \
              Reject               cache hit?
              with                  /         \
              STALE_DATA_         yes          no
              PROMISE_             |          /  \
              VIOLATION         return     budget?
                                cache       /     \
                                          yes      no
                                           |        \
                                       Conditional   STALE_DATA
                                       (1 unit)      (allow flag)
                                                       OR
                                                     RATE_LIMIT_
                                                     EXHAUSTED
```

Granularity is the SQL query — not a global "stale or fresh" mode. A
query willing to accept 5-minute staleness gets one budget treatment;
a real-time query right next to it gets another.

---

## 5. Failure modes — named and answered

| Failure | Detection | Response |
|---|---|---|
| Cache stampede on TTL expiry | Single-flight key counter > 0 | All but one waiter blocks on the same future |
| Source returns 429 mid-fetch | HTTP status | Exponential backoff (capped); circuit breaker trips after 5 failures in 60s |
| Schema drift mid-fetch | Connector validates response shape against descriptor | Emit `SCHEMA_DRIFT`; admin alert; refuse cached writes for that signature until human triage |
| Vault/KMS unavailable | Connector worker fails secret fetch | Cached DEK with 15-min TTL covers brief outages; longer outages → fail-secure (refuse all queries) |
| Redis cluster failover | Lua script returns `MOVED` | Client retries against new primary; one query gets a 1-2 s tail |
| ETag drift (source forgets) | 200 with same body received | Cache continues, but `freshness_ms` will read 0 — a known inflation risk |
| Borrowing pool starved | All tenants busy | All requests denied at nominal; borrowing pool refills on next minute |

---

## 6. Observability surface

**Per-query (in response envelope):**
- `freshness_ms` — age of returned data
- `cache_status` — hit/miss per source
- `rate_limit_status` — ok / borrowed / async_rerouted

**Per-tenant dashboard:**
- Cache hit ratio (target ≥ 70 % steady-state)
- Effective budget consumed / nominal (target < 80 %)
- Borrow rate (low for healthy tenants; high signals abuse)
- Source 429 count (early warning of upstream squeeze)
- L3 hit ratio — proves ETag flow is alive

**Per-source dashboard:**
- Current budget remaining
- 429s received from upstream
- Conditional vs full fetch ratio
- ETag staleness distribution (catches sources that mis-implement
  conditional requests)

---

## 7. What the prototype demonstrates

The prototype's [`app/rate_limit.py`](../prototype/backend/app/rate_limit.py)
and [`app/freshness.py`](../prototype/backend/app/freshness.py) implement
the in-process versions of every mechanism above except budget
borrowing (M3). The production gap is documented in the prototype
README and tracked in the execution plan.

The k6 run captured in `prototype/evidence/load-test-results.md`
demonstrates the cache-hit dominance the architecture relies on:
**56,201 hits / 23 misses over 60 s** at 700 RPS — the freshness layer
absorbed 99.96% of would-be source calls.
