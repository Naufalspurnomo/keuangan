"""Atomic PostgreSQL persistence for immutable inter-wallet debt aggregates."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from services.interwallet_debt_service import DebtConflict, DebtNotFound


class PostgresInterwalletDebtRepository:
    """Persist debt, internal ledger movement, event, postings, and outbox atomically."""

    _DEBT_COLUMNS = (
        "id", "lender_wallet_id", "borrower_wallet_id", "lender_business_unit_id",
        "borrower_business_unit_id", "project_id", "principal", "currency", "occurred_at",
        "due_at", "description", "actor", "created_at",
    )
    _EVENT_COLUMNS = (
        "id", "debt_id", "event_type", "amount", "corrects_event_id", "reverses_event_id",
        "actor", "occurred_at", "description", "reason", "corrected_event_type", "created_at",
    )

    def __init__(self, dsn: str, *, connection_factory: Callable[..., Any] | None = None) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("canonical debt repository requires a database DSN")
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg
        return psycopg.connect(self._dsn)

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def outbox_count(self) -> int:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM financial_export_outbox WHERE aggregate_type = 'debt'")
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        finally:
            connection.close()

    def _idempotent(self, cursor: Any, key_hash: str, request_hash: str) -> tuple[str, str] | None:
        cursor.execute(
            "SELECT debt_id, id, request_hash FROM interwallet_debt_events "
            "WHERE idempotency_key_hash = %s FOR UPDATE",
            (key_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        if str(row[2]) != request_hash:
            raise DebtConflict("idempotency key was already used with a different request")
        return str(row[0]), str(row[1])

    def create(
        self,
        debt: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> tuple[str, bool]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                existing = self._idempotent(cursor, idempotency_key_hash, request_hash)
                if existing is not None:
                    connection.commit()
                    return existing[0], True
                cursor.execute(
                    """
                    INSERT INTO interwallet_debts (
                        id, lender_wallet_id, borrower_wallet_id, lender_business_unit_id,
                        borrower_business_unit_id, project_id, principal, currency,
                        occurred_at, due_at, description, actor
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        debt["id"], debt["lender_wallet_id"], debt["borrower_wallet_id"],
                        debt["lender_business_unit_id"], debt["borrower_business_unit_id"],
                        debt.get("project_id"), debt["principal"], debt["currency"],
                        debt["occurred_at"], debt.get("due_at"), debt["description"],
                        self._json(debt["actor"]),
                    ),
                )
                self._insert_event_bundle(
                    cursor, debt, event, version=1,
                    idempotency_key_hash=idempotency_key_hash,
                    request_hash=request_hash,
                    outbox=outbox,
                )
            connection.commit()
            return str(debt["id"]), False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_event(
        self,
        debt_id: str,
        event: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> tuple[str, bool]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                existing = self._idempotent(cursor, idempotency_key_hash, request_hash)
                if existing is not None:
                    connection.commit()
                    return existing[1], True
                cursor.execute(
                    """
                    SELECT id, lender_wallet_id, borrower_wallet_id, lender_business_unit_id,
                           borrower_business_unit_id, project_id, principal, currency,
                           occurred_at, due_at, description, actor, created_at
                    FROM interwallet_debts WHERE id = %s FOR UPDATE
                    """,
                    (debt_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise DebtNotFound("interwallet debt not found")
                debt = dict(zip(self._DEBT_COLUMNS, row))
                cursor.execute("SELECT count(*) FROM interwallet_debt_events WHERE debt_id = %s", (debt_id,))
                version_row = cursor.fetchone()
                observed = int(version_row[0]) if version_row else 0
                if observed != expected_version:
                    raise DebtConflict("interwallet debt version changed concurrently")
                self._insert_event_bundle(
                    cursor, debt, event, version=expected_version + 1,
                    idempotency_key_hash=idempotency_key_hash,
                    request_hash=request_hash,
                    outbox=outbox,
                )
            connection.commit()
            return str(event["id"]), False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _insert_event_bundle(
        self,
        cursor: Any,
        debt: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        version: int,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> None:
        event_type = str(event["event_type"])
        status = "correction" if event_type == "correction" else "reversal" if event_type == "reversal" else "posted"
        description = event.get("description") or event.get("reason") or debt["description"]
        cursor.execute(
            """
            INSERT INTO financial_transactions (
                id, idempotency_key_hash, request_hash, scope, project_id,
                transaction_type, flow_class, amount, currency, category,
                description, occurred_at, source, source_reference, evidence,
                actor, revision_of_id, reversal_of_id, version, status
            ) VALUES (
                %s, %s, %s, 'internal', NULL, 'transfer', 'internal', %s, %s,
                'interwallet_debt', %s, %s, 'dashboard', %s, %s::jsonb,
                %s::jsonb, %s, %s, %s, %s
            )
            """,
            (
                event["id"], idempotency_key_hash, request_hash, event["amount"],
                debt["currency"], description, event["occurred_at"],
                f"debt:{debt['id']}:{event_type}", self._json({"debt_id": debt["id"], "event_type": event_type}),
                self._json(event["actor"]), event.get("corrects_event_id"),
                event.get("reverses_event_id"), version, status,
            ),
        )
        self._insert_postings(cursor, str(event["id"]), event["postings"])
        cursor.execute(
            """
            INSERT INTO interwallet_debt_events (
                id, debt_id, event_type, amount, transaction_id,
                corrects_event_id, reverses_event_id, idempotency_key_hash,
                request_hash, actor, occurred_at, description, reason, corrected_event_type
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                event["id"], debt["id"], event_type, event["amount"], event["id"],
                event.get("corrects_event_id"), event.get("reverses_event_id"),
                idempotency_key_hash, request_hash, self._json(event["actor"]),
                event["occurred_at"], event.get("description"), event.get("reason"),
                event.get("corrected_event_type"),
            ),
        )
        cursor.execute(
            """
            INSERT INTO financial_export_outbox (
                id, aggregate_type, aggregate_id, aggregate_version,
                export_key, payload, payload_sha256, destination
            ) VALUES (%s, 'debt', %s, %s, %s, %s::jsonb, %s, 'google_sheets')
            """,
            (
                outbox["id"], debt["id"], version, outbox["export_key"],
                self._json(outbox["payload"]), outbox["payload_sha256"],
            ),
        )

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
                    posting["id"], transaction_id, posting.get("wallet_id"),
                    posting.get("business_unit_id"), posting["account_class"],
                    posting["signed_amount"], posting["currency"],
                ),
            )

    def get(self, debt_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, lender_wallet_id, borrower_wallet_id, lender_business_unit_id,
                           borrower_business_unit_id, project_id, principal, currency,
                           occurred_at, due_at, description, actor, created_at
                    FROM interwallet_debts WHERE id = %s
                    """,
                    (debt_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise DebtNotFound("interwallet debt not found")
                debt = dict(zip(self._DEBT_COLUMNS, row))
                cursor.execute(
                    """
                    SELECT id, debt_id, event_type, amount, corrects_event_id,
                           reverses_event_id, actor, occurred_at, description, reason,
                           corrected_event_type, created_at
                    FROM interwallet_debt_events
                    WHERE debt_id = %s ORDER BY occurred_at, id
                    """,
                    (debt_id,),
                )
                events = [dict(zip(self._EVENT_COLUMNS, item)) for item in cursor.fetchall()]
                for event in events:
                    cursor.execute(
                        """
                        SELECT id, wallet_id, business_unit_id, account_class,
                               signed_amount, currency
                        FROM financial_postings WHERE transaction_id = %s ORDER BY id
                        """,
                        (event["id"],),
                    )
                    event["postings"] = [
                        dict(zip(("id", "wallet_id", "business_unit_id", "account_class", "signed_amount", "currency"), item))
                        for item in cursor.fetchall()
                    ]
                return debt, events
        finally:
            connection.close()
