from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from services.financial_transaction_repository import PostgresFinancialTransactionRepository


def _record(record_id: str, *, status: str, version: int, revision_of: str | None = None, reversal_of: str | None = None, occurred_at: datetime) -> tuple:
    values = {
        "id": UUID(record_id),
        "scope": "project",
        "project_id": UUID("00000000-0000-4000-8000-000000000010"),
        "transaction_type": "expense",
        "flow_class": "external",
        "amount": 1,
        "currency": "IDR",
        "category": "readiness",
        "description": "batch-read",
        "occurred_at": occurred_at,
        "source": "dashboard",
        "source_reference": None,
        "evidence": {},
        "actor": {"role": "boss"},
        "revision_of_id": UUID(revision_of) if revision_of else None,
        "reversal_of_id": UUID(reversal_of) if reversal_of else None,
        "version": version,
        "status": status,
        "created_at": occurred_at,
    }
    return tuple(values[column] for column in PostgresFinancialTransactionRepository._RECORD_COLUMNS)


class _Cursor:
    def __init__(self, records: list[tuple], postings: list[tuple]) -> None:
        self.records = records
        self.postings = postings
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query: str, _params=None) -> None:
        self.calls.append(" ".join(query.split()))

    def fetchall(self):
        if "FROM financial_postings" in self.calls[-1]:
            return self.postings
        return self.records


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.selected = cursor
        self.closed = False

    def cursor(self):
        return self.selected

    def close(self) -> None:
        self.closed = True


def test_postgres_list_chains_batches_records_and_postings_in_two_queries() -> None:
    root = "00000000-0000-4000-8000-000000000101"
    correction = "00000000-0000-4000-8000-000000000102"
    reversal = "00000000-0000-4000-8000-000000000103"
    active = "00000000-0000-4000-8000-000000000201"
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    records = [
        _record(active, status="posted", version=1, occurred_at=now),
        _record(root, status="posted", version=1, occurred_at=now),
        _record(correction, status="correction", version=2, revision_of=root, occurred_at=now),
        _record(reversal, status="reversal", version=3, reversal_of=correction, occurred_at=now),
    ]
    postings = [
        (UUID("00000000-0000-4000-8000-000000009001"), UUID(active), None, None, "expense", -1, "IDR"),
        (UUID("00000000-0000-4000-8000-000000009002"), UUID(root), None, None, "expense", -1, "IDR"),
        (UUID("00000000-0000-4000-8000-000000009003"), UUID(correction), None, None, "expense", -1, "IDR"),
        (UUID("00000000-0000-4000-8000-000000009004"), UUID(reversal), None, None, "expense", 1, "IDR"),
    ]
    cursor = _Cursor(records, postings)
    connection = _Connection(cursor)
    repository = PostgresFinancialTransactionRepository(
        "postgresql://test",
        connection_factory=lambda _dsn: connection,
    )

    chains = repository.list_chains()

    assert [[str(item["id"]) for item in chain] for chain in chains] == [
        [active],
        [root, correction, reversal],
    ]
    assert len(cursor.calls) == 2
    assert all(chain_item["postings"] for chain in chains for chain_item in chain)
    assert connection.closed is True


def test_postgres_list_chains_rejects_branching_successors() -> None:
    root = "00000000-0000-4000-8000-000000000101"
    child_one = "00000000-0000-4000-8000-000000000102"
    child_two = "00000000-0000-4000-8000-000000000103"
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    cursor = _Cursor(
        [
            _record(root, status="posted", version=1, occurred_at=now),
            _record(child_one, status="correction", version=2, revision_of=root, occurred_at=now),
            _record(child_two, status="correction", version=2, revision_of=root, occurred_at=now),
        ],
        [],
    )
    repository = PostgresFinancialTransactionRepository(
        "postgresql://test",
        connection_factory=lambda _dsn: _Connection(cursor),
    )

    from services.financial_transaction_repository import FinancialRepositoryConflict

    try:
        repository.list_chains()
    except FinancialRepositoryConflict:
        pass
    else:
        raise AssertionError("branching chain must fail closed")
