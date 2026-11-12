"""Cross-replica lock for Google Sheets read-before-append operations."""

import hashlib
import os
from contextlib import contextmanager

from services.financial_schema import MIGRATION_LOCK_ID


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _lock_id(value: str) -> int:
    raw = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(raw, byteorder="big", signed=True)


@contextmanager
def ledger_write_guard(message_id: str, route: str):
    """Serialize a source transaction across Koyeb workers and replicas."""
    dsn = _database_url()
    identity = str(message_id or "").strip()
    if not dsn:
        yield
        return

    import psycopg

    connection = psycopg.connect(dsn, autocommit=True)
    lock_id = _lock_id(f"{route}|{identity}") if identity else None
    acquired_route_lock = False
    try:
        with connection.cursor() as cursor:
            # Share the cutover lock with activate_canonical_finance.py.  The
            # latch read and the complete legacy Sheets write must be fenced
            # against the one-way PostgreSQL transition.
            cursor.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
            if lock_id is not None:
                cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
                acquired_route_lock = True
        yield
    finally:
        try:
            with connection.cursor() as cursor:
                if acquired_route_lock:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                cursor.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
        finally:
            connection.close()
