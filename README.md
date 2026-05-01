# Universal SQL — Eng Lead Take-Home

Cross-app SQL query layer for SaaS applications. Three deliverables in one repo:

- **[`summary.md`](summary.md)** — one-pager: requirements, status, approach, components.
- **[`design/`](design/)** — system architecture (4 docs), security, freshness/rate-limits, capacity, chaos plan, runbooks, rendered diagram.
- **[`planning/`](planning/)** — six-month execution plan, 12-sprint operational plan, rendered Gantt.
- **[`prototype/`](prototype/)** — working FastAPI + Next.js stack with k6 load test (700 RPS sustained), Grafana dashboard, captured evidence.

## Quickstart

```bash
cd prototype
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:4000 |
| Backend  | http://localhost:8000 |
| Grafana  | http://localhost:4001/d/universal-sql-main/universal-sql-gateway |
| Prometheus | http://localhost:9090 |

See [`prototype/README.md`](prototype/README.md) for failure-mode demos
and [`prototype/ARCHITECTURE.md`](prototype/ARCHITECTURE.md) for module-level internals.

## Where to start reading

| You have | Read this |
|---|---|
| 5 min | [`summary.md`](summary.md) |
| 15 min | [`design/01-architecture.md`](design/01-architecture.md) + [`prototype/evidence/load-test-results.md`](prototype/evidence/load-test-results.md) |
| 30 min | All four design docs in order |
| 60 min | + [`planning/02-execution-plan.md`](planning/02-execution-plan.md) + [`planning/sprint_planning.md`](planning/sprint_planning.md) + [`prototype/ARCHITECTURE.md`](prototype/ARCHITECTURE.md) |
