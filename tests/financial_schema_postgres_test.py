from __future__ import annotations

import hashlib
import os
import threading
import time
from urllib.parse import urlparse

import pytest

from services.financial_schema import (
    FinancialSchemaError,
    Migration,
    apply_financial_migrations,
)


DSN = os.getenv("FINANCIAL_SCHEMA_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="FINANCIAL_SCHEMA_TEST_DATABASE_URL is not configured",
)


def _assert_disposable_database() -> None:
    parsed = urlparse(DSN)
    database = parsed.path.removeprefix("/")
    assert parsed.hostname in {"127.0.0.1", "localhost"}
    assert database.endswith("_test")


def _reset_database() -> None:
    import psycopg

    _assert_disposable_database()
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute("DROP TABLE IF EXISTS financial_schema_atomic_probe CASCADE")
        connection.execute("DROP TABLE IF EXISTS financial_schema_race_probe CASCADE")
        connection.execute("DROP TABLE IF EXISTS financial_schema_migrations CASCADE")
        connection.execute("DROP FUNCTION IF EXISTS delay_financial_schema_insert() CASCADE")


def _migration(version: int, filename: str, sql: str) -> Migration:
    return Migration(version, filename, sql, hashlib.sha256(sql.encode()).hexdigest())


def test_migration_ddl_rolls_back_when_ledger_insert_fails():
    import psycopg

    _reset_database()
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE financial_schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                filename TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                applied_by TEXT NOT NULL DEFAULT current_user
            )
            """
        )
        connection.execute(
            """
            INSERT INTO financial_schema_migrations(version, filename, checksum)
            VALUES (1, 'collision.sql', %s)
            """,
            ("0" * 64,),
        )

    sql = """BEGIN;
CREATE TABLE financial_schema_atomic_probe(id INTEGER PRIMARY KEY);
COMMIT;
"""
    migration = _migration(2, "collision.sql", sql)

    with pytest.raises(FinancialSchemaError, match="migration failed"):
        apply_financial_migrations(DSN, migrations=[migration])

    with psycopg.connect(DSN) as connection:
        table = connection.execute(
            "SELECT to_regclass('public.financial_schema_atomic_probe')"
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT version, filename FROM financial_schema_migrations ORDER BY version"
        ).fetchall()
    assert table is None
    assert rows == [(1, "collision.sql")]


def test_concurrent_migrator_cannot_enter_ledger_window_after_migration_sql():
    import psycopg

    _reset_database()
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE financial_schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                filename TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                applied_by TEXT NOT NULL DEFAULT current_user
            )
            """
        )
        connection.execute(
            """
            CREATE FUNCTION delay_financial_schema_insert() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                PERFORM pg_sleep(2);
                RETURN NEW;
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER delay_financial_schema_insert_trigger
            BEFORE INSERT ON financial_schema_migrations
            FOR EACH ROW EXECUTE FUNCTION delay_financial_schema_insert()
            """
        )

    sql = """BEGIN;
CREATE TABLE IF NOT EXISTS financial_schema_race_probe(id INTEGER PRIMARY KEY);
COMMIT;
"""
    migration = _migration(2, "002_race.sql", sql)
    first_result: dict[str, object] = {}

    def first_runner() -> None:
        try:
            first_result["value"] = apply_financial_migrations(
                DSN,
                migrations=[migration],
                connection_factory=lambda dsn: psycopg.connect(
                    dsn, application_name="financial-schema-race-one"
                ),
            )
        except Exception as exc:  # pragma: no cover - assertion reports exact exception
            first_result["error"] = exc

    worker = threading.Thread(target=first_runner, daemon=True)
    worker.start()

    deadline = time.monotonic() + 10
    reached_ledger_insert = False
    with psycopg.connect(DSN, autocommit=True) as observer:
        while time.monotonic() < deadline:
            reached_ledger_insert = bool(
                observer.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_stat_activity
                        WHERE application_name = 'financial-schema-race-one'
                          AND state = 'active'
                          AND query ILIKE '%INSERT INTO financial_schema_migrations%'
                    )
                    """
                ).fetchone()[0]
            )
            if reached_ledger_insert:
                break
            time.sleep(0.05)
    assert reached_ledger_insert, "first migrator never reached the delayed ledger insert"

    with pytest.raises(FinancialSchemaError, match="migration lock is held"):
        apply_financial_migrations(
            DSN,
            migrations=[migration],
            connection_factory=lambda dsn: psycopg.connect(
                dsn, application_name="financial-schema-race-two"
            ),
        )

    worker.join(timeout=10)
    assert not worker.is_alive()
    assert "error" not in first_result
    assert first_result["value"] == {
        "applied": [2],
        "current_version": 2,
        "ready": True,
    }

    with psycopg.connect(DSN) as connection:
        ledger_count = connection.execute(
            "SELECT count(*) FROM financial_schema_migrations WHERE version = 2"
        ).fetchone()[0]
        table = connection.execute(
            "SELECT to_regclass('public.financial_schema_race_probe')"
        ).fetchone()[0]
    assert ledger_count == 1
    assert table == "financial_schema_race_probe"
