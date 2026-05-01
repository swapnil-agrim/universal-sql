"""Simplified auth for the prototype.

Production: OIDC verification of a JWT, claims → user/tenant/roles.
Prototype: read X-User-Id header, look up the user in the policy YAML.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Header, HTTPException

from .entitlements import EntitlementEngine


@dataclass(frozen=True)
class User:
    id: str
    tenant: str
    roles: List[str]
    attrs: dict  # arbitrary user attributes referenced by RLS predicates (e.g. allowed_repos)


def make_auth_dep(engine: EntitlementEngine):
    """Returns a FastAPI dependency function bound to the given engine."""

    async def get_current_user(x_user_id: Optional[str] = Header(default=None)) -> User:
        if not x_user_id:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": "Missing X-User-Id header"})
        record = engine.user(x_user_id)
        if not record:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": f"Unknown user {x_user_id}"})
        return User(id=x_user_id, tenant=record["tenant"], roles=record.get("roles", []), attrs=record.get("attrs", {}))

    return get_current_user
