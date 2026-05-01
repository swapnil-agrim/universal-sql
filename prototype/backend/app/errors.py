"""Standard error vocabulary — directly maps to the design doc Section 4."""
from __future__ import annotations
from typing import Optional


class QueryError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, *, retry_after: Optional[float] = None, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.details = details or {}

    def to_payload(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            payload["retry_after"] = round(self.retry_after, 2)
        if self.details:
            payload["details"] = self.details
        return payload


class RateLimitExhausted(QueryError):
    code = "RATE_LIMIT_EXHAUSTED"
    http_status = 429


class StaleData(QueryError):
    code = "STALE_DATA"
    http_status = 200  # warning, not failure


class EntitlementDenied(QueryError):
    code = "ENTITLEMENT_DENIED"
    http_status = 403


class SourceTimeout(QueryError):
    code = "SOURCE_TIMEOUT"
    http_status = 504


class SchemaDrift(QueryError):
    code = "SCHEMA_DRIFT"
    http_status = 502


class InvalidQuery(QueryError):
    code = "INVALID_QUERY"
    http_status = 400
