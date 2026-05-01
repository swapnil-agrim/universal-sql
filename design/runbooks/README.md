# Runbooks

Operational playbooks for the top-3 failure modes the PDF calls out.
Each follows the same template:

1. **Trigger / alert** — what fires the page
2. **Severity** — SEV-1 / SEV-2 / SEV-3 guidance
3. **Symptoms** — what the on-call sees
4. **Immediate actions** — first 5 minutes
5. **Diagnosis** — how to confirm and narrow
6. **Mitigation** — restore service
7. **Recovery** — back to green
8. **Post-mortem checklist** — what to capture for the blameless review

| Runbook | Failure mode |
|---|---|
| [`rate-limit-flood.md`](rate-limit-flood.md) | Rate-limit rejections spiking; users getting `RATE_LIMIT_EXHAUSTED` |
| [`connector-auth-failure.md`](connector-auth-failure.md) | Connector 401/403 from source; tenant credentials stale or revoked |
| [`cache-stampede.md`](cache-stampede.md) | Cache miss storm overwhelming a source after TTL expiry |

Owned and maintained by the on-call engineering rotation. Refreshed
quarterly or after any incident that exposes a missing step.
