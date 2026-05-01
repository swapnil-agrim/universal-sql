"""Schema catalog — table → column types, join hints.

For the prototype, the catalog is derived from the registered connectors'
capability descriptors. Production: a Postgres-backed metadata service that
versions schemas and tracks drift.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from .connectors.registry import ConnectorRegistry


class Catalog:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    def table_columns(self, table: str) -> List[str]:
        return list(self._registry.get(table).capability.columns)

    def join_keys(self, table: str) -> List[str]:
        return list(self._registry.get(table).capability.join_keys)

    def has_table(self, table: str) -> bool:
        try:
            self._registry.get(table)
            return True
        except KeyError:
            return False

    def all_tables(self) -> List[str]:
        return self._registry.tables()
