"""Connector registry — table_name → Connector instance.

Production: descriptors loaded from the Catalog service.
Prototype: in-process map populated at startup.
"""
from __future__ import annotations
from typing import Dict

from .base import Connector
from .github_mock import GitHubMockConnector
from .jira_mock import JiraMockConnector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._by_table: Dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._by_table[connector.capability.table_name] = connector

    def get(self, table_name: str) -> Connector:
        if table_name not in self._by_table:
            raise KeyError(f"No connector registered for table {table_name}")
        return self._by_table[table_name]

    def tables(self) -> list[str]:
        return list(self._by_table.keys())


def build_default_registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(GitHubMockConnector())
    reg.register(JiraMockConnector())
    return reg
