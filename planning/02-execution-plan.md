# Six-Month Execution Plan — Universal SQL Platform

> Planning approach: **Strategy → Themes → Initiatives → Governance.**
> Anchored in shared business outcomes, not a feature list. Every milestone
> exit criterion ladders to a north-star metric.

---

## 1. North-Star Outcomes

| Outcome | Why it matters |
|---|---|
| **Time-to-value** | Faster onboarding = faster sales cycle = larger TAM |
| **Agent productivity** | Ema's AI agents are the actual product; they need real-time, governed cross-app access |
| **Enterprise trust** | Security/compliance posture is what closes F500 deals |
| **Unit economics** | At 10M users and 1k QPS, sub-cent cost-per-query is what makes the business work |

---

## 2. North-Star Metrics (shared scorecard)

| Outcome | Metric | M6 GA target |
|---|---|---|
| Time-to-value | Median hours from contract → first query | ≤ 24 |
| Time-to-value | New connector ship time | ≤ 5 dev-days |
| Agent productivity | Query P95 (single-source pushdown) | < 1.5 s |
| Agent productivity | Gateway availability (monthly) | 99.9% |
| Enterprise trust | Cross-tenant leakage incidents | 0 |
| Enterprise trust | Audit-trail coverage of cross-system access | 100% |
| Unit economics | Cost / 1000 queries | ≤ $0.50 |
| Unit economics | Idle-tenant overhead / month | ≤ $20 |

---

## 3. Engineering Themes

| Theme | Serves outcome | What's inside |
|---|---|---|
| **A. Connector velocity** | Time-to-value, Agent productivity | SDK, capability descriptors, contract tests, generators |
| **B. Query intelligence** | Agent productivity, Unit economics | Planner, pushdown, three-mode execution, freshness layer |
| **C. Trust fabric** | Enterprise trust | Entitlements DSL, per-tenant KMS, audit, residency, threat model |
| **D. Operational maturity** | Agent productivity, Unit economics | Observability, autoscaling, cost guardrails, DR/BCP |
| **E. Self-serve onboarding** | Time-to-value | Admin console, policy editor, tenant provisioning |

---

## 4. Team Shape (~7.5 FTE)

| Role | FTE | Theme ownership |
|---|---|---|
| Engineering Manager | 1.0 | Cross-theme; runs roadmap + exec readouts |
| Tech Lead / Staff Eng | 1.0 | Theme B (planner) + architecture authority |
| Backend Eng | 2.0 | Theme A (connectors), Theme C (entitlement service) |
| Platform / Infra Eng | 1.0 | Theme D (k8s, Terraform, observability) |
| Security Eng | 0.5 | Theme C (threat model, KMS, audit, pen-test prep) |
| QA / SDET | 1.0 | Theme A & D (contract tests, k6, chaos drills) |
| Product Manager | 0.5 | Theme A & E (connector prioritization, design partners) |
| Developer Experience | 0.5 | Theme A & E (SDK ergonomics, public docs) |

**Flex:** Security ramps to 1.0 in M5–M6 for pen-test prep. PM doubles in M3 when design partners onboard. Hiring kicks off M0.

---

## 5. Six-Month Roadmap

### Phase 1 — Foundations (M1–M2): "Prove the architecture"

**M1 — Demonstrable end-to-end vertical slice**

| Theme | Deliverable |
|---|---|
| A | Connector SDK v0 (Python); 2 reference connectors (GitHub, Jira); capability descriptors |
| B | SELECT/WHERE/LIMIT planner; predicate pushdown; in-memory join only |
| C | Entitlement service skeleton (YAML policies, table-level grants); single-tenant deploy |
| D | Docker Compose dev env; structured logging |

**Exit:**
- 1 internal tenant runs GitHub↔Jira reference query end-to-end
- New connector "hello world" ships in ≤ 4 hours (DX measurement)
- Rate-limit guardrail validated at 110% budget; returns `RATE_LIMIT_EXHAUSTED` + `Retry-After`

**M2 — Observable and multi-tenant**

| Theme | Deliverable |
|---|---|
| B | Cardinality estimator v0; DuckDB execution path; freshness layer (TTL + ETag) |
| C | Per-tenant KMS via Vault; multi-tenant deploy on k8s namespaces |
| D | OpenTelemetry traces; Prometheus metrics; Grafana v1 |

**Exit:**
- P95 < 1.8 s for single-source predicate-pushdown queries
- Two tenants share a cluster; zero cross-tenant data in traces/logs
- Trace shows per-source connector time

---

### Phase 2 — Productionization (M3–M4): "Real-time, resilient, governed"

**M3 — Clean UX under throttling, policy enforcement**

| Theme | Deliverable |
|---|---|
| B | Async overflow path (Temporal + push notification); error vocabulary finalized |
| C | Policy DSL (RLS + CLS); policy → plan compiler; per-tenant audit log |
| D | Status page; error budget tracking; on-call rotation; runbooks for top 3 failure modes |

**Exit:**
- Throttled load test: graceful degradation; actionable error or async path always
- RLS/CLS verified by red-team suite (3 scenarios; 0 leaks)
- Audit log: 100% cross-system access coverage

