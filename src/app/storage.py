"""Storage port used by the services, plus a CPython sqlite3 implementation.

Durable Objects expose SQLite through ``ctx.storage.sql``; src/glue.py adapts that to
this interface. Tests and the dev server use :class:`SqliteStorage`, so the exact same
SQL runs in both places.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
Row = dict[str, Any]


class Storage(Protocol):
    def query(self, sql: str, *params: Any) -> list[Row]:
        """Run a statement and return all rows as dicts (fully consumed)."""
        ...

    def execute(self, sql: str, *params: Any) -> None:
        """Run a statement that returns no rows."""
        ...

    def transaction(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` atomically; roll back if it raises."""
        ...


class SqliteStorage:
    """sqlite3-backed storage with the same semantics the services rely on."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._depth = 0

    def query(self, sql: str, *params: Any) -> list[Row]:
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def execute(self, sql: str, *params: Any) -> None:
        self._conn.execute(sql, params)

    def executescript(self, script: str) -> None:
        for statement in split_statements(script):
            self._conn.execute(statement)

    def transaction(self, fn: Callable[[], T]) -> T:
        if self._depth:
            return fn()
        self._conn.execute("BEGIN")
        self._depth += 1
        try:
            result = fn()
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
            return result
        finally:
            self._depth -= 1

    def close(self) -> None:
        self._conn.close()


def split_statements(script: str) -> list[str]:
    """Split a schema script on ';'. Our schemas contain no ';' inside literals."""
    return [part.strip() for part in script.split(";") if part.strip()]


def table_exists(storage: Storage, name: str) -> bool:
    rows = storage.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", name)
    return bool(rows)
