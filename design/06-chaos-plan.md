# Chaos Plan — testing system resilience

> Companion to [01-architecture.md](01-architecture.md). The PDF lists
> "chaos plan" as a bonus rubric item; more importantly, design claims
> like *"the freshness layer absorbs source outages"* and *"budget
> borrowing keeps tail tenants fair"* are **hypotheses** until proven.
> This document operationalises that proof: a catalogue of failure
> scenarios with hypothesis, injection technique, and pass/fail criteria.

---

## 1. Principles

Drawn from the Netflix / Google Chaos Engineering taxonomy, applied to our system:

- **Hypothesis-driven** — every experiment starts with *"we believe X. Prove or disprove."*
- **Production-realistic, blast-radius bounded** — production-shaped traffic, narrowed scope (one tenant, one connector, one AZ).
- **Observable in real time** — must be detectable in dashboards within 60 s.
- **Reversible** — every injection has a documented rollback in ≤ 5 min.
- **Not in early development** — chaos engineering presupposes baseline reliability. We start dry-runs at M5; first full game day in M6.
- **Run regularly post-GA** — quarterly rotation; full annual exercise.

---

## 2. Tooling

| Tool | Role |
|---|---|
| **k6** | Synthetic user load (already in `prototype/load-test/`) |
| **Chaos Mesh** | k8s-native chaos: PodKill, NetworkPartition, IO delay, DNS chaos |
| **Toxiproxy** | TCP-level fault injection (latency, packet drop) for connector / Redis traffic |
| **Mock connector knobs** | `CONNECTOR_MODE=mock` already exists; add error/latency injection env vars (`MOCK_GITHUB_LATENCY_MS`, `MOCK_GITHUB_ERROR_RATE`) |
| **Grafana** | Observation surface during exercises |
| **Slack `#chaos-game-day-<date>`** | Comms channel during exercises |

---

## 3. Scenarios — 12 experiments

Each scenario states a hypothesis, the injection, expected behaviour, the failure mode (what would invalidate the hypothesis), and the pass criterion.

### 3.1 Source outage — GitHub API returns 503
- **Hypothesis:** Queries served from cache continue with non-zero `freshness_ms`. Queries needing fresh data return `STALE_DATA` + `Retry-After`. No cascading failures to other connectors.
- **Injection:** Toxiproxy on `github` connector returns 503 for 5 minutes.
- **Expected:** Cache-hit ratio rises (fewer competing live fetches); `STALE_DATA` count rises; Jira queries unaffected; gateway availability ≥ 99.9 %.
- **Failure mode:** Gateway P95 > 2 s sustained, or Jira-only queries impacted (= HOL block).
- **Pass:** Gateway P95 ≤ 1.5 s within 60 s of injection; recovery to baseline ≤ 60 s after injection stops.

### 3.2 Source slow — Jira API +10× latency
- **Hypothesis:** Per-source semaphore (Capacity §8.2) prevents Jira-slow from starving GitHub. Per-query timeout (§8.3, now real in code) caps latency at the configured deadline.
- **Injection:** Toxiproxy adds 10 s latency to Jira connector for 5 min.
- **Expected:** Jira-touching queries time out → `partial: true, partial_sources: ["jira.issues"]`. GitHub-only queries unaffected.
- **Failure mode:** GitHub P95 latency rises along with Jira's (= shared pool, not partitioned).
- **Pass:** GitHub P95 stays within 10 % of baseline throughout the experiment.

### 3.3 Source rate-limit storm
- **Hypothesis:** Our token bucket pre-empts most calls so we don't beat on a struggling source. If upstream still 429s, source-protective mode kicks in (raise `min_recommended_max_staleness`).
- **Injection:** Mock GitHub returns 50 % HTTP 429s for 5 min.
- **Expected:** `rate_limit_rejections_total` (our buckets) spikes briefly, then auto-mitigation reduces our pressure. Source 429 rate falls.
- **Failure mode:** Source 429s sustain > 1 minute after our adjustment.
- **Pass:** Source 429 rate ≤ 0.5/s within 90 s of mitigation.

### 3.4 Cache stampede after restart
- **Hypothesis:** Single-flight + stale-while-revalidate prevent thundering-herd; recovery within 60 s.
- **Injection:** Flush Redis L2 cache during sustained 700 RPS load.
- **Expected:** Brief cache-miss spike. Single-flight serializes per-key fetches. Source 429 stays under threshold.
- **Failure mode:** Source 429 spike, gateway P95 > 1.5 s for > 60 s.
- **Pass:** Gateway P95 returns ≤ 1.5 s within 60 s of flush.
- **Drives:** [`runbooks/cache-stampede.md`](runbooks/cache-stampede.md).

