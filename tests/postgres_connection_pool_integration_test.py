from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from services.postgres_connection_pool import PostgresConnectionPool


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_DSN"), reason="TEST_POSTGRES_DSN unavailable")
def test_real_pool_reuses_connections_and_cleans_failed_transactions() -> None:
    dsn = os.environ["TEST_POSTGRES_DSN"]
    pool = PostgresConnectionPool(dsn, min_size=2, max_size=4, timeout=5)
    pool.open()
    try:
        first = pool.connect(dsn)
        with first:
            with first.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                first_pid = int(cursor.fetchone()[0])

        failed = pool.connect(dsn)
        with pytest.raises(RuntimeError):
            with failed:
                with failed.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    raise RuntimeError("rollback proof")

        recovered = pool.connect(dsn)
        with recovered:
            with recovered.cursor() as cursor:
                cursor.execute("SELECT current_setting('transaction_isolation')")
                assert cursor.fetchone()[0]

        def read_pid(_index: int) -> int:
            connection = pool.connect(dsn)
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid(), pg_sleep(0.05)")
                    return int(cursor.fetchone()[0])

        with ThreadPoolExecutor(max_workers=4) as executor:
            pids = list(executor.map(read_pid, range(8)))

        assert 1 <= len(set(pids)) <= 4
        assert first_pid in set(pids)

        broken = pool.connect(dsn)
        with broken.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            broken_pid = int(cursor.fetchone()[0])
        with psycopg.connect(dsn, autocommit=True) as terminator:
            with terminator.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(%s)", (broken_pid,))
                assert cursor.fetchone() == (True,)
        with pytest.raises(psycopg.Error):
            with broken:
                with broken.cursor() as cursor:
                    cursor.execute("SELECT 1")
        replacement = pool.connect(dsn)
        with replacement:
            with replacement.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
    finally:
        pool.close()
