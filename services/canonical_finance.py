"""Deterministic immutable canonical transaction domain service."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, NoReturn, Protocol

from services.financial_transaction_repository import (
    FinancialRepositoryConflict,
    FinancialRepositoryNotFound,
)


MAX_SAFE_INTEGER = 9_007_199_254_740_991
CREATE_FIELDS = frozenset(
    {
        "idempotency_key",
        "scope",
        "project_id",
        "wallet_id",
        "business_unit_id",
        "transaction_type",
        "amount",
        "currency",
        "category",
        "description",
        "occurred_at",
        "source",
        "source_reference",
        "evidence",
    }
)
CREATE_REQUIRED = CREATE_FIELDS - {"source_reference", "evidence"}
CORRECTION_FIELDS = frozenset(
    {"idempotency_key", "expected_version", "amount", "description", "category", "reason"}
)
REVERSAL_FIELDS = frozenset({"idempotency_key", "expected_version", "reason"})
SCOPES = frozenset({"project", "office", "group"})
TRANSACTION_TYPES = frozenset({"inflow", "outflow"})
SOURCES = frozenset({"dashboard", "whatsapp", "telegram", "migration", "system"})
ACTOR_ROLES = frozenset({"boss", "admin", "system"})


class FinanceValidationError(ValueError):
    """The request is not a safe canonical finance command."""


class FinanceConflict(RuntimeError):
    """The command conflicts with immutable or concurrent state."""


class FinanceNotFound(LookupError):
    """The canonical transaction does not exist."""


class FinancialRepository(Protocol):
    def append(
        self,
        record: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        target_id: str | None = None,
        expected_version: int | None = None,
        outbox_payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]: ...

    def get(self, transaction_id: str) -> dict[str, Any]: ...

    def chain(self, transaction_id: str) -> list[dict[str, Any]]: ...

    def list_chains(self) -> list[list[dict[str, Any]]]: ...


def _fail(field: str, reason: str) -> NoReturn:
    raise FinanceValidationError(f"{field}: {reason}")


def _uuid(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        _fail(field, "must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        _fail(field, "must be a UUID string")
    if str(parsed) != value.casefold():
        _fail(field, "must use canonical UUID format")
    return str(parsed)


def _text(value: Any, field: str, *, maximum: int = 500, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if value != value.strip() or not 1 <= len(value) <= maximum:
        _fail(field, f"must be trimmed and contain 1..{maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(field, "must not contain control characters")
    return value


def _idempotency(value: Any) -> str:
    result = _text(value, "idempotency_key", maximum=128)
    assert result is not None
    if len(result) < 16 or any(character.isspace() for character in result):
        _fail("idempotency_key", "must be 16..128 printable characters without whitespace")
    return result


def _amount(value: Any, field: str = "amount") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an exact integer")
    if not 1 <= value <= MAX_SAFE_INTEGER:
        _fail(field, f"must be between 1 and {MAX_SAFE_INTEGER}")
    return value


def _version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("expected_version", "must be a positive integer")
    return value


def _instant(value: Any, field: str) -> str:
    if not isinstance(value, str):
        _fail(field, "must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(field, "must be an ISO-8601 timestamp with timezone")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(field, "must include a timezone")
    canonical = parsed.astimezone(timezone.utc).isoformat()
    return canonical


def _actor(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("actor", "must be an authenticated actor object")
    allowed = {"id", "role", "channel", "email"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail("actor", f"unknown field(s): {', '.join(unknown)}")
    actor_id = _text(value.get("id"), "actor.id", maximum=200)
    role = _text(value.get("role"), "actor.role", maximum=20)
    channel = _text(value.get("channel"), "actor.channel", maximum=30)
    if role not in ACTOR_ROLES:
        _fail("actor.role", "must be boss, admin, or system")
    result = {"id": str(actor_id), "role": str(role), "channel": str(channel)}
    if value.get("email") is not None:
        result["email"] = str(_text(value["email"], "actor.email", maximum=254))
    return result


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _postings(
    *,
    transaction_id: str,
    wallet_id: str,
    business_unit_id: str,
    amount: int,
    transaction_type: str,
    status: str,
) -> list[dict[str, Any]]:
    cash_sign = 1 if transaction_type == "inflow" else -1
    counter_class = "revenue" if transaction_type == "inflow" else "expense"
    if status == "reversal":
        cash_sign *= -1
    return [
        {
            "id": str(uuid.uuid5(uuid.UUID(transaction_id), "cash")),
            "wallet_id": wallet_id,
            "business_unit_id": business_unit_id,
            "account_class": "cash",
            "signed_amount": cash_sign * amount,
            "currency": "IDR",
        },
        {
            "id": str(uuid.uuid5(uuid.UUID(transaction_id), "counter")),
            "wallet_id": None,
            "business_unit_id": None,
            "account_class": counter_class,
            "signed_amount": -cash_sign * amount,
            "currency": "IDR",
        },
    ]


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class CanonicalFinanceService:
    """Create, correct, reverse, and read immutable effective transactions."""

    def __init__(self, repository: FinancialRepository) -> None:
        self._repository = repository

    @staticmethod
    def _translate_repository_error(exc: Exception) -> NoReturn:
        if isinstance(exc, FinancialRepositoryNotFound):
            raise FinanceNotFound(str(exc)) from exc
        if isinstance(exc, FinancialRepositoryConflict):
            raise FinanceConflict(str(exc)) from exc
        raise exc

    def create_transaction(
        self, payload: Mapping[str, Any], *, actor: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            _fail("request", "must be an object")
        unknown = sorted(set(payload) - CREATE_FIELDS)
        missing = sorted(CREATE_REQUIRED - set(payload))
        if unknown:
            raise FinanceValidationError(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            raise FinanceValidationError(f"missing field(s): {', '.join(missing)}")

        command = self._validate_create(payload)
        authenticated_actor = _actor(actor)
        transaction_id = str(uuid.uuid4())
        record = {
            "id": transaction_id,
            **{key: value for key, value in command.items() if key != "idempotency_key"},
            "actor": authenticated_actor,
            "flow_class": "external",
            "revision_of_id": None,
            "reversal_of_id": None,
            "version": 1,
            "status": "posted",
        }
        record["postings"] = _postings(
            transaction_id=transaction_id,
            wallet_id=record["wallet_id"],
            business_unit_id=record["business_unit_id"],
            amount=record["amount"],
            transaction_type=record["transaction_type"],
            status="posted",
        )
        return self._append(record, command["idempotency_key"], payload)

    def _validate_create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope")
        if scope not in SCOPES:
            _fail("scope", "must be project, office, or group")
        project_id = _uuid(payload.get("project_id"), "project_id", optional=True)
        if scope == "project" and project_id is None:
            _fail("project_id", "is required for project scope")
        if scope != "project" and project_id is not None:
            _fail("project_id", "must be omitted outside project scope")
        transaction_type = payload.get("transaction_type")
        if transaction_type not in TRANSACTION_TYPES:
            _fail("transaction_type", "must be inflow or outflow")
        if payload.get("currency") != "IDR":
            _fail("currency", "must be IDR")
        category = _text(payload.get("category"), "category", maximum=100, optional=True)
        evidence = payload.get("evidence", {})
        if not isinstance(evidence, Mapping):
            _fail("evidence", "must be an object")
        source = payload.get("source")
        if source not in SOURCES:
            _fail("source", "is unsupported")
        return {
            "idempotency_key": _idempotency(payload.get("idempotency_key")),
            "scope": scope,
            "project_id": project_id,
            "wallet_id": _uuid(payload.get("wallet_id"), "wallet_id"),
            "business_unit_id": _uuid(payload.get("business_unit_id"), "business_unit_id"),
            "transaction_type": transaction_type,
            "amount": _amount(payload.get("amount")),
            "currency": "IDR",
            "category": category,
            "description": _text(payload.get("description"), "description"),
            "occurred_at": _instant(payload.get("occurred_at"), "occurred_at"),
            "source": source,
            "source_reference": _text(
                payload.get("source_reference"), "source_reference", maximum=300, optional=True
            ),
            "evidence": dict(evidence),
        }

    def correct_transaction(
        self,
        transaction_id: str,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        _uuid(transaction_id, "transaction_id")
        if not isinstance(payload, Mapping):
            _fail("request", "must be an object")
        unknown = sorted(set(payload) - CORRECTION_FIELDS)
        required = {"idempotency_key", "expected_version", "reason"}
        missing = sorted(required - set(payload))
        if unknown:
            raise FinanceValidationError(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            raise FinanceValidationError(f"missing field(s): {', '.join(missing)}")
        if not any(field in payload for field in ("amount", "description", "category")):
            _fail("request", "correction must change amount, description, or category")

        target = self._get_record(transaction_id)
        expected_version = _version(payload.get("expected_version"))
        corrected = {key: value for key, value in target.items() if key not in {"postings", "created_at"}}
        corrected.update(
            {
                "id": str(uuid.uuid4()),
                "actor": _actor(actor),
                "revision_of_id": transaction_id,
                "reversal_of_id": None,
                "version": expected_version + 1,
                "status": "correction",
                "evidence": {
                    **dict(target.get("evidence") or {}),
                    "correction_reason": _text(payload.get("reason"), "reason"),
                },
            }
        )
        if "amount" in payload:
            corrected["amount"] = _amount(payload["amount"])
        if "description" in payload:
            corrected["description"] = _text(payload["description"], "description")
        if "category" in payload:
            corrected["category"] = _text(payload["category"], "category", maximum=100)
        corrected["postings"] = _postings(
            transaction_id=corrected["id"],
            wallet_id=corrected["wallet_id"],
            business_unit_id=corrected["business_unit_id"],
            amount=corrected["amount"],
            transaction_type=corrected["transaction_type"],
            status="posted",
        )
        return self._append(
            corrected,
            _idempotency(payload.get("idempotency_key")),
            payload,
            target_id=transaction_id,
            expected_version=expected_version,
        )

    def reverse_transaction(
        self,
        transaction_id: str,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        _uuid(transaction_id, "transaction_id")
        if not isinstance(payload, Mapping):
            _fail("request", "must be an object")
        unknown = sorted(set(payload) - REVERSAL_FIELDS)
        missing = sorted(REVERSAL_FIELDS - set(payload))
        if unknown:
            raise FinanceValidationError(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            raise FinanceValidationError(f"missing field(s): {', '.join(missing)}")
        target = self._get_record(transaction_id)
        expected_version = _version(payload.get("expected_version"))
        reversal = {key: value for key, value in target.items() if key not in {"postings", "created_at"}}
        reversal.update(
            {
                "id": str(uuid.uuid4()),
                "actor": _actor(actor),
                "revision_of_id": None,
                "reversal_of_id": transaction_id,
                "version": expected_version + 1,
                "status": "reversal",
                "evidence": {
                    **dict(target.get("evidence") or {}),
                    "reversal_reason": _text(payload.get("reason"), "reason"),
                },
            }
        )
        reversal["postings"] = _postings(
            transaction_id=reversal["id"],
            wallet_id=reversal["wallet_id"],
            business_unit_id=reversal["business_unit_id"],
            amount=reversal["amount"],
            transaction_type=reversal["transaction_type"],
            status="reversal",
        )
        return self._append(
            reversal,
            _idempotency(payload.get("idempotency_key")),
            payload,
            target_id=transaction_id,
            expected_version=expected_version,
        )

    def _get_record(self, transaction_id: str) -> dict[str, Any]:
        try:
            return self._repository.get(transaction_id)
        except (FinancialRepositoryConflict, FinancialRepositoryNotFound) as exc:
            self._translate_repository_error(exc)

    def _append(
        self,
        record: Mapping[str, Any],
        idempotency_key: str,
        request_payload: Mapping[str, Any],
        *,
        target_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        key_hash = _sha256(idempotency_key)
        request_hash = _sha256(_canonical_json(request_payload))
        serializable_record = _serialize(record)
        export_payload = {"schema_version": "canonical.finance.transaction.v1", **serializable_record}
        outbox_payload = {
            "id": str(uuid.uuid4()),
            "export_key": f"transaction:{record['id']}:v{record['version']}",
            "payload": export_payload,
            "payload_sha256": _sha256(_canonical_json(export_payload)),
        }
        try:
            stored, duplicate = self._repository.append(
                serializable_record,
                idempotency_key_hash=key_hash,
                request_hash=request_hash,
                target_id=target_id,
                expected_version=expected_version,
                outbox_payload=outbox_payload,
            )
        except (FinancialRepositoryConflict, FinancialRepositoryNotFound) as exc:
            self._translate_repository_error(exc)
        return {"transaction": _serialize(stored), "duplicate": duplicate}

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        _uuid(transaction_id, "transaction_id")
        try:
            chain = self._repository.chain(transaction_id)
        except (FinancialRepositoryConflict, FinancialRepositoryNotFound) as exc:
            self._translate_repository_error(exc)
        latest = chain[-1]
        reversed_state = latest["status"] == "reversal"
        return {
            "root_id": chain[0]["id"],
            "version": latest["version"],
            "reversed": reversed_state,
            "effective": None if reversed_state else _serialize(latest),
            "history": _serialize(chain),
        }

    def list_effective_transactions(self) -> list[dict[str, Any]]:
        results = []
        for chain in self._repository.list_chains():
            latest = chain[-1]
            if latest["status"] != "reversal":
                results.append(_serialize(latest))
        return results