### 3.5 KMS unavailability
- **Hypothesis:** Cached DEKs (15 min TTL) absorb short outages. Beyond 15 min, queries fail-secure with `ENTITLEMENT_DENIED`.
- **Injection:** `iptables` block from connector workers to Vault for 10 min.
- **Expected:** Queries continue normally for the cached-DEK window; never silently bypass encryption.
- **Failure mode:** **Any** query succeeds without a valid DEK after the cached window expires (security violation; SEV-1).
- **Pass:** Behaviour matches design — cached window honoured, then fail-secure.

### 3.6 Connector worker pod kill
- **Hypothesis:** In-flight queries fail with `SOURCE_TIMEOUT` (graceful). HPA spins replacement. Cache state intact (Redis persists).
- **Injection:** Chaos Mesh `PodKill` on 1/5 connector pods every 30 s for 10 min.
- **Expected:** Brief 5xx spike for in-flight requests on killed pod. Replica count holds. Cache hit ratio stable across the exercise.
- **Failure mode:** Sustained 5xx; replica count drops below floor; HPA fails to react.
- **Pass:** P95 stays ≤ 1.5 s; total 5xx < 0.5 % during exercise.

### 3.7 Network partition — Redis cluster split
- **Hypothesis:** Rate-limit and freshness fall back to in-process L1 with a degraded-mode flag. `/v1/system/health` flips to `degraded`.
- **Injection:** Chaos Mesh `NetworkPartition` between connector workers and Redis primary for 5 min.
- **Expected:** `/v1/system/health` reports `degraded`. Rate-limit precision drops (now per-pod). Cache hit ratio drops to L1-only (~30 %).
- **Failure mode:** False-positive `ENTITLEMENT_DENIED` or `RATE_LIMIT_EXHAUSTED` (stale state corruption).
- **Pass:** No false-positive entitlement / rate-limit errors; recovery within 60 s of partition heal.

### 3.8 Noisy-neighbour tenant flood
- **Hypothesis:** Borrowing capped at 2× nominal contains the spam. Quiet tenants' P95 degrades < 10 %.
- **Injection:** k6 with one tenant at 5× their nominal QPS for 10 min; other tenants at baseline.
- **Expected:** Noisy tenant gets `RATE_LIMIT_EXHAUSTED` once they cross 2× nominal. Quiet tenants barely notice.
- **Failure mode:** Quiet tenant P95 grows > 10 % (= fairness violation).
- **Pass:** Quiet tenants' P95 < 10 % above baseline; noisy tenant capped at 2× nominal.
- **Drives:** [`runbooks/rate-limit-flood.md`](runbooks/rate-limit-flood.md).

### 3.9 DuckDB tmpfs full
- **Hypothesis:** Materialisation layer detects out-of-disk and rejects with `OVERLOAD_BACKPRESSURE` rather than crashing. Load balancer routes around the affected pod.
- **Injection:** Fill tmpfs to 95 % on one connector worker pod.
- **Expected:** Affected pod fails new materialisation queries with backpressure; healthy pods unaffected.
- **Failure mode:** Pod OOM or panic; queries on other pods affected; cache state corrupted.
- **Pass:** Affected pod evicts unhealthy traffic via readiness-probe; gateway P95 stays ≤ 1.5 s.

### 3.10 Region (AZ) failure
- **Hypothesis:** Multi-AZ baseline + pod anti-affinity → one AZ loss = ~33 % capacity loss; HPA + cluster autoscaler restore within 5 min in remaining AZs.
- **Injection:** Cordon + drain all nodes in one AZ.
- **Expected:** Brief queue-depth spike, HPA scales out other AZs, recovery within 5 min.
- **Failure mode:** Sustained backpressure; capacity stuck below pre-injection.
- **Pass:** Replica count restored in ≤ 5 min; gateway availability ≥ 99 % across the window.

### 3.11 Schema drift from source
- **Hypothesis:** Capability descriptor catches the drift, emits `SCHEMA_DRIFT`, refuses to cache the polluted response, admin alert fires.
- **Injection:** Mock source returns a row with an extra / missing field that violates the descriptor.
- **Expected:** `SCHEMA_DRIFT` in logs, admin alert via PagerDuty, no cache pollution.
- **Failure mode:** Silent acceptance; downstream type errors; cache poisoned.
- **Pass:** Drift detected within 1 query; cache for that signature is *not* updated.

### 3.12 Audit log writer outage
- **Hypothesis:** Connector buffers writes locally; when Kafka returns, buffer drains; if buffer fills, queries fail-closed (audit cannot be lost silently).
- **Injection:** Kill Kafka producer for 5 min during sustained load.
- **Expected:** Local buffer absorbs traffic; if it fills, `audit_loss_protected_total` counter rises and queries that would lose audit fail-closed.
- **Failure mode:** Queries continue *without* audit being written (security violation; SEV-1).
- **Pass:** Zero audit-loss events; either buffered or fail-closed.

---

## 4. Game-day cadence

