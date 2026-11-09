from __future__ import annotations

import hashlib
import os
from urllib.parse import urlparse

import pytest

from services import durable_inbox
from services.durable_inbox import ReviewConflict


DSN = os.getenv("INBOX_REVIEW_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="INBOX_REVIEW_TEST_DATABASE_URL is required")


@pytest.fixture
def disposable_review_db(monkeypatch):
    import psycopg

    parsed = urlparse(DSN)
    database = parsed.path.removeprefix("/")
    assert parsed.hostname in {"127.0.0.1", "localhost"}, "test database must be loopback-only"
    assert database.endswith("_test"), "test refuses a database without disposable suffix"
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS transaction_inbox_review_audit CASCADE")
        conn.execute("DROP TABLE IF EXISTS transaction_inbox CASCADE")
    monkeypatch.setenv("STATE_DATABASE_URL", DSN)
    monkeypatch.setenv("DURABLE_INBOX_REQUIRED", "1")
    monkeypatch.setenv("INBOX_REVIEW_WRITES_ENABLED", "1")
    durable_inbox._initialized = False
    assert durable_inbox._ensure_db() is True
    migration = (
        os.path.dirname(os.path.dirname(__file__))
        + "/dashboard_api/migrations/004_inbox_review.sql"
    )
    with psycopg.connect(DSN, autocommit=True) as conn:
        migration_sql = open(migration, encoding="utf-8").read()
        conn.execute(migration_sql)
        conn.execute(migration_sql)
    yield
    durable_inbox._initialized = False


def event_key(message_id: str) -> str:
    return hashlib.sha256(f"wuzapi|chat-1|{message_id}".encode()).hexdigest()


def test_review_command_is_cas_idempotent_and_append_only(disposable_review_db):
    import psycopg

    key = durable_inbox.capture_event({
        "provider": "wuzapi", "chat_id": "chat-1", "message_id": "msg-1",
        "sender_id": "sender-1", "event_type": "text", "body_text": "catat 100",
        "finance_signal": True,
    })
    durable_inbox.mark_event(key, "needs_review_notified", result_status="ambiguous")
    proof = {
        "status": "complete", "message_id": "msg-1", "matches": [],
        "checked_sources": ["wallet-a", "operasional"], "failed_sources": [],
    }

    first = durable_inbox.resolve_review_event(
        key, "ignore", actor="owner@example.test", reason="not a transaction",
        expected_status="needs_review_notified", command_key="command-review-0001",
        ledger_proof=proof,
    )
    replay = durable_inbox.resolve_review_event(
        key, "ignore", actor="owner@example.test", reason="not a transaction",
        expected_status="needs_review_notified", command_key="command-review-0001",
        ledger_proof=proof,
    )
    route_replay = durable_inbox.get_review_command_result(
        "command-review-0001", event_key=key, action="ignore",
        actor="owner@example.test", reason="not a transaction",
        expected_status="needs_review_notified",
    )

    assert first["status"] == "ignored" and first["replayed"] is False
    assert replay["status"] == "ignored" and replay["replayed"] is True
    assert route_replay == {
        "event_key": key, "message_id": "msg-1", "action": "ignore",
        "status": "ignored", "replayed": True,
    }
    with pytest.raises(ReviewConflict):
        durable_inbox.resolve_review_event(
            key, "ignore", actor="owner@example.test", reason="different bytes",
            expected_status="needs_review_notified", command_key="command-review-0001",
            ledger_proof=proof,
        )
    with pytest.raises(ReviewConflict):
        durable_inbox.resolve_review_event(
            key, "ignore", actor="owner@example.test", reason="stale review",
            expected_status="needs_review", command_key="command-review-0002",
            ledger_proof=proof,
        )

    with psycopg.connect(DSN, autocommit=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM transaction_inbox_review_audit").fetchone()[0]
        assert count == 1
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE transaction_inbox_review_audit SET reason = 'tampered'")
