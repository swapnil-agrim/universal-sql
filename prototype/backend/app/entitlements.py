"""Entitlement engine — compiles policy YAML into RLS predicates and CLS masks.

Policy YAML shape (see policies/default.yaml):
  users:    user_id → {tenant, roles, attrs}
  tenants:  tenant_id → {allowed_tables: [...]}
  policies: list of {table, rls?, cls?}

An RLS rule produces a Predicate that is ANDed into the FetchSpec for the
table. A CLS rule produces a column mask that is applied to projected rows
just before they leave the planner.

Production: replace with OPA/Rego or a typed DSL with formal semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from .connectors.base import Predicate
from .errors import EntitlementDenied


MASK_REDACT = "redact"
MASK_HASH = "hash"


@dataclass
class ColumnMask:
    column: str
    strategy: str  # redact | hash

    def apply(self, value: Any) -> Any:
        if value is None:
            return None
        if self.strategy == MASK_REDACT:
            return "[REDACTED]"
        if self.strategy == MASK_HASH:
            import hashlib
            return hashlib.sha256(str(value).encode()).hexdigest()[:12]
        return value


class EntitlementEngine:
    def __init__(self, path: str) -> None:
        with open(path, "r") as f:
            self._doc = yaml.safe_load(f)
        self._users: Dict[str, dict] = self._doc.get("users", {})
        self._tenants: Dict[str, dict] = self._doc.get("tenants", {})
        self._policies: List[dict] = self._doc.get("policies", [])

    def user(self, user_id: str) -> Optional[dict]:
        return self._users.get(user_id)

    def assert_table_allowed(self, tenant: str, table: str) -> None:
        tcfg = self._tenants.get(tenant)
        if not tcfg or table not in tcfg.get("allowed_tables", []):
            raise EntitlementDenied(f"Tenant '{tenant}' not entitled to table '{table}'")

    def rls_predicates_for(self, user, table: str) -> List[Predicate]:
        """Returns RLS predicates that must be ANDed into the fetch."""
        out: List[Predicate] = []
        for pol in self._policies:
            if pol.get("table") != table:
                continue
            rls = pol.get("rls")
            if not rls:
                continue
            roles_required = set(rls.get("apply_to_roles", []))
            if roles_required and not (set(user.roles) & roles_required):
                continue
            pred_cfg = rls["predicate"]
            value = pred_cfg.get("value")
            if "value_from_user" in pred_cfg:
                value = user.attrs.get(pred_cfg["value_from_user"])
            if value is None:
                # No value to bind → RLS denies all rows
                raise EntitlementDenied(
                    f"Missing user attribute '{pred_cfg.get('value_from_user')}' required for RLS on {table}"
                )
            out.append(Predicate(column=pred_cfg["column"], op=pred_cfg["op"], value=value))
        return out

    def cls_masks_for(self, user, table: str) -> List[ColumnMask]:
        out: List[ColumnMask] = []
        for pol in self._policies:
            if pol.get("table") != table:
                continue
            cls = pol.get("cls")
            if not cls:
                continue
            apply_roles = set(cls.get("apply_to_roles", []))
            exempt_roles = set(cls.get("apply_to_roles_not_in", []))
            user_roles = set(user.roles)
            if apply_roles and not (user_roles & apply_roles):
                continue
            if exempt_roles and (user_roles & exempt_roles):
                continue
            out.append(ColumnMask(column=cls["mask"]["column"], strategy=cls["mask"]["strategy"]))
        return out
