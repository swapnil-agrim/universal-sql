# Load test results — k6 × Grafana

A 60-second sustained-arrival-rate run at **700 RPS** against the live
docker-compose stack. The dashboard screenshots in this directory were
captured during and immediately after this run.

## Headline numbers (k6 summary)

| Metric | Value |
|---|---|
| Iterations completed | **42,001** |
| Sustained RPS | **699.97 req/s** (target 700) |
| Failures | **0%** |
| Latency P50 | 1.09 ms |
| Latency P90 | 3.12 ms |
| **Latency P95** | **6.59 ms** (SLO: <1500 ms — passed by ~225×) |
| Latency max | 56.48 ms |
| Cache hits / misses (per source-fetch) | 56,201 / 23 |
| Rate-limit rejections | 0 |
| Data received | 69 MB (1.2 MB/s) |

Both k6 thresholds passed:
- ✓ `http_req_duration p(95) < 1500`  → actual 6.59 ms
- ✓ `http_req_failed rate < 0.05`     → actual 0.00%

## What the screenshots prove

### `grafana-dashboard.png` — captured mid-run (~25s in)
Shows the system at peak load with k6 actively driving traffic:
- **Queries/s gauge:** 266 req/s on a 30 s rate window (still climbing toward
  the 700 RPS target as the rate window catches up)
- **P95 connector latency:** 48 ms (well inside the 1.5 s SLO)
- **Cache hit ratio:** 100 % in steady state
- **Rate-limit rejections:** None
- **P50/P95 by cache_status timeseries:** the brief "miss" spike during
  warm-up (~30 ms P95 for `github (miss)`) drops to flat near-zero as the
  cache takes over — exactly the freshness layer doing its job

### `grafana-dashboard-final.png` — captured after the run
Same dashboard with the test now visible end-to-end:
- **Throughput timeseries** shows the canonical load-test envelope:
  ramp-up → ~300 req/s plateau → ramp-down
- **Connector fetch volume** stack reaches 400 ops/s at peak (200 each from
  GitHub and Jira hits) — proving every query touched both sources, served
  from cache
- The single tiny "github miss" notch at the start of the run is the only
  live source fetch needed for the entire 60 seconds

## Why the dashboard's plateau reads ~300 req/s vs k6's measured 700 RPS

The backend container runs **2 uvicorn workers** for resilience. The
`prometheus-client` Python library keeps counters in-process per worker,
so when Prometheus scrapes `/metrics` it reaches one worker round-robin
and sees roughly half the global counter. This is the documented
multi-process behaviour of the upstream library. Production uses
`multiprocess_mode` (file-based aggregation) or runs a single worker
behind k8s replicas. The k6 client-side count of 700 RPS is the truth.

## How to reproduce

```bash
cd prototype
docker compose up --build -d

# Warm cache (optional — gives a more realistic steady-state shape)
for i in 1 2 3; do
  curl -s -X POST http://localhost:8000/v1/query \
    -H 'Content-Type: application/json' -H 'X-User-Id: alice' \
    -d '{"sql":"SELECT pr.number FROM github.pull_requests AS pr WHERE pr.repo='\''acme/api'\'' LIMIT 5"}' \
    > /dev/null
done

# Run the load test
docker run --rm --network host \
  -v "$PWD/load-test":/scripts \
  -e BACKEND_URL=http://localhost:8000 \
  grafana/k6:latest run /scripts/k6.js

# Open the dashboard
open http://localhost:4001/d/universal-sql-main/universal-sql-gateway
```

Anonymous access is enabled (`GF_AUTH_ANONYMOUS_ENABLED=true`,
`GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`) so the dashboard loads without a
login prompt. For non-anonymous mode, the seeded credentials are
`admin / admin`.
