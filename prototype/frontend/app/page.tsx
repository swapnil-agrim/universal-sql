"use client";

// Thin UI — every decision (parsing, entitlements, rate-limits, freshness, joins)
// happens server-side. This component only renders state and posts to /v1/query.

import { useState } from "react";

const DEFAULT_SQL = `SELECT pr.number, pr.title, pr.repo,
       jira.key, jira.status, jira.assignee
FROM   github.pull_requests AS pr
JOIN   jira.issues          AS jira ON jira.key = pr.linked_issue_key
WHERE  pr.repo = 'acme/api'
LIMIT  20`;

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type QueryResponse = {
  rows: Record<string, unknown>[];
  columns: string[];
  freshness_ms: number;
  rate_limit_status: string;
  trace_id: string;
  cache_status: Record<string, string>;
  rows_per_source: Record<string, number>;
};

type QueryError = {
  code: string;
  message: string;
  retry_after?: number;
  details?: Record<string, unknown>;
};

export default function Home() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [user, setUser] = useState("alice");
  const [maxStaleness, setMaxStaleness] = useState(300);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<QueryError | null>(null);
  const [loading, setLoading] = useState(false);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  async function runQuery() {
    setLoading(true);
    setError(null);
    setResponse(null);
    const t0 = performance.now();
    try {
      const res = await fetch(`${BACKEND}/v1/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": user },
        body: JSON.stringify({ sql, max_staleness_seconds: maxStaleness }),
      });
      const body = await res.json();
      if (!res.ok) {
        // FastAPI puts our payload in `detail`
        const err: QueryError = body.detail || body;
        setError(err);
      } else {
        setResponse(body as QueryResponse);
      }
    } catch (e) {
      setError({ code: "NETWORK_ERROR", message: String(e) });
    } finally {
      setElapsedMs(Math.round(performance.now() - t0));
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Universal SQL — Prototype</h1>
        <p className="text-sm text-slate-400">
          Cross-app query: GitHub PRs ↔ Jira issues. All logic server-side.
        </p>
      </header>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-slate-400">User (X-User-Id)</span>
          <select
            value={user}
            onChange={(e) => setUser(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1"
          >
            <option value="alice">alice (engineer, repos: api+web)</option>
            <option value="bob">bob (engineer, repos: api only — RLS test)</option>
            <option value="manager">manager (engineer+manager — sees assignee)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-slate-400">max_staleness_seconds</span>
          <input
            type="number"
            min={0}
            max={3600}
            value={maxStaleness}
            onChange={(e) => setMaxStaleness(parseInt(e.target.value || "0", 10))}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1"
          />
        </label>
        <div className="flex items-end">
          <button
            onClick={runQuery}
            disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 px-4 py-2 rounded text-sm font-medium w-full"
          >
            {loading ? "Running…" : "Run query"}
          </button>
        </div>
      </section>

      <section className="mb-4">
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={10}
          className="w-full font-mono text-sm bg-slate-900 border border-slate-700 rounded p-3 leading-relaxed"
          spellCheck={false}
        />
      </section>

      {error && (
        <section className="mb-4 border border-red-700 bg-red-950/40 rounded p-4 text-sm">
          <div className="font-semibold text-red-300">Error: {error.code}</div>
          <div className="text-red-200 mt-1">{error.message}</div>
          {error.retry_after !== undefined && (
            <div className="text-red-300 mt-2">Retry after: {error.retry_after}s</div>
          )}
          {error.details && (
            <pre className="text-xs text-red-200 mt-2 overflow-auto">
              {JSON.stringify(error.details, null, 2)}
            </pre>
          )}
        </section>
      )}

      {response && (
        <>
          <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4 text-sm">
            <Stat label="rows" value={response.rows.length} />
            <Stat label="freshness_ms" value={response.freshness_ms} />
            <Stat label="rate_limit_status" value={response.rate_limit_status} />
            <Stat label="round-trip ms" value={elapsedMs ?? "–"} />
          </section>

          <section className="mb-4 grid grid-cols-1 lg:grid-cols-2 gap-3 text-xs">
            <Block title="Cache status (per source)">
              <pre>{JSON.stringify(response.cache_status, null, 2)}</pre>
            </Block>
            <Block title="Rows per source (post-pushdown)">
              <pre>{JSON.stringify(response.rows_per_source, null, 2)}</pre>
            </Block>
          </section>

          <section className="mb-4 text-xs text-slate-500">
            trace_id: <span className="font-mono">{response.trace_id}</span>
          </section>

          <section className="overflow-auto rounded border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  {response.columns.map((c) => (
                    <th key={c} className="text-left px-3 py-2 font-medium">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {response.rows.map((row, i) => (
                  <tr key={i} className="border-t border-slate-800">
                    {response.columns.map((c) => (
                      <td key={c} className="px-3 py-2 font-mono text-xs">
                        {String(row[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded px-3 py-2">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="font-mono text-base">{value}</div>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded p-3">
      <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">{title}</div>
      <div className="text-slate-300 font-mono">{children}</div>
    </div>
  );
}
