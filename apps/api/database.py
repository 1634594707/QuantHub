"""SQLAlchemy 2 connection boundary for SQLite and PostgreSQL."""

from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection, Engine, Result

_engine_lock = Lock()
_engines: dict[str, Engine] = {}


def deployment_mode() -> str:
    mode = os.environ.get("QUANTHUB_DEPLOYMENT_MODE", "local")
    if mode not in {"local", "lan", "postgresql"}:
        raise RuntimeError("QUANTHUB_DEPLOYMENT_MODE 必须是 local、lan 或 postgresql")
    return mode


def database_url(sqlite_path: Path) -> str:
    configured = os.environ.get("QUANTHUB_DATABASE_URL", "").strip()
    if configured:
        return configured
    if deployment_mode() == "postgresql":
        raise RuntimeError("postgresql 模式必须设置 QUANTHUB_DATABASE_URL")
    return f"sqlite+pysqlite:///{sqlite_path.as_posix()}"


def is_postgresql(sqlite_path: Path) -> bool:
    return database_url(sqlite_path).startswith(("postgresql://", "postgresql+psycopg://"))


def engine_for(sqlite_path: Path) -> Engine:
    url = database_url(sqlite_path)
    with _engine_lock:
        engine = _engines.get(url)
        if engine is None:
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if url.startswith("sqlite"):
                sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                kwargs["connect_args"] = {"check_same_thread": False}
            engine = create_engine(url, **kwargs)
            _engines[url] = engine
        return engine


def dispose_engines() -> None:
    with _engine_lock:
        engines = list(_engines.values())
        _engines.clear()
    for engine in engines:
        engine.dispose()


def _postgresql_sql(sql: str) -> str:
    statement = re.sub(
        r"^(\s*)INSERT\s+OR\s+IGNORE\s+INTO",
        r"\1INSERT INTO",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if statement != sql:
        statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return statement.replace("?", "%s")


class ConnectionAdapter:
    def __init__(self, connection: Connection, *, postgresql: bool) -> None:
        self._connection = connection
        self._postgresql = postgresql
        self.rolled_back = False

    def execute(self, sql: str, params: tuple | list | None = None) -> ResultAdapter:
        if self._postgresql and sql.lstrip().upper().startswith("PRAGMA "):
            return ResultAdapter(None)
        statement = _postgresql_sql(sql) if self._postgresql else sql
        result = self._connection.exec_driver_sql(statement, tuple(params or ()))
        return ResultAdapter(result)

    def table_exists(self, table: str) -> bool:
        return inspect(self._connection).has_table(table)

    def column_names(self, table: str) -> set[str]:
        return {column["name"] for column in inspect(self._connection).get_columns(table)}

    def commit(self) -> None:
        # The store context commits the complete unit of work on exit.
        return None

    def rollback(self) -> None:
        self._connection.rollback()
        self.rolled_back = True


class ResultAdapter:
    def __init__(self, result: Result[Any] | None) -> None:
        self._result = result

    @property
    def rowcount(self) -> int:
        return 0 if self._result is None else self._result.rowcount

    def fetchone(self):
        if self._result is None:
            return None
        return self._result.mappings().fetchone()

    def fetchall(self):
        if self._result is None:
            return []
        return self._result.mappings().fetchall()
