from contextlib import nullcontext
from datetime import date
from pathlib import Path

import pytest

from services.project_document_repository import ProjectDocumentConflict, ProjectDocumentRepository, canonical_json_hash


PROJECT = "11111111-1111-4111-8111-111111111111"
ACTOR = {"email": "owner@example.com", "role": "owner"}
SOURCE = {"amount": 100_000, "date": "2026-11-01", "description": "Cat", "category": None}


def test_classification_migration_is_append_only_and_respects_project_hard_delete():
    sql = (Path(__file__).parents[1] / "dashboard_api/migrations/000_project_expense_classification.sql").read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "OLD.project_id = hollawall_project_hard_delete_target()" in sql
    assert "REFERENCES projects(id) ON DELETE CASCADE" in sql


class Cursor:
    def __init__(self, source=SOURCE, events=()):
        self.source = source
        self.events = events
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        if self.source is None:
            return None
        return self.source["amount"], date.fromisoformat(self.source["date"]), self.source["description"], self.source["category"]

    def fetchall(self):
        return self.events


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return nullcontext(self._cursor)


def repository_for(monkeypatch, cursor):
    repository = ProjectDocumentRepository("postgresql://test")
    monkeypatch.setattr(repository, "_connect", lambda: nullcontext(Connection(cursor)))
    monkeypatch.setattr(repository, "_claim", lambda *args: ("key", "request", None))
    monkeypatch.setattr(repository, "_complete", lambda cursor, key, result: result)
    return repository


def test_review_records_only_classification_and_preserves_transaction(monkeypatch):
    cursor = Cursor()
    repo = repository_for(monkeypatch, cursor)
    result = repo.classify_project_expense(PROJECT, "ledger:1", "project_cost", expected_source=SOURCE,
                                           idempotency_key="test-key-123456789", actor=ACTOR)
    assert result == {"source_key": "ledger:1", "classification": "project_cost", **SOURCE}
    sql = " ".join(query for query, _ in cursor.queries)
    assert "INSERT INTO project_expense_classification_events" in sql
    assert "UPDATE financial_ledger" not in sql and "DELETE FROM" not in sql


def test_review_refuses_changed_source(monkeypatch):
    cursor = Cursor({**SOURCE, "amount": 200_000})
    repo = repository_for(monkeypatch, cursor)
    with pytest.raises(ProjectDocumentConflict, match="transaction changed"):
        repo.classify_project_expense(PROJECT, "ledger:1", "non_cost", expected_source=SOURCE,
                                     idempotency_key="test-key-123456789", actor=ACTOR)
    assert not any("INSERT INTO project_expense_classification_events" in sql for sql, _ in cursor.queries)


def test_review_snapshot_integrity_is_checked(monkeypatch):
    events = [("ledger:1", canonical_json_hash(SOURCE), "project_cost", {**SOURCE, "description": "Changed"})]
    cursor = Cursor(events=events)
    assert repository_for(monkeypatch, cursor).list_expense_classifications(PROJECT) == []


def test_canonical_review_requires_current_project_outflow():
    cursor = Cursor()
    source_key = "postgresql:transaction:22222222-2222-4222-8222-222222222222:v3"
    assert ProjectDocumentRepository._classification_source(cursor, PROJECT, source_key) == SOURCE
    sql, params = cursor.queries[-1]
    assert "project_id = %s" in sql and "transaction_type = 'outflow'" in sql
    assert "successor.revision_of_id" in sql and "successor.reversal_of_id" in sql
    assert params == ("22222222-2222-4222-8222-222222222222", PROJECT, 3)


def test_review_rejects_non_integer_amounts_and_unsupported_types(monkeypatch):
    cursor = Cursor()
    repo = repository_for(monkeypatch, cursor)
    with pytest.raises(ValueError):
        repo.classify_project_expense(PROJECT, "ledger:1", "project_cost", expected_source={**SOURCE, "amount": True}, idempotency_key="test-key-123456789", actor=ACTOR)
    with pytest.raises(ValueError):
        repo.classify_project_expense(PROJECT, "ledger:1", "unknown", expected_source=SOURCE, idempotency_key="test-key-123456789", actor=ACTOR)
    assert cursor.queries == []
