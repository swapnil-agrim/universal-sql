# Runbook — Connector authentication failure

> Connector receiving 401 / 403 from source; tenant credentials stale,
> revoked, or invalid.

---

## 1. Trigger / alert

Fires when **any** holds for ≥ 1 minute:

- `rate(connector_request_duration_seconds_count{response_code=~"401|403"}[1m]) > 0.5/s`
- Source-specific 401/403 metric exceeds 10/min for any tenant
- Vault token TTL on a tenant credential below 5 minutes (warning, not page)

## 2. Severity

| Condition | Severity |
|---|---|
| One tenant, one connector | **SEV-3** |
| One tenant, multiple connectors (suggests JWT/session issue, not source-side) | **SEV-2** |
| Multiple tenants on the same connector (source-side outage suspected) | **SEV-2 → SEV-1 if widespread** |

## 3. Symptoms

- Customer reports queries returning `ENTITLEMENT_DENIED` or empty results
- Grafana shows 401/403 spike on a specific connector
- Audit log shows `source_response_code: 401` for the affected tenant
- `freshness_ms` climbing because cache is the only source of truth

## 4. Immediate actions

1. **Identify scope:** affected tenant(s) and connector(s).
2. **Check Vault** — is the credential present and within TTL?
   - `vault read secret/tenant/<id>/connector/<name>` (requires on-call elevated access)
3. **Check status page** of the source vendor (GitHub, Jira, Salesforce…).
4. **Open incident channel** if scope > 1 tenant.
5. **Contact customer** if this is their credential — most often it is.

## 5. Diagnosis

### Path A — credential expired or rotated by customer
- Most common cause.
- Symptoms: single tenant; works after re-auth.
- Fix: Section 6a.

### Path B — Vault outage or KMS unreachable
- Symptoms: many tenants, multiple connectors, audit log shows zero
  reads on `secret/tenant/*` paths.
- Fix: Section 6b.

### Path C — source-side outage
- Symptoms: many tenants on same connector; vendor status page red.
- Fix: Section 6c.

### Path D — our code regression in token handling
- Symptoms: started after a deploy; spans show our connector pre-emptively
  refreshing tokens that didn't need refreshing.
- Fix: Section 6d.

## 6. Mitigation

### 6a. Customer credential
- Email tenant admin via support channel (template in `customer-comms/cred-expired.md`).
- In admin console: mark connector as `state: requires_credential`; users see
  "Connector unavailable, please re-authenticate" with a link.
- Cached data continues to serve `max_staleness >= 60s` queries — buys time.

### 6b. Vault / KMS outage
- **Fail-secure** — DO NOT bypass. Check Vault health.
- Connector workers will continue to use cached DEKs for up to 15 minutes
  (designed degradation per `04-security.md`).
- After 15 min without Vault, all queries fail with `ENTITLEMENT_DENIED` —
  this is by design. Restore Vault before extending the cache TTL.
- Page Vault on-call.

### 6c. Source vendor outage
- Confirm via vendor status page; subscribe.
- Update our status page: "Source X experiencing issues; queries may fail."
- For tenants on `max_staleness >= 5min`, results still flow from cache.
- For real-time queries: client receives `SOURCE_TIMEOUT`; recommend retry
  with non-zero `max_staleness`.

### 6d. Code regression
- Roll back the most recent connector deploy:
  `helm rollback universal-sql <revision>`
- Verify rejection rate drops; open follow-up ticket on the regression.

## 7. Recovery

- 401/403 rate back to baseline (~ 0).
- Vault / KMS green.
- Tenant has re-authenticated (if Path A).
- Cached data freshness recovers.

## 8. Post-mortem checklist

- [ ] Was the customer notified within SLO?
- [ ] Did our cache absorb the outage as designed?
- [ ] How long did the credential have remaining when alert fired? Should the
      "TTL low" warning fire earlier?
- [ ] Was a Vault break-glass path tested in this incident? When was the last
      drill?
- [ ] Were any cross-tenant artefacts created or leaked? (Audit-log review.)
- [ ] Should the connector implement automatic re-auth UI prompts?