**M4 — Scale and elasticity**

| Theme | Deliverable |
|---|---|
| B | ClickHouse materialization; semi-join pushdown; mode-pick finalized |
| D | HPA + cluster autoscaler with cost guardrails; Helm chart for multi/single-tenant; Terraform modules; canary + auto-rollback |

**Exit:**
- 1k QPS for 60s with P95 < 1.5 s (SLO match)
- Single-tenant deploy from same Helm chart via one values flag
- Cost / 1000 queries ≤ $0.75

---

### Phase 3 — GA Readiness (M5–M6): "Harden and scale"

**M5 — Connector breadth, security depth**

| Theme | Deliverable |
|---|---|
| A | 5 production-ready connectors (add Salesforce, Zendesk, Notion); contract test suite |
| C | STRIDE threat model; pen-test readiness; automated off-boarding (crypto-shred); residency enforcement |
| D | Per-tenant cost guardrails; perf tuning; multi-AZ + multi-region active/passive design |

**Exit:**
- Perf & cost report: SLOs met across 5 connectors; cost ≤ $0.50 / 1k queries
- Off-boarding drill: < 5 min, KMS revoked, no residual data
- Pen-test scoping signed by external vendor

**M6 — GA sign-off**

| Theme | Deliverable |
|---|---|
| E | Admin console v1 (connector config, policy editor, tenants); self-serve onboarding |
| D | Chaos drills (rate-limit flood, source outage, cache stampede, KMS unavailability); GA runbook |
| C | External pen-test; findings triaged |

**Exit:**
- All 8 north-star metrics green
- 3 design-partner tenants in production ≥ 2 weeks
- Onboarding median ≤ 24 hours
- Onboarding playbook published

---

## 6. Operating Cadence & Governance

| Cadence | What |
|---|---|
| Weekly | Engineering standup; theme leads sync (15 min); design-partner office hours |
| Bi-weekly | Demo at milestone exit; sprint review with PM |
| Monthly | Stakeholder review with shared scorecard (north-stars + theme progress + risk delta) |
| Quarterly | Roadmap re-planning with **RICE / Impact–Effort** scoring; risk-register refresh; budget review |
| Continuous | Error-budget tracking; cost dashboard; design-partner NPS |

**Exec readouts are outcome-first.** Example:
> "Tenant onboarding median dropped 7 days → 30 hours this month — driven by SDK boilerplate generator and admin-console alpha. Trade-off: pushed materialization layer one milestone. Risk delta: connector variability medium → low."

**RICE on the backlog quarterly** — Reach × Impact × Confidence ÷ Effort. Removes "loudest voice wins."

---

## 7. Risk Register

| # | Risk | Prob. | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | Connector variability (auth quirks, hidden rate limits) | High | Med | Capability descriptors with empirical limits; weekly contract tests; per-connector circuit breakers | Backend |
| R2 | Source quota exhaustion under load | Med | High | Hierarchical token buckets; tenant budgets; async overflow; 70/90% budget alerts | TL + Infra |
| R3 | Schema drift in SaaS sources | High | Med | Connector versioning; contract tests; admin drift alerts; graceful `SCHEMA_DRIFT` error | Backend + DX |
| R4 | Entitlement bug → cross-tenant leak | Low | **Critical** | Policy DSL with formal semantics; red-team suite; audit review; M6 pen-test | Security |
| R5 | Cost overrun from autoscaling | Med | High | Per-tenant cost cap; query-budget rejection; weekly cost review with EM | Infra + EM |
| R6 | Cardinality estimator inaccurate early | High | Low | Conservative defaults; mid-flight escalation; EWMA pre-populated by shadow traffic | TL |
| R7 | Materialization (ClickHouse) op load | Med | Med | Managed ClickHouse Cloud; revisit self-host post-GA; runbook for TTL stalls | Infra |
| R8 | Design partners won't grant prod credentials | Med | High | Sandbox-first; mock-source mode; staged credential exchange via security review | PM |
| R9 | Hiring miss (staff/security) | Med | High | Interviewing from M0; bridge with contractors | EM |
| R10 | Compliance scope creep (SOC2 / HIPAA) | Med | Med | GA scope locked at SOC2 Type 1 only; HIPAA deferred post-GA | EM + Security |

---

## 8. Budget & Infra Assumptions

- **Cloud baseline:** k8s (3 AZ), Postgres RDS, Redis Elasticache, ClickHouse Cloud, S3+KMS → ~$8–12k/month at design-partner scale, ~$40–60k/month at GA load.
- **Vendor stack:** Vault, Temporal Cloud, Grafana Cloud (or self-host Tempo+Prom) → ~$3–5k/month.
- **Per-tenant marginal:** < $20/month idle, < $0.50 / 1000 queries active.
- **One-time:** external pen-test ~$25k, SOC2 Type 1 audit ~$30k.
- **Headcount:** ~7.5 FTE × ~$300k loaded ≈ $2.25M annualized.

---

## 9. Mapping to the take-home prototype

Prototype lands in **M1's exit criteria minus per-tenant KMS** (collapsed for time). Everything beyond is roadmap, not submission scope. The design doc tells the GA story; the prototype proves M1 is achievable.
