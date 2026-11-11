from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.financial_schema import (
    APPLICATION_SCHEMA_MAX,
    APPLICATION_SCHEMA_MIN,
    FinancialSchemaError,
    Migration,
    apply_financial_migrations,
    load_financial_migrations,
    verify_financial_schema,
)


ROOT = Path(__file__).parents[1]


def test_canonical_migrations_are_versioned_additive_and_checksums_are_stable():
    migrations = load_financial_migrations(ROOT / "dashboard_api" / "migrations")

    assert [migration.version for migration in migrations] == [9, 10, 11, 12, 13]
    assert all(migration.sha256 == hashlib.sha256(migration.sql.encode()).hexdigest() for migration in migrations)
    combined = "\n".join(migration.sql for migration in migrations).lower()
    assert "opening_balances" in combined
    assert "interwallet_debt_events_effective_type_check" in combined
    assert "event_type in ('correction', 'reversal')" in combined
    assert "balance_adjustments" in combined
    assert "financial_transactions" in combined
    assert "interwallet_debts" in combined
    assert "financial_export_outbox" in combined
    assert "financial_migration_manifest" in combined
    assert "cannot be mutated or hard deleted" in combined
    assert "corrects_event_id" in combined
    assert "interwallet debts cannot be mutated or hard deleted" in combined
    assert "create constraint trigger trg_financial_transaction_balanced" in combined
    assert "create constraint trigger trg_financial_postings_balanced" in combined
    assert "create extension" not in combined


class _Cursor:
    def __init__(self, applied=()):
        self.applied = list(applied)
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "from financial_schema_migrations" in normalized and "select version" in normalized:
            self._result = list(self.applied)
        elif "pg_try_advisory_xact_lock" in normalized:
            self._result = [(True,)]
        elif "select max(version)" in normalized:
            self._result = [(self.applied[-1][0] if self.applied else None,)]
        elif "select checksum" in normalized:
            version = params[0]
            row = next((item for item in self.applied if item[0] == version), None)
            self._result = [(row[1],)] if row else []
        else:
            self._result = []

    def fetchall(self):
        return list(self._result or [])

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_one_shot_migration_uses_advisory_lock_and_records_checksum_once():
    migration = Migration(9, "009_test.sql", "SELECT 1", hashlib.sha256(b"SELECT 1").hexdigest())
    cursor = _Cursor()
    connection = _Connection(cursor)

    result = apply_financial_migrations(
        "postgres://test",
        migrations=[migration],
        connection_factory=lambda _dsn: connection,
    )

    sql = "\n".join(item[0] for item in cursor.executed).lower()
    assert "pg_try_advisory_xact_lock" in sql
    assert "insert into financial_schema_migrations" in sql
    assert result == {"applied": [9], "current_version": 9, "ready": True}
    assert connection.commits == 1


def test_schema_readiness_is_read_only_and_rejects_checksum_drift():
    migration = Migration(9, "009_test.sql", "SELECT 1", hashlib.sha256(b"SELECT 1").hexdigest())
    cursor = _Cursor(applied=[(9, "0" * 64, "009_test.sql")])
    connection = _Connection(cursor)

    with pytest.raises(FinancialSchemaError, match="checksum"):
        verify_financial_schema(
            "postgres://test",
            migrations=[migration],
            minimum=9,
            maximum=9,
            connection_factory=lambda _dsn: connection,
        )

    assert connection.commits == 0
    assert not any("create table" in sql.lower() for sql, _ in cursor.executed)
    assert APPLICATION_SCHEMA_MIN <= APPLICATION_SCHEMA_MAX


def test_migration_refuses_to_modify_a_schema_newer_than_the_release():
    migration = Migration(9, "009_test.sql", "SELECT 1", hashlib.sha256(b"SELECT 1").hexdigest())
    cursor = _Cursor(applied=[(10, "1" * 64, "010_future.sql")])
    connection = _Connection(cursor)

    with pytest.raises(FinancialSchemaError, match="newer"):
        apply_financial_migrations(
            "postgres://test",
            migrations=[migration],
            connection_factory=lambda _dsn: connection,
        )

    assert not any(sql == migration.sql for sql, _ in cursor.executed)
