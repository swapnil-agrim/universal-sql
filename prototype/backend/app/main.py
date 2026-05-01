"""Universal SQL gateway — FastAPI entrypoint.

Endpoints:
  POST /v1/query   — execute a query, returns rows + freshness/rate/trace metadata
  GET  /healthz    — liveness
  GET  /metrics    — Prometheus exposition
  GET  /v1/tables  — list registered tables (for the UI)
"""
from __future__ import annotations
import logging
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field

from .auth import User, make_auth_dep
from .catalog import Catalog
from .connectors.registry import build_default_registry
from .entitlements import EntitlementEngine
from .errors import QueryError
from .freshness import FreshnessCache
from .observability import QUERY_COUNTER, init_tracing, metrics_response
from .planner import Planner, QueryResponse
from .rate_limit import BudgetConfig, HierarchicalRateLimiter
from .settings import SETTINGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------------- bootstrap ----------------
init_tracing()
registry = build_default_registry()
catalog = Catalog(registry)
entitlements = EntitlementEngine(SETTINGS.policy_path)
rate_limiter = HierarchicalRateLimiter({
    "github": BudgetConfig(
        global_per_minute=SETTINGS.github_rpm_global,
        tenant_per_minute=SETTINGS.github_rpm_tenant,
        user_per_minute=SETTINGS.github_rpm_user,
    ),
    "jira": BudgetConfig(
        global_per_minute=SETTINGS.jira_rpm_global,
        tenant_per_minute=SETTINGS.jira_rpm_tenant,
        user_per_minute=SETTINGS.jira_rpm_user,
    ),
})
freshness = FreshnessCache()
planner = Planner(catalog, registry, entitlements, rate_limiter, freshness)
get_current_user = make_auth_dep(entitlements)


app = FastAPI(title="Universal SQL Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
FastAPIInstrumentor.instrument_app(app)


# ---------------- request/response models ----------------
class QueryRequest(BaseModel):
    sql: str = Field(..., description="SELECT statement; subset of SQL — see docs")
    max_staleness_seconds: int = Field(SETTINGS.default_ttl_seconds, ge=0, le=3600,
                                       description="Largest acceptable cache age in seconds")
    timeout_seconds: float = Field(30.0, gt=0, le=300,
                                   description="Per-source fetch deadline. Slow sources past this "
                                               "deadline return empty rows; the response is marked "
                                               "partial=true with partial_sources listing which "
                                               "sources timed out.")


class QueryResponseModel(BaseModel):
    rows: list
    columns: list[str]
    freshness_ms: int
    rate_limit_status: str
    trace_id: str
    cache_status: dict
    rows_per_source: dict
    partial: bool = False
    partial_sources: list[str] = []


# ---------------- routes ----------------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


@app.get("/v1/tables")
def list_tables(user: User = Depends(get_current_user)):
    """Returns tables visible to this user's tenant."""
    out = []
    for table in catalog.all_tables():
        try:
            entitlements.assert_table_allowed(user.tenant, table)
        except Exception:
            continue
        out.append({
            "name": table,
            "columns": catalog.table_columns(table),
            "join_keys": catalog.join_keys(table),
        })
    return {"tables": out}


@app.post("/v1/query", response_model=QueryResponseModel)
async def query(req: QueryRequest, user: User = Depends(get_current_user)):
    try:
        result: QueryResponse = await planner.execute(
            req.sql, user, req.max_staleness_seconds, timeout_seconds=req.timeout_seconds,
        )
        result_label = "partial" if result.partial else "ok"
        QUERY_COUNTER.labels(tenant=user.tenant, result=result_label).inc()
        return QueryResponseModel(
            rows=result.rows,
            columns=result.columns,
            freshness_ms=result.freshness_ms,
            rate_limit_status=result.rate_limit_status,
            trace_id=result.trace_id,
            cache_status=result.cache_status,
            rows_per_source=result.rows_per_source,
            partial=result.partial,
            partial_sources=result.partial_sources,
        )
    except QueryError as e:
        QUERY_COUNTER.labels(tenant=user.tenant, result=e.code).inc()
        headers = {}
        if e.retry_after is not None:
            headers["Retry-After"] = str(int(e.retry_after) + 1)
        raise HTTPException(status_code=e.http_status, detail=e.to_payload(), headers=headers)
