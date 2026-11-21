"""Bounded process-local PostgreSQL connection reuse for dashboard repositories."""

from __future__ import annotations

import atexit
import os
from collections.abc import Callable
from typing import Any


class PostgresPoolConfigurationError(RuntimeError):
    """Fail-closed pool configuration error without connection details."""


def _integer(name: str, default: int) -> int:
    raw = str(os.getenv(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise PostgresPoolConfigurationError(f"{name} must be an integer") from exc
    if value < 1:
        raise PostgresPoolConfigurationError(f"{name} must be positive")
    return value


def _seconds(name: str, default: float) -> float:
    raw = str(os.getenv(name, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise PostgresPoolConfigurationError(f"{name} must be numeric") from exc
    if not 0 < value <= 30:
        raise PostgresPoolConfigurationError(f"{name} must be between 0 and 30 seconds")
    return value


def _default_pool_factory():
    from psycopg_pool import ConnectionPool

    return ConnectionPool


class _ConnectionLease:
    """Transparent connection proxy that always returns the checkout to its pool."""

    def __init__(self, pool: Any, connection: Any) -> None:
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "raw", connection)
        object.__setattr__(self, "_returned", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_pool", "raw", "_returned"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self.raw, name, value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_value, _traceback) -> None:
        if self._returned:
            return
        try:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            self.close()

    def close(self) -> None:
        if self._returned:
            return
        object.__setattr__(self, "_returned", True)
        self._pool.putconn(self.raw)


class PostgresConnectionPool:
    """One bounded pool per worker; each checkout remains one repository transaction."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 2,
        max_size: int = 4,
        timeout: float = 10.0,
        pool_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise PostgresPoolConfigurationError("database DSN is required")
        if min_size < 1:
            raise PostgresPoolConfigurationError("pool minimum must be positive")
        if max_size < min_size:
            raise PostgresPoolConfigurationError("pool maximum must be at least the minimum")
        if max_size > 8:
            raise PostgresPoolConfigurationError("pool maximum must not exceed 8 per worker")
        if not 0 < timeout <= 30:
            raise PostgresPoolConfigurationError("pool timeout must be between 0 and 30 seconds")

        factory = pool_factory or _default_pool_factory()
        self._timeout = float(timeout)
        self._closed = False
        self._opened = False
        self._pool = factory(
            self._dsn,
            min_size=int(min_size),
            max_size=int(max_size),
            timeout=self._timeout,
            open=False,
            close_returns=True,
            check=None,
            max_lifetime=900.0,
            max_idle=300.0,
        )
        atexit.register(self.close)

    @classmethod
    def from_environment(
        cls,
        dsn: str,
        *,
        pool_factory: Callable[..., Any] | None = None,
    ) -> "PostgresConnectionPool":
        return cls(
            dsn,
            min_size=_integer("DASHBOARD_DB_POOL_MIN_SIZE", 2),
            max_size=_integer("DASHBOARD_DB_POOL_MAX_SIZE", 4),
            timeout=_seconds("DASHBOARD_DB_POOL_TIMEOUT_SECONDS", 10.0),
            pool_factory=pool_factory,
        )

    def open(self) -> None:
        if self._closed:
            raise PostgresPoolConfigurationError("database pool is closed")
        if self._opened:
            return
        try:
            self._pool.open(wait=True, timeout=self._timeout)
        except Exception as exc:
            raise PostgresPoolConfigurationError(
                f"database pool unavailable: {type(exc).__name__}"
            ) from exc
        self._opened = True

    def connect(self, dsn: str, *, autocommit: bool = False, **_kwargs: Any):
        if str(dsn or "").strip() != self._dsn:
            raise PostgresPoolConfigurationError("database pool DSN mismatch")
        if not self._opened:
            self.open()
        connection = None
        try:
            connection = self._pool.getconn(timeout=self._timeout)
            connection.autocommit = bool(autocommit)
            return _ConnectionLease(self._pool, connection)
        except PostgresPoolConfigurationError:
            raise
        except Exception as exc:
            if connection is not None:
                self._pool.putconn(connection)
            raise PostgresPoolConfigurationError(
                f"database connection unavailable: {type(exc).__name__}"
            ) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.close()
