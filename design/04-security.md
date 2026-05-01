# Security, Entitlements & Compliance

> Companion to [01-architecture.md](01-architecture.md). Targets the
> "Security & Entitlements" rubric line (15%) with explicit threat
> model, isolation layers, audit semantics, and compliance posture.

## 1. STRIDE threat model in one screen

| Threat | Vector | Mitigation |
|---|---|---|
| **Spoofing** — fake JWT | Stolen / forged token | OIDC verification at gateway; JWT lifetime 15 min; per-user revocation list; audience binding |
| Spoofing — counterfeit source | DNS hijack of `api.github.com` | Pin TLS cert / SAN per connector; pinned-CA mode for high-tier tenants |
| **Tampering** — query injection into source | User-controlled string in JQL/SOQL | No string concatenation anywhere; parameterized source calls; predicates pass through typed AST nodes only |
| Tampering — policy bypass | Hot-edited Vault YAML | Git-backed Vault path; signed commits; CI policy validator blocks merges with deny-everything / allow-everything regressions |
| **Repudiation** — missing audit | Connector worker logs nothing | Audit emission is part of the connector contract; fail-closed if emission fails |
| **Information disclosure** — cross-tenant leak | Bug in planner cache key | Tenant ID as primary key prefix (type-system enforced); red-team test suite (M3) |
| Information disclosure — log scraping | Logs containing row data | Logs only contain row counts, never values; CLS-marked columns redacted at the log boundary |
| Information disclosure — side channels | Timing differences reveal entitlement decisions | Constant-time entitlement evaluation for cached policies; jittered error responses |
| **Denial of service** — rate-limit abuse | One tenant burns global budget | Hierarchical buckets with hard 2× ceiling (see [03-freshness-rate-limits](03-freshness-rate-limits.md)) |
| DoS — materialization flood | Adversarial queries spawning ClickHouse tables | Per-tenant materialization budget (storage ceiling + concurrency limit) |
| **Elevation of privilege** — worker escape | Container compromise reads other tenant's data | Worker pods unprivileged; AppArmor + seccomp; per-tenant credentials never co-resident in process memory |

Each row maps to a control with an owning team and a test that gates
the relevant milestone in [02-execution-plan.md](../planning/02-execution-plan.md).

---

## 2. Tenant isolation — defense in depth

Independent isolation mechanisms layered so that any one being buggy
does not compromise tenant separation.

```
          ┌──────────────────────────────────────────────┐
          │  L1: Compute namespace                       │  k8s NetworkPolicy
          │   ┌─────────────────────────────────────┐    │
          │   │  L2: Per-tenant credentials         │    │  Vault dynamic secrets
          │   │   ┌───────────────────────────────┐ │    │
          │   │   │  L3: Cache key scoping        │ │    │  hash(tenant) prefix
          │   │   │   ┌─────────────────────────┐ │ │    │
          │   │   │   │  L4: Encryption         │ │ │    │  per-tenant DEK ⊃ KEK
          │   │   │   └─────────────────────────┘ │ │    │
          │   │   └───────────────────────────────┘ │    │
          │   └─────────────────────────────────────┘    │
          └──────────────────────────────────────────────┘
```

### 2.1 Compute (L1)
- Namespace per tenant in multi-tenant deploy
- `NetworkPolicy` denies cross-namespace traffic by default
- Optional dedicated cluster for high-tier tenants (same Helm chart,
  `values.tenancy=single`)

### 2.2 Credentials (L2)
- Source credentials live under `secret/tenant/{tenant_id}/connector/{name}` in Vault
- Workers fetch via Vault dynamic secrets, 15-minute lease, AppRole +
  serviceaccount auth
- Long-lived credentials never appear in pod env vars or filesystem

### 2.3 Cache & data (L3)
- All cache keys begin with `{tenant_id}::{table}::{predicate-hash}` —
  enforced by type system (`TenantScopedKey` newtype refuses
  unscoped construction)
- Postgres metadata catalog: row-level security on `tenant_id` column

