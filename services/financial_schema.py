"""One-shot canonical finance migrations and read-only runtime compatibility checks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


APPLICATION_SCHEMA_MIN = 14
APPLICATION_SCHEMA_MAX = 14
MIGRATION_LOCK_ID = 0x484F4C4C415741  # stable "HOLLAWA" advisory lock namespace
_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_.*\.sql$")


class FinancialSchemaError(RuntimeError):
    """The canonical schema cannot safely be migrated or used."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    filename: str
    sql: str
    sha256: str


def load_financial_migrations(root: Path | None = None) -> list[Migration]:
    migration_root = root or Path(__file__).parents[1] / "dashboard_api" / "migrations"
    migrations: list[Migration] = []
    for path in sorted(migration_root.glob("*.sql")):
        match = _MIGRATION_PATTERN.match(path.name)
        if match is None:
            continue
        version = int(match.group("version"))
        if version < 9:
            continue
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(version, path.name, sql, hashlib.sha256(sql.encode("utf-8")).hexdigest())
        )
    versions = [migration.version for migration in migrations]
    if versions != list(range(9, APPLICATION_SCHEMA_MAX + 1)):
        raise FinancialSchemaError(f"canonical migration set is incomplete: {versions}")
    return migrations


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn)


def _selected_migrations(migrations: Iterable[Migration] | None) -> list[Migration]:
    return list(migrations) if migrations is not None else load_financial_migrations()


def apply_financial_migrations(
    dsn: str,
    *,
    migrations: Iterable[Migration] | None = None,
    connection_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Apply migrations once under a transaction-scoped PostgreSQL advisory lock.

    This function is for a restricted release job only. Application startup must
    call :func:`verify_financial_schema`, which executes SELECT statements only.
    """

    selected_dsn = str(dsn or "").strip()
    if not selected_dsn:
        raise FinancialSchemaError("canonical finance migration requires a database DSN")
    selected = _selected_migrations(migrations)
    connector = connection_factory or _connect
    applied_now: list[int] = []
    try:
        with connector(selected_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                lock_row = cursor.fetchone()
                if lock_row is None or not bool(lock_row[0]):
                    raise FinancialSchemaError("canonical finance migration lock is held")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS financial_schema_migrations (
                        version INTEGER PRIMARY KEY CHECK (version > 0),
                        filename TEXT NOT NULL UNIQUE,
                        checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        applied_by TEXT NOT NULL DEFAULT current_user
                    )
                    """
                )
                cursor.execute(
                    "SELECT version, checksum, filename FROM financial_schema_migrations ORDER BY version"
                )
                existing = {int(row[0]): (str(row[1]), str(row[2])) for row in cursor.fetchall()}
                newest_supported = max((migration.version for migration in selected), default=0)
                if existing and max(existing) > newest_supported:
                    raise FinancialSchemaError(
                        f"canonical finance schema is newer than this release: "
                        f"{max(existing)} > {newest_supported}"
                    )
                for migration in selected:
                    recorded = existing.get(migration.version)
                    if recorded is not None:
                        if recorded != (migration.sha256, migration.filename):
                            raise FinancialSchemaError(
                                f"migration checksum or filename mismatch at version {migration.version}"
                            )
                        continue
                    cursor.execute(migration.sql)
                    cursor.execute(
                        """
                        INSERT INTO financial_schema_migrations(version, filename, checksum)
                        VALUES (%s, %s, %s)
                        """,
                        (migration.version, migration.filename, migration.sha256),
                    )
                    applied_now.append(migration.version)
            connection.commit()
    except FinancialSchemaError:
        raise
    except Exception as exc:
        raise FinancialSchemaError(f"canonical finance migration failed: {type(exc).__name__}") from exc
    return {
        "applied": applied_now,
        "current_version": max((migration.version for migration in selected), default=0),
        "ready": True,
    }


def verify_financial_schema(
    dsn: str,
    *,
    migrations: Iterable[Migration] | None = None,
    minimum: int = APPLICATION_SCHEMA_MIN,
    maximum: int = APPLICATION_SCHEMA_MAX,
    connection_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Verify exact version/checksum compatibility without running DDL or writes."""

    selected_dsn = str(dsn or "").strip()
    if not selected_dsn:
        raise FinancialSchemaError("canonical finance schema check requires a database DSN")
    selected = _selected_migrations(migrations)
    expected = {item.version: (item.sha256, item.filename) for item in selected}
    connector = connection_factory or _connect
    try:
        with connector(selected_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT version, checksum, filename FROM financial_schema_migrations ORDER BY version"
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise FinancialSchemaError(f"canonical finance schema is unavailable: {type(exc).__name__}") from exc

    observed = {int(row[0]): (str(row[1]), str(row[2])) for row in rows}
    if not observed:
        raise FinancialSchemaError("canonical finance schema is not migrated")
    current = max(observed)
    if current < minimum:
        raise FinancialSchemaError(f"canonical finance schema is too old: {current} < {minimum}")
    if current > maximum:
        raise FinancialSchemaError(f"canonical finance schema is too new: {current} > {maximum}")
    for version, contract in expected.items():
        if version > current:
            continue
        if observed.get(version) != contract:
            raise FinancialSchemaError(f"canonical finance migration checksum mismatch at version {version}")
    missing = sorted(version for version in expected if version <= current and version not in observed)
    if missing:
        raise FinancialSchemaError(f"canonical finance schema is partial: missing {missing}")
    return {
        "ready": True,
        "current_version": current,
        "compatible_min": minimum,
        "compatible_max": maximum,
        "checksums_verified": len([version for version in expected if version <= current]),
    }
