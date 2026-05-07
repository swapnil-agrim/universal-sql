# Deferred Items — what's not in the prototype and when each lands

> Canonical list of every capability that is **specified in the design**
> but **not implemented in the M1 prototype**. Every "📋 design only"
> entry across [`../summary.md`](../summary.md),
> [`../prototype/README.md`](../prototype/README.md), and the design
> docs has a row here with a target milestone and rationale.

---

## 1. Why this list exists

The prototype is an M1 vertical slice — every architectural seam is wired
end-to-end with simplified mechanisms. Many production-grade pieces are
explicitly deferred to specific milestones. This is the **canonical
record**, so a reviewer can verify nothing slipped through unannounced.

Deferral is a leadership signal: each row is a deliberate scope decision
with rationale, not an oversight.

---

## 2. Master deferral table

| # | Capability | Prototype substitution today | Milestone | Why deferred |
|---|---|---|---|---|
| 1 | OIDC JWT verification at gateway | `X-User-Id` header → policy YAML lookup | **M2** | Auth integration is per-tenant; needs IdP onboarding starting in M3 |
| 2 | Per-tenant KMS via Vault (envelope encryption) | Env vars; tenant-scoped cache keys; no encryption at rest | **M2** | Needs Vault deployed first; not on M1 critical path |
| 3 | Multi-tenant Helm chart (namespace per tenant) | Single docker-compose deploy | **M2** | Single-binary M1 sufficient to prove architecture |
| 4 | k8s cluster + Terraform modules (VPC, EKS, KMS, RDS) | docker-compose locally | **M2** | Deployment is M2; M1 proves the code |
| 5 | Cross-pod rate-limit state (Redis + Lua atomic acquire) | In-process asyncio token buckets | **M2** | Single-process M1; horizontal scale starts M2 |
| 6 | Distributed freshness cache (Redis L2 + ETag L3) | In-process LRU + TTL only | **M2** | Same — single-process |
| 7 | OpenTelemetry trace shipping to Tempo/OTLP collector | ConsoleSpanExporter (logs) | **M2** | Console is fine for M1 evidence; collector lands with k8s |
| 8 | OPA/Rego policy DSL with CI validator | YAML embedded engine + Python evaluator | **M3** | Proto YAML proves the model; OPA needed for production governance |
| 9 | Audit log writer to Kafka + S3 object-lock | OTel span attributes (audit-shaped) | **M3** | Trace attrs already audit-shaped; Kafka + S3 is the production lift |
| 10 | Async overflow path (Temporal workflow + push notification) | Sync only; full path documented | **M3** | Sync path enough to prove rate-limit + budget handling |
| 11 | Operational runbooks live (rate-limit flood, connector auth failure, cache stampede, KMS unavailable) | Specced in [`../design/runbooks/`](../design/runbooks/) | **M3** | Runbooks land with the on-call rotation |
| 12 | DPA template + Legal review | None | **M3** | Lands with first design-partner Stage-2 (see Design-partner ladder) |
| 13 | DuckDB ephemeral execution mode | In-memory hash join only | **M4** | Prototype data sizes don't need DuckDB |
| 14 | ClickHouse short-lived materialisation (per-tenant TTL ≤ 5 min) | None | **M4** | Hot-query promotion is an optimisation, not architecture proof |
| 15 | Cardinality estimator (capability bounds + EWMA + cheap probe) | Simple row count from connector | **M4** | Estimator drives mode picking; only needed when modes exist |
| 16 | HPA + cluster autoscaler with cost guardrails | Manual replicas | **M4** | Comes with k8s; M2 deploys static, M4 scales dynamically |
| 17 | Canary + automated rollback on SLO regression | Direct deploy | **M4** | Needs SLO instrumentation in place first |
| 18 | Postgres metadata catalog with versioning + Flyway migrations | In-memory catalog from descriptors | **M4** | Catalog versioning is M4 deliverable |
| 19 | Single-tenant Helm variant (`tenancy=single`) | None | **M4** | Variant of M2 chart; lands with Helm M4 work |
| 20 | Semi-join pushdown optimisation (extract IN-list to second source) | None — naive hash join | **M4** | Needs cardinality estimator (#15) first |
| 21 | 5 production-ready connectors (Salesforce + Zendesk + Notion in addition to GitHub + Jira) | 2 mocked (GitHub + Jira) | **M5** | 2 prove the connector pattern; breadth is engineering |
| 22 | Live-mode connector HTTP implementation (real GitHub / Jira API calls) | Mock connectors only | **M5** | `CONNECTOR_MODE=live` defined in `settings.py` but not implemented |
| 23 | Connector SDK v1 (token-refresh hooks, pagination protocol, drift detection) | SDK v0 | **M5** | v0 sufficient for 2 connectors; v1 needed for breadth |
| 24 | Per-tenant cost guardrails (query budget rejection) | None | **M5** | Cost data lands M4; enforcement at M5 |
| 25 | Residency-tag enforcement (admission controller + scheduler annotations) | None | **M5** | Multi-region needs to exist first |
| 26 | Crypto-shred drill — automated KMS-revoke flow with verification | Documented in `04-security.md §7` | **M5** | Drill requires KMS (#2) + multi-tenant data (#3) live |
| 27 | DR / BCP playbook with RPO ≤ 15 min, RTO ≤ 1 h | Multi-AZ design discussed | **M5** | M5 explicitly delivers; drill executes |
| 28 | Sync vs async budget split per connector | Single budget pool | **M5** | Both lanes need to exist; async lands M3, split lands M5 |
| 29 | STRIDE threat-model document signed off by Security | Threat model in `04-security.md` | **M5** | Document exists; formal sign-off lands with pen-test scoping |
| 30 | Pen-test vendor SoW signed | None | **M5** | Procurement starts M3; SoW lands M5 |
| 31 | Budget borrowing across tenants (idle donates to busy, 2× cap) | Hierarchical buckets without borrowing | **M3 / M5** | Mechanism lands M3; per-source tuning M5 |
| 32 | Connector marketplace UI scaffold | None | **M5** | UI shell only; full marketplace post-GA |
| 33 | Admin console v1 (connector config, policy editor, tenant management, audit-log viewer) | API only | **M6** | Self-serve onboarding ships at GA |
| 34 | Self-serve tenant onboarding flow | Manual | **M6** | Same — GA scope |
| 35 | Chaos drill execution — full 12-scenario game day | Plan in `../design/06-chaos-plan.md` | **M6** | Dry-run M5; full game day M6 |
| 36 | External pen-test execution | Plan in `04-security.md` | **M6** | Vendor scoped M5; executed M6 |
| 37 | SOC 2 Type 1 audit | None | **M6** | Standard pre-GA sequence; control mapping starts M5 |
| 38 | Tier-1 customer support lane with per-partner SLA | None | **M6** | Lands with first production design partner |
| 39 | GA documentation (admin guide, connector author guide, policy DSL ref, security whitepaper, DPA template) | Internal-only docs | **M6** | Public docs freeze at GA |
| 40 | Status page + synthetic monitors | None | **M3** | Lands with on-call rotation |

---

## 3. By milestone — what lands when

| Milestone | Window | Capabilities (refs above) |
|---|---|---|
| **M2** Productionisation: observable + multi-tenant | Sprints 3–4 | #1 OIDC, #2 KMS+Vault, #3 multi-tenant Helm, #4 Terraform/EKS, #5 Redis rate-limit, #6 Redis freshness, #7 OTLP collector |
| **M3** Resilience: throttling UX + policy enforcement | Sprints 5–6 | #8 OPA/Rego, #9 audit log, #10 async overflow, #11 runbooks, #12 DPA, #31 budget borrowing core, #40 status page |
| **M4** Scale: elasticity + materialisation | Sprints 7–8 | #13 DuckDB, #14 ClickHouse, #15 cardinality estimator, #16 autoscaler, #17 canary, #18 catalog versioning, #19 single-tenant Helm, #20 semi-join |
| **M5** GA-readiness: breadth + security depth | Sprints 9–10 | #21 5 connectors, #22 live mode, #23 SDK v1, #24 cost guardrails, #25 residency, #26 crypto-shred drill, #27 DR/BCP, #28 sync/async split, #29 STRIDE sign-off, #30 pen-test SoW, #31 borrowing tuning, #32 marketplace UI |
| **M6** GA: ship-ready | Sprints 11–12 | #33 admin console, #34 self-serve onboarding, #35 chaos drill execution, #36 pen-test execution, #37 SOC 2 Type 1, #38 support lane, #39 public docs |

---

## 4. What we explicitly chose NOT to defer in M1

The corollary list — capabilities that *could* have been deferred but
aren't, because they're load-bearing for the architecture proof:

| Capability | Why we kept it in M1 |
|---|---|
| End-to-end `/v1/query` with full response envelope | Without it, "architecture works end-to-end" is unproven |
| RLS + CLS via YAML with red-team test coverage | Proves the entitlement composition rule (intersection, not union) |
| Hierarchical token-bucket *structure* (3 levels: connector / tenant / user) | Proves the design even without Redis-Lua atomicity |
| TTL freshness cache with `cache_status` per source in response | Proves the freshness contract is honoured per-query |
| OTel tracing + Prometheus metric + Grafana dashboard | Proves observability seam is wired, not an afterthought |
| k6 700 RPS load test | Proves the SLO target is achievable (P95 6.59 ms vs 1500 ms budget) |
| Per-query timeout + partial-results envelope | Hard PDF requirement; small code, big credibility |
| 2 connectors with capability descriptors | Less than 2 wouldn't prove the connector model scales |

---

## 5. How deferral decisions get reviewed

- **At each milestone exit:** team re-reads this list. Anything that
  hasn't landed by its target milestone gets discussed in the next
  quarterly RICE review.
- **Promotion** (pulling an item earlier than its target milestone)
  requires only EM sign-off — usually triggered by a customer
  commitment.
- **Further deferral** (pushing an item past its target milestone)
  requires EM + PM + SEC sign-off (whichever owns the gate). This
  bar is intentionally higher than promotion.
- **Cancellation** (removing an item entirely) requires the same
  sign-off as further deferral, plus an updated risk-register entry
  documenting what we're choosing to live without.

---

## 6. Where this list is referenced

| Doc | How it uses this list |
|---|---|
| [`../summary.md`](../summary.md) §3 | Short version (the "📋 design only" rows) |
| [`../prototype/README.md`](../prototype/README.md) "Trade-offs" | Production-vs-prototype substitutions |
| [`../prototype/ARCHITECTURE.md`](../prototype/ARCHITECTURE.md) §10 | Mocked vs real — what's implemented in the prototype |
| [`02-execution-plan.md`](02-execution-plan.md) §5 | M1–M6 milestone deliverables (where these items land) |
| [`sprint_planning.md`](sprint_planning.md) §3 | Per-sprint task allocation (which sprint each item lands in) |

When any of those docs change, this list should be reconciled.
