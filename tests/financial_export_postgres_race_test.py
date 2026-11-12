from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.financial_export_worker import PostgresExportOutbox
from services.financial_schema import apply_financial_migrations, load_financial_migrations


DSN = os.getenv("FINANCIAL_EXPORT_TEST_DATABASE_URL", "")
ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(not DSN, reason="FINANCIAL_EXPORT_TEST_DATABASE_URL is not configured")


def _connection():
    import psycopg

    return psycopg.connect(DSN)


def _seed_rows(count: int) -> list[str]:
    ids: list[str] = []
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM financial_export_outbox")
        for ordinal in range(1, count + 1):
            row_id = str(uuid.uuid4())
            aggregate_id = str(uuid.uuid4())
            payload = {"schema_version": "canonical.finance.transaction.v1", "ordinal": ordinal}
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            cursor.execute(
                """
                INSERT INTO financial_export_outbox (
                    id, aggregate_type, aggregate_id, aggregate_version,
                    export_key, payload, payload_sha256, destination, export_ordinal
                ) VALUES (%s, 'transaction', %s, 1, %s, %s::jsonb, %s, 'google_sheets', %s)
                """,
                (
                    row_id,
                    aggregate_id,
                    f"transaction:{aggregate_id}:v1",
                    payload_json,
                    hashlib.sha256(payload_json.encode()).hexdigest(),
                    ordinal,
                ),
            )
            ids.append(row_id)
    return ids


def test_two_workers_claim_disjoint_rows_and_stale_tokens_cannot_ack():
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS projects (id UUID PRIMARY KEY)")
    apply_financial_migrations(
        DSN,
        migrations=load_financial_migrations(ROOT / "dashboard_api" / "migrations"),
    )
    expected_ids = set(_seed_rows(20))
    barrier = threading.Barrier(2)

    def claim_worker():
        store = PostgresExportOutbox(DSN, connection_factory=lambda _dsn: _connection())
        barrier.wait(timeout=5)
        return store, store.claim(limit=20, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(claim_worker)
        second_future = pool.submit(claim_worker)
        first_store, first_claims = first_future.result(timeout=15)
        second_store, second_claims = second_future.result(timeout=15)

    first_ids = {row.id for row in first_claims}
    second_ids = {row.id for row in second_claims}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == expected_ids
    assert len(first_claims) + len(second_claims) == 20

    owner_store, owner_claim = (first_store, first_claims[0]) if first_claims else (second_store, second_claims[0])
    stale_token = str(uuid.uuid4())
    assert owner_store.acknowledge(owner_claim.id, stale_token, "canonical-export!A2:J2") is False
    assert owner_store.acknowledge(
        owner_claim.id,
        owner_claim.claim_token,
        "canonical-export!A2:J2",
    ) is True

    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, claim_token, remote_locator FROM financial_export_outbox WHERE id = %s",
            (owner_claim.id,),
        )
        status, claim_token, locator = cursor.fetchone()
    assert status == "exported"
    assert claim_token is None
    assert locator == "canonical-export!A2:J2"
