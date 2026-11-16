from __future__ import annotations

from services.financial_transaction_repository import (
    PostgresFinancialTransactionRepository,
    _idempotency_lock_id,
)


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self._result = None

    def execute(self, sql: str, params=None) -> None:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "where idempotency_key_hash = %s for update" in normalized:
            self._result = ("transaction-existing", "request-hash")
        else:
            self._result = None

    def fetchone(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_first_idempotency_use_is_serialized_before_exact_hash_lookup() -> None:
    cursor = _Cursor()
    connection = _Connection(cursor)
    repository = PostgresFinancialTransactionRepository(
        "postgresql://test/db",
        connection_factory=lambda _dsn: connection,
    )
    repository._read_record = lambda _cursor, transaction_id: {"id": transaction_id}  # type: ignore[method-assign]

    record, replayed = repository.append(
        {"id": "unused-on-replay"},
        idempotency_key_hash="f" * 64,
        request_hash="request-hash",
        outbox_payload={},
    )

    assert record == {"id": "transaction-existing"}
    assert replayed is True
    assert "pg_advisory_xact_lock" in cursor.executed[0][0]
    assert cursor.executed[0][1] == (_idempotency_lock_id("f" * 64),)
    assert "idempotency_key_hash" in cursor.executed[1][0]
    assert cursor.executed[1][1] == ("f" * 64,)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_idempotency_lock_key_is_stable_signed_bigint_and_hash_specific() -> None:
    first = _idempotency_lock_id("a" * 64)

    assert first == _idempotency_lock_id("a" * 64)
    assert first != _idempotency_lock_id("b" * 64)
    assert -(2**63) <= first < 2**63