### 2.4 Encryption (L4)
- Per-tenant data encryption key (DEK) wrapped by tenant-scoped KMS
  key (KEK) — envelope encryption
- DEK rotated every 90 days; rewrap on rotation
- Tenant KMS key is the **crypto-shred handle**: revoke = data
  unrecoverable, regardless of where it physically lives

---

## 3. Identity & authentication

| Surface | AuthN | AuthZ |
|---|---|---|
| User → Gateway | OIDC (JWT validated against IdP JWKS) | Entitlement service merges user roles + tenant policy |
| Service → Service | mTLS via SPIFFE/SPIRE-issued SVIDs | NetworkPolicy + service-mesh authorisation |
| Connector → Source | Per-tenant credential from Vault | Source-side OAuth / API key |
| Admin → Control plane | OIDC + role gate (`platform-admin`) | OPA policy decision endpoint |

JWT lifetime is intentionally short (15 minutes) with refresh on a
separate channel. A leaked token expires fast; a leaked refresh token
is a different (smaller) blast radius and gets per-user revocation.

---

## 4. Entitlements — composition and DSL

### 4.1 The composition rule

A user's effective view of a row is the **intersection** of three
sets, never the union:

1. **Source permission set** — what the SaaS app says the user can see (e.g. GitHub returns repos the user is a member of)
2. **Tenant policy set** — what platform admin allows (e.g. mask PII for non-managers)
3. **Query projection** — what columns the user actually selected

Union semantics are explicitly rejected: a row visible in the source
but masked by tenant policy is not visible. The principle is "least
surprise to the platform admin" — adding a policy never widens access.

### 4.2 Two-tier policy DSL

- **Tenant-scoped Rego** (OPA) — flexible authoring surface; audited;
  changes require PR + sign-off
- **Compiled predicates** — for the hot path, the planner compiles RLS
  rules into native predicate AST nodes that push down with the query

Compilation pipeline:

```
Rego policy ──► Intermediate Rep ──► Predicate AST ──► Connector pushdown
     │                                      │                    │
     └─ git commit                          └─ unit-tested        └─ source-native filter
        + signed                               in CI                 (e.g. JQL `key IN (...)`)
        + CI validator
```

The CI validator rejects policies that compile to "always deny" or
"always allow" without an explicit `# OVERRIDE: <ticket>` annotation.
Catches the typo class that would otherwise be either a security or
availability incident.

### 4.3 Policy testing

- Red-team scenario suite committed to the repo
  (`tests/security/redteam_*.py`)
- Each release runs all scenarios in CI; any new failure blocks merge
- Quarterly external pen-test against staging with live policies (M6
  exit criterion)

---

## 5. Audit trail

Every cross-system access produces one audit record:

```json
{
  "ts": "2026-04-30T14:23:48.922Z",
  "tenant": "acme",
  "user": "alice",
  "trace_id": "3a8159...",
  "table": "github.pull_requests",
  "predicates_applied": [{"col": "repo", "op": "IN", "value_hash": "9f3a..."}],
  "rls_rules": ["github_repo_scope"],
  "cls_masks": [],
  "rows_returned": 50,
  "freshness_ms": 17,
  "cache_status": "miss",
  "source_response_code": 200
}
```

Storage:
- Append-only Kafka topic per tenant
- Archived to S3 with object-lock (write-once-read-many)
- Retention per tenant's residency contract (default 13 months)

**Predicate values are hashed**, not stored verbatim. The audit log
proves what scope was applied without leaking the values themselves
(which could include PII like user emails). Reviewers can verify a
specific value was queried, but the log alone cannot be mined for
the population of values.

---

## 6. Data residency

Each tenant carries a residency tag (`us`, `eu`, `apac`, `ca`, etc.).
The tag drives:

- Which **k8s cluster** runs their queries
- Which **Vault namespace** holds their credentials
- Which **S3 bucket** holds their materialised data
- Which **Kafka cluster** holds their audit log

