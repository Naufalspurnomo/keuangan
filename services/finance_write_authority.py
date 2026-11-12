"""Single finance-write authority switch used during PostgreSQL cutover."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol


class CanonicalWriteUnavailable(RuntimeError):
    """Canonical authority was selected but could not commit the command."""


class AuthorityResolver(Protocol):
    def resolve_wallet(self, label: str) -> tuple[str, str] | None: ...

    def resolve_project(self, project_id: str | None, project_label: str | None) -> str | None: ...

    def quarantine(self, command: Mapping[str, Any], reason_code: str) -> str: ...


class FinanceService(Protocol):
    def create_transaction(
        self, payload: Mapping[str, Any], *, actor: Mapping[str, Any]
    ) -> dict[str, Any]: ...


class DebtService(Protocol):
    def create_debt(
        self, payload: Mapping[str, Any], *, actor: Mapping[str, Any]
    ) -> dict[str, Any]: ...


def canonical_finance_writes_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get("CANONICAL_FINANCE_WRITES_ENABLED", "").strip().casefold() in {"1", "true"}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PostgresAuthorityResolver:
    """Resolve only persisted canonical identities and durably quarantine gaps."""

    def __init__(self, dsn: str, *, connection_factory: Callable[..., Any] | None = None) -> None:
        self._dsn = dsn
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg

        return psycopg.connect(self._dsn)

    @staticmethod
    def _label(value: str) -> str:
        return value.strip().casefold()

    def resolve_wallet(self, label: str) -> tuple[str, str] | None:
        query = """
            SELECT w.id::text, wbu.business_unit_id::text
              FROM wallets w
              JOIN wallet_business_units wbu ON wbu.wallet_id = w.id
              JOIN business_units bu ON bu.id = wbu.business_unit_id
             WHERE w.active AND bu.active
               AND lower(trim(w.display_name)) = %s
             ORDER BY w.id, wbu.business_unit_id
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (self._label(label),))
            rows = cursor.fetchall()
        if len(rows) != 1:
            return None
        return str(rows[0][0]), str(rows[0][1])

    def resolve_project(self, project_id: str | None, project_label: str | None) -> str | None:
        canonical_id = None
        if project_id is not None:
            try:
                parsed = uuid.UUID(project_id)
            except (ValueError, TypeError, AttributeError):
                return None
            if str(parsed) != project_id.casefold():
                return None
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT id::text FROM projects WHERE id = %s", (str(parsed),))
                row = cursor.fetchone()
            if row is None:
                return None
            canonical_id = str(row[0])

        mapped_id = None
        if project_label is not None:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id::text
                      FROM canonical_project_identity_mappings
                     WHERE normalized_label = %s AND owner_approved AND active
                    """,
                    (self._label(project_label),),
                )
                rows = cursor.fetchall()
            if len(rows) != 1:
                return None
            mapped_id = str(rows[0][0])

        if canonical_id is not None and mapped_id is not None and canonical_id != mapped_id:
            return None
        return canonical_id or mapped_id

    def quarantine(self, command: Mapping[str, Any], reason_code: str) -> str:
        command_json = _canonical_json(command)
        command_hash = _sha256(command_json)
        quarantine_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"hollawall:finance-quarantine:{command_hash}")
        )
        idempotency_key = command.get("idempotency_key")
        idempotency_hash = _sha256(idempotency_key) if isinstance(idempotency_key, str) else None
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO financial_command_quarantine (
                    id, command_sha256, idempotency_key_hash, reason_code, command
                ) VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (command_sha256) DO NOTHING
                """,
                (quarantine_id, command_hash, idempotency_hash, reason_code, command_json),
            )
            cursor.execute(
                "SELECT id::text FROM financial_command_quarantine WHERE command_sha256 = %s",
                (command_hash,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CanonicalWriteUnavailable("canonical finance quarantine readback failed")
        return str(row[0])


class FinanceWriteAuthorityGateway:
    """Select exactly one authority; active canonical failures never fall back."""

    def __init__(
        self,
        *,
        enabled: bool,
        resolver: AuthorityResolver,
        finance_service: FinanceService,
        debt_service: DebtService,
    ) -> None:
        self._enabled = enabled
        self._resolver = resolver
        self._finance = finance_service
        self._debt = debt_service

    def dispatch(
        self,
        command: Mapping[str, Any],
        *,
        legacy_write: Callable[[], Any],
    ) -> dict[str, Any]:
        if not self._enabled:
            return {"authority": "google_sheets", "result": legacy_write()}
        if not isinstance(command, Mapping):
            raise CanonicalWriteUnavailable("canonical finance command must be an object")
        kind = command.get("kind")
        preflight = self._preflight(command)
        if preflight is not None:
            return preflight
        if kind == "transaction":
            return self._dispatch_transaction(command)
        if kind == "debt":
            return self._dispatch_debt(command)
        return self._quarantine(command, "unsupported_command")

    def _preflight(self, command: Mapping[str, Any]) -> dict[str, Any] | None:
        key = command.get("idempotency_key")
        if not isinstance(key, str) or not 16 <= len(key) <= 128 or any(
            character.isspace() for character in key
        ):
            return self._quarantine(command, "missing_idempotency")
        if not isinstance(command.get("actor"), Mapping):
            return self._quarantine(command, "missing_actor")
        instant = command.get("occurred_at")
        if not isinstance(instant, str):
            return self._quarantine(command, "missing_timestamp")
        try:
            parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
        except ValueError:
            return self._quarantine(command, "missing_timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return self._quarantine(command, "missing_timestamp")
        return None

    def _quarantine(self, command: Mapping[str, Any], reason: str) -> dict[str, Any]:
        try:
            quarantine_id = self._resolver.quarantine(command, reason)
        except Exception as exc:
            raise CanonicalWriteUnavailable("canonical finance quarantine failed") from exc
        return {
            "authority": "postgresql",
            "status": "quarantined",
            "reason_code": reason,
            "quarantine_id": quarantine_id,
        }

    def _wallet(
        self, command: Mapping[str, Any], field: str
    ) -> tuple[str, str] | dict[str, Any]:
        label = command.get(field)
        if not isinstance(label, str) or not label.strip():
            return self._quarantine(command, "unknown_wallet")
        resolved = self._resolver.resolve_wallet(label)
        if resolved is None:
            return self._quarantine(command, "unknown_wallet")
        return resolved

    def _project(self, command: Mapping[str, Any]) -> str | None | dict[str, Any]:
        project_id = command.get("project_id")
        project_label = command.get("project_label")
        if project_id is not None and not isinstance(project_id, str):
            return self._quarantine(command, "unmapped_project")
        if project_label is not None and not isinstance(project_label, str):
            return self._quarantine(command, "unmapped_project")
        return self._resolver.resolve_project(project_id, project_label)

    @staticmethod
    def _actor(command: Mapping[str, Any]) -> Mapping[str, Any]:
        actor = command.get("actor")
        if not isinstance(actor, Mapping):
            raise CanonicalWriteUnavailable("canonical finance actor is missing")
        return actor

    def _dispatch_transaction(self, command: Mapping[str, Any]) -> dict[str, Any]:
        wallet = self._wallet(command, "wallet_label")
        if isinstance(wallet, dict):
            return wallet
        wallet_id, business_unit_id = wallet
        scope = command.get("scope")
        project_id: str | None = None
        if scope == "project":
            resolved_project = self._project(command)
            if isinstance(resolved_project, dict):
                return resolved_project
            if resolved_project is None:
                return self._quarantine(command, "unmapped_project")
            project_id = resolved_project

        payload = {
            "idempotency_key": command.get("idempotency_key"),
            "scope": scope,
            "project_id": project_id,
            "wallet_id": wallet_id,
            "business_unit_id": business_unit_id,
            "transaction_type": command.get("transaction_type"),
            "amount": command.get("amount"),
            "currency": command.get("currency"),
            "category": command.get("category"),
            "description": command.get("description"),
            "occurred_at": command.get("occurred_at"),
            "source": command.get("source"),
            "source_reference": command.get("source_reference"),
            "evidence": command.get("evidence", {}),
        }
        try:
            result = self._finance.create_transaction(payload, actor=self._actor(command))
        except Exception as exc:
            raise CanonicalWriteUnavailable("canonical finance write failed") from exc
        return {"authority": "postgresql", "status": "committed", "result": result}

    def _dispatch_debt(self, command: Mapping[str, Any]) -> dict[str, Any]:
        lender = self._wallet(command, "lender_wallet_label")
        if isinstance(lender, dict):
            return lender
        borrower = self._wallet(command, "borrower_wallet_label")
        if isinstance(borrower, dict):
            return borrower
        if lender[0] == borrower[0]:
            return self._quarantine(command, "same_wallet_debt")

        project_id = None
        if command.get("project_id") is not None or command.get("project_label") is not None:
            resolved_project = self._project(command)
            if isinstance(resolved_project, dict):
                return resolved_project
            if resolved_project is None:
                return self._quarantine(command, "unmapped_project")
            project_id = resolved_project

        payload = {
            "idempotency_key": command.get("idempotency_key"),
            "lender_wallet_id": lender[0],
            "borrower_wallet_id": borrower[0],
            "lender_business_unit_id": lender[1],
            "borrower_business_unit_id": borrower[1],
            "project_id": project_id,
            "principal": command.get("principal"),
            "currency": command.get("currency"),
            "occurred_at": command.get("occurred_at"),
            "due_at": command.get("due_at"),
            "description": command.get("description"),
        }
        try:
            result = self._debt.create_debt(payload, actor=self._actor(command))
        except Exception as exc:
            raise CanonicalWriteUnavailable("canonical debt write failed") from exc
        return {"authority": "postgresql", "status": "committed", "result": result}
