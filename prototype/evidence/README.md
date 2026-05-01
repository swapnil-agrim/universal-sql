# Evidence — what these artifacts prove

Captured from a clean run of the prototype. They're committed so the
submission reviewer can see real output without spinning up the stack.

| File | What it shows |
|---|---|
| `sample-query-response.json` | Single `POST /v1/query` envelope (rows + freshness + trace) |
| `otel-trace-sample.txt` | OpenTelemetry span dump for one query (planner → fetch_all → connector spans) |
| `sample-metrics.txt` | Prometheus exposition excerpt — the rubric-required histogram |
| `grafana-dashboard.png` | Grafana dashboard mid-run during 700 RPS k6 test |
| `grafana-dashboard-final.png` | Same dashboard immediately after the run, showing full envelope |
| `k6-summary.txt` | Raw k6 console output |
| `load-test-results.md` | Annotated load-test summary — start here |


## `sample-query-response.json`
A single `POST /v1/query` round-trip for the cross-app reference query
(GitHub PRs ↔ Jira issues, joined on issue key, filtered to `acme/api`,
LIMIT 5). Confirms:

- Cross-source join executed correctly (rows contain both `number/title`
  from GitHub and `key/status/assignee` from Jira).
- CLS column mask applied — `assignee` is `[REDACTED]` because the calling
  user (`alice`) does not have the `manager` role.
- Response carries the full metadata envelope: `freshness_ms`,
  `rate_limit_status`, `trace_id`, `cache_status` per source,
  `rows_per_source` post-pushdown.

## `otel-trace-sample.txt`
Span dump from the OpenTelemetry ConsoleSpanExporter for the same query.
Three spans share one `trace_id`:

- `planner.execute` (root) — entire request lifetime
- `planner.fetch_all` (child) — parallel fan-out
- `connector.github.fetch` and `connector.jira.fetch` (siblings under
  `fetch_all`) — each carries `connector.name`, `predicates.count`,
  `rows.count` attributes.

This is the trace screenshot equivalent the submission rubric asks for.
In production this exporter is replaced with OTLP→Tempo/Jaeger via
`OTEL_EXPORTER_OTLP_ENDPOINT`.

## `sample-metrics.txt`
Excerpt of `GET /metrics`. Shows the rubric-required metric
`connector_request_duration_seconds` exposed as a Prometheus histogram
labelled by `connector`, `tenant`, and `cache_status`. With the cache_status
label, a single PromQL expression separates cache-hit vs live-fetch
percentiles — exactly what an SRE wants to see in Grafana.

Example query for a P95 dashboard:
```
histogram_quantile(0.95,
  sum by (le, connector, cache_status) (
    rate(connector_request_duration_seconds_bucket[1m])))
```
