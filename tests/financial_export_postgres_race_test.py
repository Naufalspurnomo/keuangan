from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.finance_write_authority import (
    FinanceAuthorityLatchError,
    assert_finance_authority_configuration,
    legacy_sheets_finance_writes_fenced,
)
from services.financial_export_worker import PostgresExportOutbox
from services.financial_transaction_repository import (
    FinancialRepositoryConflict,
    PostgresFinancialTransactionRepository,
)
from services.financial_schema import apply_financial_migrations, load_production_bootstrap_migrations


DSN = os.getenv("FINANCIAL_EXPORT_TEST_DATABASE_URL", "")
ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(not DSN, reason="FINANCIAL_EXPORT_TEST_DATABASE_URL is not configured")


def _connection():
    import psycopg

    return psycopg.connect(DSN)


@pytest.fixture(scope="module", autouse=True)
def _canonical_schema():
    apply_financial_migrations(
        DSN,
        migrations=load_production_bootstrap_migrations(ROOT / "dashboard_api" / "migrations"),
    )


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


def test_finance_authority_latch_is_one_way_and_fences_legacy_writers():
    evidence = hashlib.sha256(b"owner-approved-activation-evidence").hexdigest()
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT authority FROM finance_authority_state WHERE singleton = TRUE")
        authority = cursor.fetchone()[0]
        if authority == "google_sheets":
            cursor.execute(
                """
                UPDATE finance_authority_state
                   SET authority = 'postgresql',
                       activated_at = now(),
                       activated_by = 'ci:authority-latch',
                       activation_evidence_sha256 = %s
                 WHERE singleton = TRUE
                """,
                (evidence,),
            )

    assert assert_finance_authority_configuration(DSN, writes_enabled=True) == "postgresql"
    with pytest.raises(FinanceAuthorityLatchError, match="mismatch"):
        assert_finance_authority_configuration(DSN, writes_enabled=False)
    assert legacy_sheets_finance_writes_fenced(
        {"DATABASE_URL": DSN},
    ) is True

    with pytest.raises(Exception, match="cannot return to google_sheets"):
        with _connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE finance_authority_state SET authority = 'google_sheets' WHERE singleton = TRUE"
            )

    with pytest.raises(Exception, match="activation evidence is immutable"):
        with _connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE finance_authority_state
                   SET activation_evidence_sha256 = %s
                 WHERE singleton = TRUE
                """,
                ("0" * 64,),
            )


def test_transaction_idempotency_is_atomic_across_real_postgres_connections():
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT setval(
                'financial_export_ordinal_seq',
                GREATEST(COALESCE((SELECT max(export_ordinal) FROM financial_export_outbox), 0), 1),
                COALESCE((SELECT max(export_ordinal) FROM financial_export_outbox), 0) > 0
            )
            """
        )
    key_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    request_hash = hashlib.sha256(b"same canonical request").hexdigest()
    barrier = threading.Barrier(2)

    def append(index: int):
        transaction_id = str(uuid.uuid4())
        payload = {"schema_version": "canonical.finance.transaction.v1", "request": "same"}
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        record = {
            "id": transaction_id,
            "scope": "group",
            "project_id": None,
            "transaction_type": "adjustment",
            "flow_class": "adjustment",
            "amount": 1000,
            "currency": "IDR",
            "category": "ci",
            "description": "Concurrent idempotency test",
            "occurred_at": "2026-11-16T00:00:00Z",
            "source": "system",
            "source_reference": None,
            "evidence": {},
            "actor": {"type": "system", "id": "ci"},
            "revision_of_id": None,
            "reversal_of_id": None,
            "version": 1,
            "status": "posted",
            "postings": [
                {
                    "id": str(uuid.uuid4()),
                    "wallet_id": None,
                    "business_unit_id": None,
                    "account_class": "revenue",
                    "signed_amount": 1000,
                    "currency": "IDR",
                },
                {
                    "id": str(uuid.uuid4()),
                    "wallet_id": None,
                    "business_unit_id": None,
                    "account_class": "expense",
                    "signed_amount": -1000,
                    "currency": "IDR",
                },
            ],
        }
        outbox = {
            "id": str(uuid.uuid4()),
            "export_key": f"transaction:{transaction_id}:v1",
            "payload": payload,
            "payload_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
        }
        barrier.wait(timeout=5)
        return PostgresFinancialTransactionRepository(DSN).append(
            record,
            idempotency_key_hash=key_hash,
            request_hash=request_hash,
            outbox_payload=outbox,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(2)))

    assert sorted(replayed for _record, replayed in results) == [False, True]
    transaction_id = results[0][0]["id"]
    assert results[1][0]["id"] == transaction_id
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM financial_transactions WHERE idempotency_key_hash = %s",
            (key_hash,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT count(*) FROM financial_export_outbox WHERE aggregate_id = %s",
            (transaction_id,),
        )
        assert cursor.fetchone()[0] == 1

    with pytest.raises(FinancialRepositoryConflict, match="different request"):
        PostgresFinancialTransactionRepository(DSN).append(
            {},
            idempotency_key_hash=key_hash,
            request_hash=hashlib.sha256(b"conflicting request").hexdigest(),
            outbox_payload={},
        )
