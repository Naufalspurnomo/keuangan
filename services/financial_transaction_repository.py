"""Atomic persistence boundary for the canonical immutable finance ledger.

The PostgreSQL implementation writes transactions, balanced postings, and the
one-way export outbox in one database transaction.  The in-memory
implementation is a deterministic test double with the same idempotency and
optimistic-concurrency semantics.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any


class FinancialRepositoryConflict(RuntimeError):
    """A request conflicts with immutable or concurrently changed state."""


class FinancialRepositoryNotFound(LookupError):
    """The requested canonical financial aggregate does not exist."""


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _idempotency_lock_id(idempotency_key_hash: str) -> int:
    """Derive a stable signed bigint transaction-lock key from the exact hash."""

    digest = hashlib.sha256(idempotency_key_hash.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _root_id(records: Mapping[str, dict[str, Any]], transaction_id: str) -> str:
    current = records.get(transaction_id)
    if current is None:
        raise FinancialRepositoryNotFound("financial transaction not found")
    seen: set[str] = set()
    while current.get("revision_of_id") or current.get("reversal_of_id"):
        if current["id"] in seen:
            raise FinancialRepositoryConflict("financial transaction chain is cyclic")
        seen.add(current["id"])
        parent_id = current.get("revision_of_id") or current.get("reversal_of_id")
        current = records.get(str(parent_id))
        if current is None:
            raise FinancialRepositoryConflict("financial transaction chain is incomplete")
    return str(current["id"])


def _legacy_replay_matches(
    stored: Mapping[str, Any], *, operation: str | None,
    command_target_id: str | None, read_record: Callable[[str], Mapping[str, Any]],
) -> bool:
    """Old hashes bind only the body; prove operation and target from audit links.

    Legacy commands resolved any requested ancestor to the latest revision.
    Only ancestors of the stored command's parent are valid, never the result
    itself or later descendants. No persisted audit data is rewritten.
    """
    revision = stored.get("revision_of_id")
    reversal = stored.get("reversal_of_id")
    if operation == "create":
        return (command_target_id is None and stored.get("status") == "posted"
                and revision is None and reversal is None)
    if operation == "correct" and stored.get("status") == "correction" and not reversal:
        parent = revision
    elif operation == "reverse" and stored.get("status") == "reversal" and not revision:
        parent = reversal
    else:
        return False
    seen = {str(stored["id"])}
    while parent is not None:
        parent_id = str(parent)
        if parent_id in seen:
            return False
        seen.add(parent_id)
        if parent_id == command_target_id:
            return True
        ancestor = read_record(parent_id)
        parent = ancestor.get("revision_of_id") or ancestor.get("reversal_of_id")
    return False


class InMemoryFinancialRepository:
    """Thread-safe repository used for unit tests and local deterministic replay."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._outbox: dict[tuple[str, str, int], dict[str, Any]] = {}

    @property
    def outbox_count(self) -> int:
        with self._lock:
            return len(self._outbox)

    def append(
        self,
        record: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        legacy_request_hash: str | None = None,
        operation: str | None = None,
        command_target_id: str | None = None,
        target_id: str | None = None,
        expected_version: int | None = None,
        outbox_payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            existing = self._idempotency.get(idempotency_key_hash)
            if existing is not None:
                existing_hash, existing_id = existing
                stored = self._records[existing_id]
                if existing_hash != request_hash and not (
                    legacy_request_hash is not None and existing_hash == legacy_request_hash
                    and _legacy_replay_matches(
                        stored, operation=operation, command_target_id=command_target_id,
                        read_record=self.get,
                    )
                ):
                    raise FinancialRepositoryConflict(
                        "idempotency key was already used with a different request"
                    )
                return _clone(self._records[existing_id]), True

            if target_id is not None:
                chain = self._chain_locked(target_id)
                latest = chain[-1]
                if latest["status"] == "reversal":
                    raise FinancialRepositoryConflict("financial transaction is already reversed")
                if latest["id"] != target_id:
                    raise FinancialRepositoryConflict(
                        "financial transaction version changed concurrently"
                    )
                if expected_version is None or latest["version"] != expected_version:
                    raise FinancialRepositoryConflict(
                        "financial transaction version changed concurrently"
                    )

            stored = _clone(dict(record))
            self._records[stored["id"]] = stored
            self._idempotency[idempotency_key_hash] = (request_hash, stored["id"])
            self._outbox[("transaction", stored["id"], stored["version"])] = _clone(
                dict(outbox_payload)
            )
            return _clone(stored), False

    def get(self, transaction_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                return _clone(self._records[transaction_id])
            except KeyError as exc:
                raise FinancialRepositoryNotFound("financial transaction not found") from exc

    def chain(self, transaction_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return _clone(self._chain_locked(transaction_id))

    def _chain_locked(self, transaction_id: str) -> list[dict[str, Any]]:
        root = _root_id(self._records, transaction_id)
        result = [self._records[root]]
        current = result[0]
        while True:
            children = [
                item
                for item in self._records.values()
                if item.get("revision_of_id") == current["id"]
                or item.get("reversal_of_id") == current["id"]
            ]
            if not children:
                break
            if len(children) != 1:
                raise FinancialRepositoryConflict("financial transaction chain has multiple successors")
            current = children[0]
            result.append(current)
        return result

    def list_chains(self) -> list[list[dict[str, Any]]]:
        with self._lock:
            roots = [
                item["id"]
                for item in self._records.values()
                if item.get("revision_of_id") is None and item.get("reversal_of_id") is None
            ]
            chains = [self._chain_locked(root) for root in roots]
            chains.sort(key=lambda chain: (chain[0]["occurred_at"], chain[0]["id"]), reverse=True)
            return _clone(chains)


class PostgresFinancialTransactionRepository:
    """PostgreSQL canonical transaction repository.

    ``connection_factory`` is injectable for integration tests.  Production
    connections use explicit transactions; no DDL or authority activation is
    performed here.
    """

    _RECORD_COLUMNS = (
        "id",
        "scope",
        "project_id",
        "transaction_type",
        "flow_class",
        "amount",
        "admin_fee",
        "currency",
        "category",
        "description",
        "occurred_at",
        "source",
        "source_reference",
        "evidence",
        "actor",
        "revision_of_id",
        "reversal_of_id",
        "version",
        "status",
        "created_at",
    )
    _RECORD_SELECT_SQL = """
        SELECT ft.id, ft.scope, ft.project_id, ft.transaction_type, ft.flow_class,
               ft.amount, ft.admin_fee, ft.currency, ft.category, ft.description, ft.occurred_at,
               ft.source, ft.source_reference, ft.evidence, ft.actor,
               ft.revision_of_id, ft.reversal_of_id, ft.version, ft.status,
               ft.created_at,
               COALESCE(
                   (
                       SELECT jsonb_agg(
                           jsonb_build_object(
                               'id', fp.id,
                               'wallet_id', fp.wallet_id,
                               'business_unit_id', fp.business_unit_id,
                               'account_class', fp.account_class,
                               'signed_amount', fp.signed_amount,
                               'currency', fp.currency
                           ) ORDER BY fp.id
                       )
                       FROM financial_postings fp
                       WHERE fp.transaction_id = ft.id
                   ),
                   '[]'::jsonb
               ) AS postings
        FROM financial_transactions ft
        WHERE ft.id = %s
    """
    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("canonical finance repository requires a database DSN")
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg

        return psycopg.connect(self._dsn)

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def append(
        self,
        record: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        legacy_request_hash: str | None = None,
        operation: str | None = None,
        command_target_id: str | None = None,
        target_id: str | None = None,
        expected_version: int | None = None,
        outbox_payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                # Keep the advisory lock and lookup as separate statements. A
                # single-statement CTE uses the statement snapshot taken before a
                # contended advisory lock is released and can miss the winner's
                # committed row, violating concurrent idempotency.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_idempotency_lock_id(idempotency_key_hash),),
                )
                cursor.execute(
                    "SELECT id, request_hash FROM financial_transactions "
                    "WHERE idempotency_key_hash = %s FOR UPDATE",
                    (idempotency_key_hash,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    result = self._read_record(cursor, str(existing[0]))
                    existing_hash = str(existing[1])
                    if existing_hash != request_hash and not (
                        legacy_request_hash is not None and existing_hash == legacy_request_hash
                        and _legacy_replay_matches(
                            result, operation=operation, command_target_id=command_target_id,
                            read_record=lambda identifier: self._read_record(cursor, identifier),
                        )
                    ):
                        raise FinancialRepositoryConflict(
                            "idempotency key was already used with a different request"
                        )
                    connection.commit()
                    return result, True

                if target_id is not None:
                    cursor.execute(
                        "SELECT version, status FROM financial_transactions WHERE id = %s FOR UPDATE",
                        (target_id,),
                    )
                    target = cursor.fetchone()
                    if target is None:
                        raise FinancialRepositoryNotFound("financial transaction not found")
                    cursor.execute(
                        "SELECT 1 FROM financial_transactions "
                        "WHERE revision_of_id = %s OR reversal_of_id = %s LIMIT 1",
                        (target_id, target_id),
                    )
                    if cursor.fetchone() is not None or str(target[1]) == "reversal":
                        raise FinancialRepositoryConflict(
                            "financial transaction version changed concurrently"
                        )
                    if expected_version is None or int(target[0]) != expected_version:
                        raise FinancialRepositoryConflict(
                            "financial transaction version changed concurrently"
                        )

                # Queue the immutable transaction, balanced postings, export
                # outbox, and authoritative readback before one commit sync.
                # This keeps the same atomic transaction while avoiding one
                # client/server round-trip per small statement.
                with connection.pipeline():
                    cursor.execute(
                        """
                        INSERT INTO financial_transactions (
                            id, idempotency_key_hash, request_hash, scope, project_id,
                            transaction_type, flow_class, amount, admin_fee, currency, category,
                            description, occurred_at, source, source_reference, evidence,
                            actor, revision_of_id, reversal_of_id, version, status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s
                        )
                        """,
                        (
                            record["id"],
                            idempotency_key_hash,
                            request_hash,
                            record["scope"],
                            record.get("project_id"),
                            record["transaction_type"],
                            record["flow_class"],
                            record["amount"],
                            record.get("admin_fee", 0),
                            record["currency"],
                            record.get("category"),
                            record["description"],
                            record["occurred_at"],
                            record["source"],
                            record.get("source_reference"),
                            self._json(record.get("evidence") or {}),
                            self._json(record["actor"]),
                            record.get("revision_of_id"),
                            record.get("reversal_of_id"),
                            record["version"],
                            record["status"],
                        ),
                    )
                    self._insert_postings(cursor, record["id"], record["postings"])
                    cursor.execute(
                        """
                        INSERT INTO financial_export_outbox (
                            id, aggregate_type, aggregate_id, aggregate_version,
                            export_key, payload, payload_sha256, destination
                        ) VALUES (%s, 'transaction', %s, %s, %s, %s::jsonb, %s, 'google_sheets')
                        """,
                        (
                            outbox_payload["id"],
                            record["id"],
                            record["version"],
                            outbox_payload["export_key"],
                            self._json(outbox_payload["payload"]),
                            outbox_payload["payload_sha256"],
                        ),
                    )
                    readback = connection.cursor()
                    readback.execute(self._RECORD_SELECT_SQL, (str(record["id"]),))
                    connection.commit()
                    result = self._decode_record_row(readback.fetchone())
            return result, False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _insert_postings(cursor: Any, transaction_id: str, postings: Sequence[Mapping[str, Any]]) -> None:
        for posting in postings:
            cursor.execute(
                """
                INSERT INTO financial_postings (
                    id, transaction_id, wallet_id, business_unit_id,
                    account_class, signed_amount, currency
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    posting["id"],
                    transaction_id,
                    posting.get("wallet_id"),
                    posting.get("business_unit_id"),
                    posting["account_class"],
                    posting["signed_amount"],
                    posting["currency"],
                ),
            )

    @classmethod
    def _decode_record_row(cls, row: Sequence[Any] | None) -> dict[str, Any]:
        if row is None or len(row) != len(cls._RECORD_COLUMNS) + 1:
            raise FinancialRepositoryNotFound("financial transaction not found")
        record: dict[str, Any] = dict(zip(cls._RECORD_COLUMNS, row[:-1]))
        raw_postings = row[-1] or []
        if isinstance(raw_postings, str):
            raw_postings = json.loads(raw_postings)
        record["postings"] = [dict(item) for item in raw_postings]
        authority_posting = next(
            (
                posting
                for posting in record["postings"]
                if posting.get("wallet_id") is not None
                and posting.get("business_unit_id") is not None
            ),
            None,
        )
        if authority_posting is not None:
            record["wallet_id"] = authority_posting["wallet_id"]
            record["business_unit_id"] = authority_posting["business_unit_id"]
        return record

    def _read_record(self, cursor: Any, transaction_id: str) -> dict[str, Any]:
        cursor.execute(self._RECORD_SELECT_SQL, (transaction_id,))
        return self._decode_record_row(cursor.fetchone())

    def get(self, transaction_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                return self._read_record(cursor, transaction_id)
        finally:
            connection.close()

    def chain(self, transaction_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH RECURSIVE ancestors AS (
                        SELECT id, revision_of_id, reversal_of_id
                        FROM financial_transactions WHERE id = %s
                        UNION ALL
                        SELECT parent.id, parent.revision_of_id, parent.reversal_of_id
                        FROM financial_transactions parent
                        JOIN ancestors child ON parent.id = COALESCE(child.revision_of_id, child.reversal_of_id)
                    )
                    SELECT id FROM ancestors
                    WHERE revision_of_id IS NULL AND reversal_of_id IS NULL
                    """,
                    (transaction_id,),
                )
                root = cursor.fetchone()
                if root is None:
                    raise FinancialRepositoryNotFound("financial transaction not found")
                chain: list[dict[str, Any]] = []
                current_id = str(root[0])
                while current_id:
                    chain.append(self._read_record(cursor, current_id))
                    cursor.execute(
                        "SELECT id FROM financial_transactions "
                        "WHERE revision_of_id = %s OR reversal_of_id = %s ORDER BY created_at, id",
                        (current_id, current_id),
                    )
                    children = cursor.fetchall()
                    if len(children) > 1:
                        raise FinancialRepositoryConflict(
                            "financial transaction chain has multiple successors"
                        )
                    current_id = str(children[0][0]) if children else ""
                return chain
        finally:
            connection.close()

    def list_chains(self) -> list[list[dict[str, Any]]]:
        """Read every immutable transaction chain in two bounded queries.

        The previous implementation selected roots, then opened a new connection
        and issued multiple record/posting queries for every chain. Reversed
        readiness history therefore made the dashboard snapshot slower as the
        ledger grew. Batch the immutable rows and postings, then reconstruct the
        same linear chains in memory while preserving fail-closed invariants.
        """

        connection = self._connect()
        try:
            connection.autocommit = True
            with connection.pipeline():
                records_cursor = connection.cursor()
                records_cursor.execute(
                    """
                    SELECT id, scope, project_id, transaction_type, flow_class, amount, admin_fee,
                           currency, category, description, occurred_at, source,
                           source_reference, evidence, actor, revision_of_id,
                           reversal_of_id, version, status, created_at
                    FROM financial_transactions
                    ORDER BY occurred_at DESC, id DESC
                    """
                )
                postings_cursor = connection.cursor()
                postings_cursor.execute(
                    """
                    SELECT id, transaction_id, wallet_id, business_unit_id,
                           account_class, signed_amount, currency
                    FROM financial_postings
                    ORDER BY transaction_id, id
                    """
                )

            records: list[dict[str, Any]] = [
                dict(zip(self._RECORD_COLUMNS, row))
                for row in records_cursor.fetchall()
            ]
            posting_rows = postings_cursor.fetchall()
        finally:
            connection.close()

        records_by_id = {str(record["id"]): record for record in records}
        if len(records_by_id) != len(records):
            raise FinancialRepositoryConflict("financial transaction ids are not unique")

        postings_by_transaction: dict[str, list[dict[str, Any]]] = {}
        posting_columns = (
            "id",
            "wallet_id",
            "business_unit_id",
            "account_class",
            "signed_amount",
            "currency",
        )
        for row in posting_rows:
            transaction_id = str(row[1])
            postings_by_transaction.setdefault(transaction_id, []).append(
                dict(zip(posting_columns, (row[0], *row[2:])))
            )

        children_by_parent: dict[str, list[str]] = {}
        roots: list[dict[str, Any]] = []
        for record_id, record in records_by_id.items():
            record["postings"] = postings_by_transaction.get(record_id, [])
            if record["postings"]:
                authority_posting = next(
                    (
                        posting
                        for posting in record["postings"]
                        if posting.get("wallet_id") is not None
                        and posting.get("business_unit_id") is not None
                    ),
                    None,
                )
                if authority_posting is not None:
                    record["wallet_id"] = authority_posting["wallet_id"]
                    record["business_unit_id"] = authority_posting["business_unit_id"]

            parent = record.get("revision_of_id") or record.get("reversal_of_id")
            if parent is None:
                roots.append(record)
                continue
            parent_id = str(parent)
            if parent_id not in records_by_id:
                raise FinancialRepositoryConflict("financial transaction chain has an orphan successor")
            children_by_parent.setdefault(parent_id, []).append(record_id)

        if any(len(children) != 1 for children in children_by_parent.values()):
            raise FinancialRepositoryConflict("financial transaction chain has multiple successors")

        roots.sort(key=lambda record: (record["occurred_at"], str(record["id"])), reverse=True)
        chains: list[list[dict[str, Any]]] = []
        visited: set[str] = set()
        for root in roots:
            chain: list[dict[str, Any]] = []
            current_id = str(root["id"])
            while current_id:
                if current_id in visited:
                    raise FinancialRepositoryConflict("financial transaction chain contains a cycle")
                visited.add(current_id)
                chain.append(records_by_id[current_id])
                children = children_by_parent.get(current_id, [])
                current_id = children[0] if children else ""
            chains.append(chain)

        if len(visited) != len(records_by_id):
            raise FinancialRepositoryConflict("financial transaction chain is disconnected")
        return chains
