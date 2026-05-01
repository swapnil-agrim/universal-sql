# Runbook — Rate-limit flood

> Connector-scope or tenant-scope token buckets exhausting at high
> rate; users seeing `RATE_LIMIT_EXHAUSTED` responses.

---

## 1. Trigger / alert

Fires when **either** condition holds for ≥ 2 minutes:

- `rate(rate_limit_rejections_total[2m]) > 5/s` (any scope)
- `sum by (tenant) (rate(rate_limit_rejections_total[5m])) > 1/s` for any tenant

Alert source: Prometheus → Alertmanager → PagerDuty.

## 2. Severity

| Condition | Severity |
|---|---|
| One tenant only, < 100 rejections/min | **SEV-3** — page during business hours |
| Multiple tenants OR > 500 rejections/min | **SEV-2** — page on-call immediately |
| Global bucket exhaustion (every tenant blocked) | **SEV-1** — wake everyone |

## 3. Symptoms

- Customer reports queries returning HTTP 429
- Grafana **Rate-limit rejections (rate)** panel non-zero
- Connector source returning more 429s than usual (look at upstream metrics if available)
- Async job queue depth growing (clients opting into the async path)

## 4. Immediate actions (first 5 minutes)

1. **Triage scope:** Grafana → "Rate-limit rejections by scope" chart. Is it `user`, `tenant`, or `global`?
2. **Identify the offending tenant(s):** Prometheus query
   `topk(5, sum by (tenant) (rate(rate_limit_rejections_total[5m])))`
3. **Page customer success** if a paying tenant is affected and they have a SLA.
4. **Open an incident channel** (`#incident-<timestamp>`).
5. **Decide containment vs investigation** — see Section 6.

## 5. Diagnosis

### Was it our app, or the source?
- Check `connector_request_duration_seconds` for upstream 429 spikes.
- Compare our `rate_limit_rejections_total` (our buckets) vs upstream 429s.
- If upstream is fine but we're rejecting → our bucket sizing is too tight; relax temporarily.
- If upstream is flooding 429s → the source is squeezed; we need to back off.

### Tenant-specific abuse?
- `topk(10, sum by (tenant, user) (rate(queries_total[5m])))` — find the noisy tenant/user.
- Audit log: `tenant=X` query count for the past hour.
- If one user is responsible: contact them; consider throttling at gateway level.

### Schema drift trigger?
- Has a recent connector deploy increased per-query source calls? Check change-log.

## 6. Mitigation

Pick one path:

### 6a. Temporary budget bump (1-tenant impact, source has capacity)
- Edit Helm `values.yaml` for affected tenant: bump `rpm_tenant` by 50%.
- Redeploy with canary: `helm upgrade --reuse-values --set tenant.<name>.rpm=...`
- Verify rejection rate drops within 60s.
- Open a follow-up ticket: "permanent budget review for tenant X".

### 6b. Borrowing pool exhausted (multi-tenant impact)
- Check global pool free tokens: Prometheus `connector_global_tokens`.
- If pool dry: temporarily raise `borrow_ceiling` from 2× to 3× for affected connector.
- Monitor for source 429 — if upstream starts rejecting, **revert immediately**.

### 6c. Source-side squeeze (upstream 429s)
- We cannot fix this; reduce our pressure.
- **Decrease** sync-pool budget by 30%; re-route excess to async lane.
- Notify users via status page: "GitHub API throttling — queries may take longer."
- Wait out the window. GitHub authenticated limits reset hourly.

### 6d. One bad query/user
- Identify via diagnosis step.
- If it's an abusive script, kill the user's session (revoke JWT).
- For a buggy customer query: contact them with `trace_id` and `details`.

## 7. Recovery

- Confirm `rate_limit_rejections_total` rate < 0.1/s for 10 minutes.
- Check async queue is draining (depth decreasing).
- Status page → green.
- Close incident channel.

## 8. Post-mortem checklist

- [ ] Was the alert threshold appropriate?
- [ ] Did the borrowing pool behave as designed?
- [ ] Should this tenant's nominal budget be raised?
- [ ] Did upstream-source dashboards correlate with our rejection rate?
- [ ] Was the customer-facing message timely?
- [ ] Did the async-overflow path drain in time, or did we lose jobs?
- [ ] What single signal would have predicted this 30 minutes earlier?
