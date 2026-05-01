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

### 2.1 GA targets

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

### 2.2 Quarterly checkpoints — intermediate targets

GA targets aren't checkable mid-flight. Each metric has an intermediate
reading at the end of M2, M4, and M6 so we know if velocity is on track:

| Metric | M2 | M4 | M6 (GA) |
|---|---|---|---|
| Onboarding hours | n/a (no design partners) | ≤ 7 days (first migration) | ≤ 24 hours |
| Connector ship time | n/a (single connector path) | ≤ 10 dev-days (3-connector test) | ≤ 5 dev-days |
| Query P95 (single-source) | < 1.8 s (M2 exit) | < 1.5 s (M4 exit) | < 1.5 s |
| Gateway availability | n/a (single tenant) | 99.5 % on staging | 99.9 % monthly |
| Cross-tenant leakage incidents | 0 (red-team v0) | 0 | 0 |
| Audit-trail coverage | n/a (writer not deployed) | 80 % (M3 lands writer; M4 instrumentation gaps) | 100 % |
| Cost / 1000 queries | n/a | ≤ $0.75 (M4 cost report) | ≤ $0.50 |
| Idle-tenant overhead / month | n/a | ≤ $30 | ≤ $20 |

Misses at M2 / M4 trigger a re-plan, not a slip — the buffer is built
into M5–M6 by design.

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

**Staffing assumption:** all roles staffed from Sprint 1; no hiring
contingencies in plan. SEC stays at 0.5 FTE for the entire 6 months —
security-heavy implementation work (audit log writer, crypto-shred
automation, pen-test execution) is split with BE / INFRA / external
vendor; SEC owns spec, review, and validation. See
[`sprint_planning.md §4`](sprint_planning.md) for the per-sprint
load matrix that demonstrates this is sustainable.

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

**M5 — Connector breadth, security depth, DR**

| Theme | Deliverable |
|---|---|
| A | 5 production-ready connectors (add Salesforce, Zendesk, Notion); contract test suite |
| C | STRIDE threat model; pen-test readiness; automated off-boarding (crypto-shred); residency enforcement |
| D | Per-tenant cost guardrails; perf tuning; **DR/BCP playbook** with multi-AZ baseline + active/passive multi-region; **RPO ≤ 15 min, RTO ≤ 1 h** for the control plane |

**Exit:**
- Perf & cost report: SLOs met across 5 connectors; cost ≤ $0.50 / 1k queries
- Off-boarding drill: < 5 min, KMS revoked, no residual data
- Pen-test scoping signed by external vendor
- DR fail-over drill executed in staging within RPO/RTO targets

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
| R9 | Vendor procurement delay (Vault, Temporal Cloud, ClickHouse Cloud, pen-test SoW) | Med | High | Procurement starts M0 (see §9 External dependencies); fallbacks identified per vendor | EM + INFRA |
| R10 | Compliance scope creep (SOC2 / HIPAA) | Med | Med | GA scope locked at SOC2 Type 1 only; HIPAA deferred post-GA | EM + Security |

---

## 8. Budget & Infra Assumptions

- **Cloud baseline:** k8s (3 AZ), Postgres RDS, Redis Elasticache, ClickHouse Cloud, S3+KMS → ~$8–12k/month at design-partner scale, ~$40–60k/month at GA load.
- **Vendor stack:** Vault, Temporal Cloud, Grafana Cloud (or self-host Tempo+Prom) → ~$3–5k/month.
- **Per-tenant marginal:** < $20/month idle, < $0.50 / 1000 queries active.
- **One-time:** external pen-test ~$25k, SOC2 Type 1 audit ~$30k.
- **Headcount:** ~7.5 FTE × ~$300k loaded ≈ $2.25M annualized.

---

## 9. External dependencies — vendor & cross-team blockers

These are real-world lead times that don't appear in engineering effort
but can move GA. Procurement starts at M0 to keep the critical path
clear.

| Dependency | Owner | Lead time | Latest start | Required by |
|---|---|---|---|---|
| AWS account, regions, KMS keys, billing | INFRA + EM | 2–4 weeks (cost negotiation) | Week 0 (pre-S1) | M2 |
| Vault Enterprise license + setup | INFRA | 4–6 weeks | Week 4 (mid-S2) | M2 |
| Temporal Cloud namespace | INFRA | 1–2 weeks | Week 8 (S5) | M3 |
| ClickHouse Cloud account | INFRA | 1 week | Week 12 (S7) | M4 |
| OIDC IdP integration with each design partner | PM + INFRA | 2–3 weeks per partner | Week 8 (S5) | M3 |
| Customer DPA template | EM + Legal | 2–3 weeks | Week 4 (S3) | M3 |
| Pricing model finalisation | EM + Finance | Ongoing → finalised by M5 | Week 12 (S7) | M5 |
| External pen-test vendor SoW | EM + SEC | 4–6 weeks (RFP + contract) | Week 14 (S7) | M5 |
| SOC 2 Type 1 auditor selection + readiness review | EM + SEC | 6–8 weeks | Week 8 (S4) | M6 |

