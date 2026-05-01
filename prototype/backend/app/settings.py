"""Configuration loaded from environment with sensible local defaults."""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Connector mode: "mock" (deterministic, used for tests/load) or "live" (real APIs)
    connector_mode: str = os.getenv("CONNECTOR_MODE", "mock")

    # Real API credentials (only used when connector_mode=live)
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    jira_base_url: str = os.getenv("JIRA_BASE_URL", "")
    jira_email: str = os.getenv("JIRA_EMAIL", "")
    jira_token: str = os.getenv("JIRA_TOKEN", "")

    # Rate-limit budgets (per minute). Conservative for the prototype.
    github_rpm_global: int = int(os.getenv("GITHUB_RPM_GLOBAL", "300"))
    github_rpm_tenant: int = int(os.getenv("GITHUB_RPM_TENANT", "120"))
    github_rpm_user: int = int(os.getenv("GITHUB_RPM_USER", "60"))
    jira_rpm_global: int = int(os.getenv("JIRA_RPM_GLOBAL", "300"))
    jira_rpm_tenant: int = int(os.getenv("JIRA_RPM_TENANT", "120"))
    jira_rpm_user: int = int(os.getenv("JIRA_RPM_USER", "60"))

    # Freshness defaults
    default_ttl_seconds: int = int(os.getenv("DEFAULT_TTL_SECONDS", "300"))

    # Auth — for the prototype we accept a header X-User-Id; production swaps to OIDC.
    dev_auth: bool = os.getenv("DEV_AUTH", "true").lower() == "true"

    # Policy file
    policy_path: str = os.getenv("POLICY_PATH", "policies/default.yaml")


SETTINGS = Settings()
