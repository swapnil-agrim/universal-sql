# Universal SQL — Design Doc

> Take-home: design a universal SQL query layer over many SaaS apps.
> Four files in this folder cover system design; the operational
> roadmap and sprint plan live in [`../planning/`](../planning/).

| # | File | What's inside | Rubric line |
|---|---|---|---|
| 01 | [Architecture](01-architecture.md) | Scenario lock, system diagram, 6 bold design calls, request flow, error vocabulary, tenant isolation matrix | Architecture & Trade-offs (30%) |
| 03 | [Freshness & rate-limits](03-freshness-rate-limits.md) | Three cache layers, max_staleness state machine, hierarchical token buckets, budget borrowing, named failure modes | Freshness & Rate-Limits (15%) |
| 04 | [Security](04-security.md) | STRIDE, four-layer isolation, entitlement composition rule, audit format, residency, crypto-shred | Security & Entitlements (15%) |
| 05 | [Capacity at 1k QPS](05-capacity-1k-qps.md) | Latency budget walkthrough, Little's Law sizing, $21k/month cost model, bottleneck succession to 10k QPS | Architecture (bonus depth) |
| 06 | [Chaos plan](06-chaos-plan.md) | 12 scenarios with hypothesis + injection + pass criteria, game-day process, error-budget impact, claim → test mapping | Architecture & Trade-offs (bonus) |

## Companion folders

- [`../planning/`](../planning/) — Six-month execution plan + 12-sprint
  schedule with Mermaid Gantt and per-role task allocation. Rubric line:
  Execution Plan (15%).
- [`../prototype/`](../prototype/) — Working FastAPI + Next.js prototype
  with k6 load test, Grafana dashboard, and captured evidence.
- [`runbooks/`](runbooks/) — Operational playbooks for rate-limit flood,
  connector auth failure, cache stampede.
- [`diagrams/`](diagrams/) — Rendered system-architecture diagram
  (PNG / SVG / Mermaid source).

## Reading order suggestions

- **For a 10-min scan:** the architecture doc only — diagram + 6 bold calls + flow.
- **For a hiring committee:** 01 (system) + ../planning/02-execution-plan.md (operations).
- **For a deep technical review:** all four design docs in order, then the planning folder, then the prototype.
- **By rubric line:** the tables here and in `../planning/README.md` map each rubric weight to the document that defends it.

The numbering skips 02 because the execution plan moved to
`../planning/` — kept gap rather than renumber to preserve external
links.
