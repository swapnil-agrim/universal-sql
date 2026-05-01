# Runbook — Cache stampede

> Many concurrent queries hit a cold cache key simultaneously, all
> miss, all fan out to the source, source rate-limits or chokes,
> latency spikes for everyone.

---

## 1. Trigger / alert

Fires when **all** of the following hold for ≥ 1 minute:

- Cache hit ratio drops below 30% (steady state target ≥ 70%):
  `sum(rate(connector_request_duration_seconds_count{cache_status="hit"}[1m])) / clamp_min(sum(rate(connector_request_duration_seconds_count[1m])), 0.0001) < 0.3`
- Connector P95 latency > 1s
- Source 429 rate > 1/s OR source P95 > 2s

## 2. Severity

| Condition | Severity |
|---|---|
| One source, < 5 minutes | **SEV-3** |
| Multiple sources OR cascading source 429s | **SEV-2** |
| Gateway P95 > 5s OR availability dropping | **SEV-1** |

## 3. Symptoms

- Sudden drop in cache hit ratio on Grafana dashboard
- Spike in `connector_request_duration_seconds{cache_status="miss"}`
- User-visible: queries slow; some hit `RATE_LIMIT_EXHAUSTED` at the source
- Source returning 429s or slow responses
- May follow a deployment, a cache flush, or a mass TTL expiry

## 4. Immediate actions

1. **Confirm stampede signature:** Grafana — cache hit ratio panel cliffed,
   `connector_request_duration_seconds{cache_status="miss"}` panel spiked.
2. **Identify the cache key family** — which `(tenant, table, predicate-shape)`
   is the most-missed?
   `topk(5, sum by (tenant, connector) (rate(connector_request_duration_seconds_count{cache_status="miss"}[2m])))`
3. **Check source health:** if source is hot, prioritise Section 6a (rate
   relief) over Section 6b (cache rebuild).
4. **Open incident channel.**

## 5. Diagnosis

### Was it caused by our deploy?
- A recent restart drops L1 caches across all pods.
- L2 (Redis) should still hold most data — check Redis hit ratio.
- If Redis is also cold, was it flushed or restarted?

### Was it caused by mass TTL expiry?
- Did jitter fail? Check for synchronised TTL across many keys.
- Look at `cache_evictions_total` for an eviction spike.

### Was it source recovery from an outage?
- During outage, queries fall through with `STALE_DATA`. When source
  recovers, all clients hit it at once.

## 6. Mitigation

### 6a. Source-protective mode (FIRST priority if source is squeezed)
- Temporarily raise `max_staleness` floor for the affected source: edit
  the connector's `min_recommended_max_staleness` from 60s → 300s.
- This forces clients to accept slightly older data; takes pressure off source.
- Single-flight already prevents waiters from each calling source — but if
  it's bypassed (deploy reset), this is the bigger lever.

### 6b. Pre-warm the cache
- Identify hot keys from logs.
- Run a pre-warming script that fetches each hot `(tenant, table,
  predicate-shape)` once with a long TTL.
- This burns budget but typically less than the stampede burns.

### 6c. Stagger TTL refresh
- If diagnosis shows synchronised TTL expiry: temporarily increase jitter
  window from ±10% to ±30%.
- Helm value: `freshness.jitter_pct: 30`.
- Redeploy via canary.

### 6d. Single-flight broken?
- If two pods both hit source for the same key, single-flight (Redis-backed
  in production) is malfunctioning.
- Check Redis cluster health; check for our `inflight:<key>` entries
  not being cleaned up.
- Restart connector worker pods if locks are stuck.

## 7. Recovery

- Cache hit ratio back ≥ 70% (steady state target).
- Connector P95 < 800 ms.
- Source 429 rate at zero or below pre-incident baseline.
- Status page → green.

## 8. Post-mortem checklist

- [ ] Did single-flight prevent fanout, or fail open?
- [ ] What was the trigger — deploy, TTL expiry, source recovery, or
      something else?
- [ ] Should we add a cache pre-warming step to deploy automation?
- [ ] Should the TTL jitter default be wider?
- [ ] Did stale-while-revalidate (SWR) trigger? If not, is it wired up?
- [ ] Was the customer impact within SLO?
- [ ] Add a chaos drill for this scenario if not already scheduled (M6).