| Cadence | Scope | Tied to |
|---|---|---|
| **M5 (Sprint 9–10)** | Dry-run in staging — operationally-critical scenarios only (3.1, 3.2, 3.4, 3.6, 3.8) | Pen-test prep |
| **M6 (Sprint 11)** | Full 12-scenario game day in staging — **GA acceptance gate** | GA sign-off |
| **Quarterly post-GA** | 4 scenarios per quarter on rotation; full game day once a year | SLO health |
| **After-incident** | Re-run the scenario closest to the incident | Continuous improvement |

---

## 5. Game-day process (3-hour exercise)

```
T+0:00   Brief                  Facilitator walks scenarios; assigns roles
T+0:15   Baseline               15 min of normal-state metrics captured
T+0:30   Scenario 1 inject      10 min observation
T+0:40   Scenario 1 recover     5 min — runbook verification, retrospect
T+0:45   Scenario 2 inject      ...
...
T+2:30   Cool-down              15 min — verify SLO recovery
T+2:45   Debrief                15 min — collect findings, file tickets
```

### Roles

| Role | Owner | Responsibility |
|---|---|---|
| Facilitator | EM | Drive the exercise, control injections, manage time |
| On-call (simulated) | TL or current rotation | First responder, follow runbooks as if production |
| Observer | PM | Capture customer-facing impact, draft incident comms |
| Scribe | DX | Record timeline, decisions, post-game tickets |

---

## 6. Acceptance-criteria framework

Every scenario answers four questions:

1. **Did the system stay within SLO during the experiment?**
   P95 ≤ 1.5 s; availability ≥ 99.9 % over the experiment window.
2. **Did the right alert fire within 60 s of injection?**
   No silent failures.
3. **Was the runbook accurate?**
   On-call followed the corresponding runbook in `design/runbooks/`; did the prescribed mitigation actually resolve the issue?
4. **Was customer impact within the per-scenario contract?**
   See "Pass" line in each scenario.

A scenario **passes** when all four are met. Failures become tickets, prioritised in the next sprint.

---

## 7. Error-budget impact

Chaos game days are **scheduled error-budget burn**. Plan for:

- ≤ 15 min of degraded-state metrics per scenario
- 12 scenarios × 15 min = 3 h, ≤ 0.4 % monthly availability — within the 99.9 % SLO budget headroom
- Run during off-peak hours (Saturday morning UTC = lowest traffic for our design-partner mix)

If the error budget is already burning down from real incidents, **postpone the game day**. Chaos is governance-second to ongoing reliability — never the cause of an SLA breach.

---

## 8. Tracking — the "chaos register"

Stored in a Notion / Confluence page (or a simple committed spreadsheet). Per scenario:

| Field | Example |
|---|---|
| Scenario | 3.8 Noisy-neighbour tenant flood |
| Last run | 2026-09-15 |
| Result | Pass — quiet-tenant P95 +6 % |
| Findings ticket | #1247 (improved chart annotations) |
| Owner | EM |
| Stale-after | 2027-03-15 (6 months) |

Scenarios untouched > 6 months auto-flag in the on-call dashboard.

GA acceptance: **all 12 scenarios pass at least once** in the M6 game day.

---

## 9. What this proves

The chaos plan is the operational *test* of every defensive claim in the design docs:

| Claim | Scenario that tests it |
|---|---|
| "Freshness layer absorbs source outages" | 3.1 |
| "Per-source semaphore prevents HOL blocking" | 3.2 |
| "Token bucket + auto-mitigation contains source pressure" | 3.3 |
| "Single-flight prevents stampede" | 3.4 |
| "Cached DEKs absorb Vault outages; fail-secure beyond" | 3.5 |
| "HPA + autoscaler handle pod loss" | 3.6 |
| "System survives Redis partition in degraded mode" | 3.7 |
| "Budget borrowing capped at 2× contains noisy neighbours" | 3.8 |
| "Materialisation back-pressures cleanly under disk pressure" | 3.9 |
| "Multi-AZ tolerates one-AZ failure within 5 min" | 3.10 |
| "Connector descriptors catch schema drift" | 3.11 |
| "Audit log never silently drops" | 3.12 |

Without this catalogue, those claims are aspirational. With it, they're testable, scheduled, and continuously re-verified.

---

## 10. Where this lives in the plan

- **Sprint 9–10 (M5):** dry-run game day with the operationally-critical 5 scenarios; surfaces issues before the external pen-test.
- **Sprint 11 (M6):** full 12-scenario game day; **GA acceptance gate**.
- **Post-GA quarterly:** rotate 4 scenarios per quarter; ensure no scenario goes > 6 months unrun.
- **Owners:** EM facilitates; TL technical lead; INFRA + QA execution; SEC reviews 3.5, 3.7, 3.12 (the security-sensitive scenarios).

See [`02-execution-plan.md`](../planning/02-execution-plan.md) and
[`sprint_planning.md`](../planning/sprint_planning.md) for the
sprint-level allocation.
