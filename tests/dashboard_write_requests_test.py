import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from dashboard_api.write_contracts import TransactionRequest
from services.dashboard_write_requests import (
    DashboardWriteRequestConflict,
    DashboardWriteRequestStore,
    DashboardWriteRequestUnavailable,
)


class FakeDatabase:
    def __init__(self):
        self.rows = {}
        self.executions = []
        self.next_id = 1

    def connect(self, dsn):
        assert dsn == "postgresql://isolated-test"
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, database):
        self.database = database

    def cursor(self):
        return FakeCursor(self.database)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.row = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        params = tuple(params)
        self.database.executions.append((normalized, params))

        if normalized.startswith("INSERT INTO dashboard_write_requests"):
            key_hash, request_hash, request_json, actor_json, message_id = params
            if key_hash in self.database.rows:
                self.row = None
                return
            row = [
                self.database.next_id,
                key_hash,
                request_hash,
                json.loads(request_json),
                json.loads(actor_json),
                message_id,
                "claimed",
                None,
            ]
            self.database.next_id += 1
            self.database.rows[key_hash] = row
            self.row = tuple(row)
            return

        if normalized.startswith("SELECT id, idempotency_key_hash"):
            stored = self.database.rows.get(params[0])
            self.row = tuple(stored) if stored else None
            return

        if normalized.startswith("UPDATE dashboard_write_requests"):
            response_json, status, key_hash, request_hash = params
            stored = self.database.rows.get(key_hash)
            if stored is None or stored[2] != request_hash:
                self.row = None
                return
            stored[6] = status
            stored[7] = json.loads(response_json)
            self.row = tuple(stored)
            return

        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def transaction(**changes):
    values = {
        "idempotency_key": "dashboard-request-0001",
        "date": date(2026, 10, 2),
        "scope": "project",
        "direction": "Pemasukan",
        "amount": 100_000,
        "description": "Pembayaran termin",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "category": "Lain-lain",
        "project": "PROJECT-001",
    }
    values.update(changes)
    return TransactionRequest(**values)


def make_store(database=None):
    database = database or FakeDatabase()
    store = DashboardWriteRequestStore(
        "postgresql://isolated-test",
        connection_factory=database.connect,
    )
    return store, database


def test_claim_hashes_idempotency_key_and_stores_canonical_evidence():
    store, database = make_store()
    request = transaction()

    claim = store.claim(
        request,
        actor={"role": "owner", "email": "owner@example.com"},
        message_id="dashboard:request-0001",
    )

    expected_key_hash = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
    assert claim.claimed is True
    assert claim.idempotency_key_hash == expected_key_hash
    assert claim.status == "claimed"
    assert claim.message_id == "dashboard:request-0001"
    assert claim.canonical_request == {
        "amount": 100_000,
        "category": "Lain-lain",
        "company": "HOLLA",
        "date": "2026-10-02",
        "description": "Pembayaran termin",
        "direction": "Pemasukan",
        "idempotency_key": "dashboard-request-0001",
        "project": "PROJECT-001",
        "scope": "project",
        "wallet": "CV HB(101)",
    }
    assert claim.actor == {"email": "owner@example.com", "role": "owner"}
    assert len(claim.request_hash) == 64
    assert list(database.rows) == [expected_key_hash]

    insert_sql, insert_params = database.executions[0]
    assert "ON CONFLICT (idempotency_key_hash) DO NOTHING" in insert_sql
    assert request.idempotency_key not in insert_params[:2]


def test_duplicate_same_request_replays_stored_claim_without_replacing_evidence():
    store, _ = make_store()
    first = store.claim(
        transaction(),
        actor={"email": "first@example.com", "role": "owner"},
        message_id="dashboard:first",
    )
    replay = store.claim(
        transaction(),
        actor={"email": "second@example.com", "role": "owner"},
        message_id="dashboard:second",
    )

    assert replay.claimed is False
    assert replay.request_id == first.request_id
    assert replay.actor == first.actor
    assert replay.message_id == "dashboard:first"
    assert replay.status == "claimed"


def test_same_idempotency_key_with_different_canonical_request_conflicts():
    store, _ = make_store()
    store.claim(
        transaction(),
        actor={"email": "owner@example.com", "role": "owner"},
        message_id="dashboard:first",
    )

    with pytest.raises(DashboardWriteRequestConflict, match="different canonical request"):
        store.claim(
            transaction(amount=200_000),
            actor={"email": "owner@example.com", "role": "owner"},
            message_id="dashboard:second",
        )


def test_completion_response_is_durable_and_returned_on_replay():
    store, _ = make_store()
    claim = store.claim(
        transaction(),
        actor={"email": "owner@example.com", "role": "owner"},
        message_id="dashboard:first",
    )

    completed = store.complete(
        claim,
        {"transaction_id": "sheet:42", "recorded": True},
    )
    replay = store.claim(
        transaction(),
        actor={"email": "owner@example.com", "role": "owner"},
        message_id="dashboard:replay",
    )

    assert completed.claimed is False
    assert completed.status == "completed"
    assert completed.completion_response == {"recorded": True, "transaction_id": "sheet:42"}
    assert replay.status == "completed"
    assert replay.completion_response == completed.completion_response


def test_failed_completion_status_and_response_are_durable():
    store, _ = make_store()
    claim = store.claim(
        transaction(),
        actor={"email": "owner@example.com", "role": "owner"},
        message_id="dashboard:first",
    )

    failed = store.complete(claim, {"code": "sheet_append_failed"}, status="failed")

    assert failed.status == "failed"
    assert failed.completion_response == {"code": "sheet_append_failed"}


def test_missing_database_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = DashboardWriteRequestStore()

    with pytest.raises(DashboardWriteRequestUnavailable, match="requires STATE_DATABASE_URL or DATABASE_URL"):
        store.claim(
            transaction(),
            actor={"email": "owner@example.com", "role": "owner"},
            message_id="dashboard:first",
        )


def test_database_failure_is_wrapped_and_never_degrades_to_memory():
    def unavailable(_dsn):
        raise OSError("database offline")

    store = DashboardWriteRequestStore(
        "postgresql://isolated-test",
        connection_factory=unavailable,
    )

    with pytest.raises(DashboardWriteRequestUnavailable, match="database unavailable"):
        store.claim(
            transaction(),
            actor={"email": "owner@example.com", "role": "owner"},
            message_id="dashboard:first",
        )


def test_migration_is_additive_and_does_not_write_financial_ledger():
    migration = Path(__file__).parents[1] / "dashboard_api/migrations/002_dashboard_write_requests.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS dashboard_write_requests" in sql
    assert "idempotency_key_hash" in sql
    assert "canonical_request JSONB NOT NULL" in sql
    assert "actor JSONB NOT NULL" in sql
    assert "completion_response JSONB" in sql
    assert "INSERT INTO financial_ledger" not in sql
    assert "ALTER TABLE financial_ledger" not in sql