**Failure mode:** any dependency missing its "Latest start" rolls the
"Required by" milestone forward. Tracked weekly in the operating-cadence
review with the same red/amber/green discipline as the engineering
backlog.

---

## 10. Design-partner ladder

Three production tenants by GA isn't an event — it's a journey with
gates. Each partner moves through the ladder at their own pace; the
plan supports concurrent partners at different stages.

| Stage | Sprint window | Description | Gate to advance |
|---|---|---|---|
| 0. Outreach | S1–S3 | Verbal interest; business case captured; mutual fit | Signed evaluation agreement |
| 1. Sandbox | S3–S4 (M2) | Mock connectors, sample queries, no production credentials | Sandbox queries pass; legal review of DPA started |
| 2. Staging | S5–S6 (M3) | Production-shape data via partner sandbox API; OIDC integrated; RLS / CLS policies authored together | DPA signed; security review of policy DSL passes; partner CTO sign-off |
| 3. Production | S9–S10 (M5) | First production tenant queries flowing; tier-1 support lane open; on-call paged on their incidents | 2 weeks of production traffic with no SEV-1; NPS ≥ 7 |
| 4. Reference | S12 (M6) | Public reference; case-study published; willing to talk to prospects | Marketing + legal joint sign-off |

**Plan target at GA:** 3 partners at Stage 3, ≥ 1 partner at Stage 4.

**Risk if partners stall at Stage 2:** GA's "3 partners in production
≥ 2 weeks" criterion slips. Mitigation: pipeline 5 partners through
Stage 1 to land 3 at Stage 3 (60 % conversion assumption is
conservative based on prior experience).

---

## 11. Production Readiness Review (PRR) — GA gate

Run on Sprint 12 day 5. Ten checklist items — every box must be
green for GA sign-off. A red item at PRR = GA slip; an amber item =
go with mitigation tracked.

### Reliability
- [ ] All 12 chaos scenarios from [`design/06-chaos-plan.md`](../design/06-chaos-plan.md) pass in M6 game day
- [ ] On-call rotation populated; PagerDuty escalation policy active; runbooks tested in dry-run
- [ ] SLO dashboards show 99.9 % availability over the previous 30-day window
- [ ] Error-budget policy ratified (release-freeze trigger defined and agreed by exec)
- [ ] Rollback path tested for each major component (canary + blue-green)

### Security
- [ ] External pen-test all-clear (no critical / high findings open)
- [ ] SOC 2 Type 1 audit complete OR formal "ready for audit" letter from auditor
- [ ] Off-boarding drill executed in last 30 days; < 5 min crypto-shred SLA met

### Capacity
- [ ] 1k QPS sustained for 60 min with P95 < 1.5 s across all 5 connectors
- [ ] 2× peak headroom verified in staging

### Operational
- [ ] Status page live and tested
- [ ] Tier-1 support lane operational with per-partner SLA
- [ ] DR/BCP documented; RPO ≤ 15 min, RTO ≤ 1 h verified by drill

### Documentation
- [ ] Admin guide, connector author guide, policy DSL reference, security whitepaper, DPA template all published

PRR is the *only* go/no-go gate at GA. Phase gates between earlier
milestones are lighter (M-exit criteria + risk-register green).

---

## 12. Companion documents

| Doc | Why it matters here |
|---|---|
| [`sprint_planning.md`](sprint_planning.md) | Per-sprint task allocation, Mermaid Gantt, dependency graph; the operational expansion of this doc |
| [`../design/06-chaos-plan.md`](../design/06-chaos-plan.md) | 12 chaos scenarios with hypothesis, injection, pass criteria; M5 + M6 game days are the *acceptance proof* of every defensive claim in the design |
| [`../design/runbooks/`](../design/runbooks/) | Three operational runbooks (rate-limit flood, connector auth failure, cache stampede); referenced by the chaos plan and the PRR checklist |
| [`../design/05-capacity-1k-qps.md`](../design/05-capacity-1k-qps.md) | Sizing math and bottleneck succession; the source of M4's "1k QPS / P95 < 1.5 s" exit criterion |

---

## 13. Mapping to the take-home prototype

Prototype lands in **M1's exit criteria minus per-tenant KMS**
(collapsed for time). Everything beyond is roadmap, not submission
scope. The design doc tells the GA story; the prototype proves M1 is
achievable. The chaos plan and runbooks (referenced in §12) show the
M5–M6 operational maturity is real, not hand-waved.
