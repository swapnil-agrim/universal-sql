// k6 load test — drives ~500–1k QPS for 60s against POST /v1/query.
// Usage:
//   docker run --network host -v $PWD:/scripts -i grafana/k6 run /scripts/load-test/k6.js
// or natively:
//   k6 run load-test/k6.js
//
// Sustained QPS depends on machine; on a laptop expect ~700–900 effective.
// The first ~5s seeds caches; after that almost every request is a cache HIT,
// which is the realistic load shape (rate-limit budget is preserved).

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const BACKEND = __ENV.BACKEND_URL || "http://localhost:8000";

const cacheHits = new Counter("cache_hits");
const cacheMisses = new Counter("cache_misses");
const rateLimited = new Counter("rate_limited");
const queryLatency = new Trend("query_latency_ms", true);

export const options = {
  scenarios: {
    sustained: {
      executor: "constant-arrival-rate",
      rate: 700,           // requests per second
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: 80,
      maxVUs: 200,
    },
  },
  thresholds: {
    "http_req_duration": ["p(95)<1500"],   // matches design SLO
    "http_req_failed":   ["rate<0.05"],    // tolerate 5% during cold start
  },
};

const QUERIES = [
  {
    user: "alice",
    sql: `SELECT pr.number, pr.title, pr.repo, jira.key, jira.status, jira.assignee
          FROM   github.pull_requests AS pr
          JOIN   jira.issues          AS jira ON jira.key = pr.linked_issue_key
          WHERE  pr.repo = 'acme/api'
          LIMIT  20`,
  },
  {
    user: "bob",
    sql: `SELECT pr.number, pr.title, pr.author
          FROM   github.pull_requests AS pr
          WHERE  pr.repo = 'acme/api'
          LIMIT  10`,
  },
  {
    user: "manager",
    sql: `SELECT j.key, j.status, j.assignee
          FROM   jira.issues AS j
          WHERE  j.status = 'In Progress'
          LIMIT  10`,
  },
];

export default function () {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.post(
    `${BACKEND}/v1/query`,
    JSON.stringify({ sql: q.sql, max_staleness_seconds: 300 }),
    {
      headers: { "Content-Type": "application/json", "X-User-Id": q.user },
      tags: { user: q.user },
    },
  );

  check(res, {
    "status 200 or 429": (r) => r.status === 200 || r.status === 429,
  });

  queryLatency.add(res.timings.duration);

  if (res.status === 429) {
    rateLimited.add(1);
    return;
  }

  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      const sources = body.cache_status || {};
      for (const status of Object.values(sources)) {
        if (status === "hit") cacheHits.add(1);
        else if (status === "miss") cacheMisses.add(1);
      }
    } catch (_) {}
  }
}