Cross-region replication is **opt-in per tenant**, never default. The
scheduler refuses to place a tenant's job in the wrong region — a
mis-tagged tenant fails closed (no service) rather than fails open
(wrong region).

The residency boundary is enforced at three layers:
1. Admission controller in k8s rejects pods scheduled across boundaries
2. Storage layer rejects DEK reads from out-of-region requests
3. Audit log records the residency tag on every access; quarterly
   compliance audit verifies zero violations

---

## 7. Off-boarding & crypto-shred

A 5-minute SLA from "off-board tenant X" to "tenant data structurally
unrecoverable":

| Step | Duration | What |
|---|---|---|
| 1 | 5 s | Stop accepting tenant X queries (gateway feature flag) |
| 2 | 30–60 s | Cancel in-flight queries; drain async jobs |
| 3 | instant | **Revoke tenant X KMS key** — the actual security event |
| 4 | 30–60 s | Delete tenant X namespace (cascades to caches + materialisations) |
| 5 | async | Archive audit log per contract; emit off-boarding event for billing/compliance |

Without the KMS key, all on-disk data (cache, materialisation, S3) is
ciphertext that can't be decrypted. **That's the crypto-shred.**
Storage deletion is hygiene; the key revocation is the security event.

This is a single-button operation in the admin console (M6
deliverable) and a tested drill in the M5 milestone.

---

## 8. Compliance posture

| Cert | Scope | Target |
|---|---|---|
| SOC 2 Type 1 | M6 GA | Explicit acceptance criterion |
| SOC 2 Type 2 | Post-GA Q1 | Continuous controls evidence |
| GDPR | At GA | DPA template; right-to-erasure via off-boarding |
| HIPAA | Deferred | Post-GA roadmap; requires BAA + specific data handling |
| ISO 27001 | Post-Type 2 | Customer-driven |

Compliance is a **quarterly cadence after GA**, not a one-time event.
The audit trail (Section 5) and residency enforcement (Section 6) are
designed to produce evidence continuously, so re-certifications are
work weeks rather than work months.

---

## 9. Secrets handling — beyond Vault

| Secret class | Storage | Rotation | Break-glass |
|---|---|---|---|
| Tenant KMS key (KEK) | AWS KMS / GCP CMEK | Never rotated; backed up to HSM | HSM admin quorum |
| Tenant DEK | Vault transit, wrapped by KEK | 90 days, rewrap online | Re-issue from KEK |
| Source API tokens (per tenant) | Vault dynamic secrets | Source-defined (typically 90 d) | Manual rotate via admin console |
| Service mTLS certs | SPIRE | 24 hours | SPIRE root rotation drill quarterly |
| OIDC signing keys | IdP-managed | IdP-managed | IdP-managed |

The break-glass column is the answer to "what if the rotation
mechanism fails?" — every secret has a documented manual recovery
path that doesn't require the automated pipeline to be working.

---

## 10. What the prototype demonstrates

The prototype implements the **Y axis** of every isolation layer
(structure) but with simplified mechanisms (single-process, no Vault,
no real KMS). Specifically:

- Tenant-scoped cache keys (L3) — `app/planner.py::_cache_key`
- RLS predicate composition (Section 4) — `app/entitlements.py`
- CLS column masks (Section 4) — same module, exercised by tests
- Standard error vocabulary including `ENTITLEMENT_DENIED` —
  `app/errors.py`
- Audit-shaped trace attributes (Section 5 in miniature) —
  `app/observability.py` spans carry user, tenant, predicate counts

The production gap (Vault, KMS, mTLS, OPA, SPIRE) is documented as
roadmap in [02-execution-plan.md](../planning/02-execution-plan.md) milestones M2
(per-tenant KMS), M3 (policy DSL + audit), M5 (residency + off-boarding
drill), M6 (external pen-test).

The red-team test in `prototype/backend/tests/test_query_e2e.py`
already demonstrates the principle: Bob's RLS predicate restricts him
to one repo even when he writes a query without filters, and the CLS
mask redacts `assignee` for non-managers — both verified end-to-end
against the running system.
