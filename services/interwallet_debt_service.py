"""Immutable, balanced inter-wallet debt lifecycle service.

Debt cash movements are internal transfers.  Effective debt state is replayed
from immutable events; revenue and expense accounts are never posted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, NoReturn, Protocol


MAX_SAFE_INTEGER = 9_007_199_254_740_991
ACTOR_ROLES = frozenset({"boss", "admin", "system"})
CREATE_FIELDS = frozenset(
    {
        "idempotency_key",
        "lender_wallet_id",
        "borrower_wallet_id",
        "lender_business_unit_id",
        "borrower_business_unit_id",
        "project_id",
        "principal",
        "currency",
        "occurred_at",
        "due_at",
        "description",
    }
)
CREATE_REQUIRED = CREATE_FIELDS - {"project_id", "due_at"}
REPAY_FIELDS = frozenset(
    {"idempotency_key", "expected_version", "amount", "occurred_at", "description"}
)
CORRECT_FIELDS = frozenset(
    {"idempotency_key", "expected_version", "amount", "reason", "occurred_at"}
)
REVERSE_FIELDS = frozenset(
    {"idempotency_key", "expected_version", "reason", "occurred_at"}
)


class DebtValidationError(ValueError):
    """A debt command is malformed or unsafe."""


class DebtConflict(RuntimeError):
    """A debt command conflicts with current immutable state."""


class DebtNotFound(LookupError):
    """A debt or debt event does not exist."""


class DebtRepository(Protocol):
    @property
    def outbox_count(self) -> int: ...

    def create(
        self,
        debt: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> tuple[str, bool]: ...

    def append_event(
        self,
        debt_id: str,
        event: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> tuple[str, bool]: ...

    def get(self, debt_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...


def _fail(field: str, reason: str) -> NoReturn:
    raise DebtValidationError(f"{field}: {reason}")


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _text(value: Any, field: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if value != value.strip() or not 1 <= len(value) <= maximum:
        _fail(field, f"must be trimmed and contain 1..{maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(field, "must not contain control characters")
    return value


def _idempotency(value: Any) -> str:
    result = _text(value, "idempotency_key", maximum=128)
    if len(result) < 16 or any(character.isspace() for character in result):
        _fail("idempotency_key", "must be 16..128 printable characters without whitespace")
    return result


def _amount(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an exact integer")
    if not 1 <= value <= MAX_SAFE_INTEGER:
        _fail(field, f"must be between 1 and {MAX_SAFE_INTEGER}")
    return value


def _version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("expected_version", "must be a positive integer")
    return value


def _instant(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        _fail(field, "must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(field, "must be an ISO-8601 timestamp with timezone")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(field, "must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _actor(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("actor", "must be an authenticated actor object")
    unknown = sorted(set(value) - {"id", "role", "channel", "email"})
    if unknown:
        _fail("actor", f"unknown field(s): {', '.join(unknown)}")
    actor_id = _text(value.get("id"), "actor.id", maximum=200)
    role = _text(value.get("role"), "actor.role", maximum=20)
    channel = _text(value.get("channel"), "actor.channel", maximum=30)
    if role not in ACTOR_ROLES:
        _fail("actor.role", "must be boss, admin, or system")
    result = {"id": actor_id, "role": role, "channel": channel}
    if value.get("email") is not None:
        result["email"] = _text(value["email"], "actor.email", maximum=254)
    return result


def _postings(
    *,
    event_id: str,
    lender_wallet_id: str,
    borrower_wallet_id: str,
    lender_business_unit_id: str,
    borrower_business_unit_id: str,
    amount: int,
    movement: str,
) -> list[dict[str, Any]]:
    """Build balanced cash plus receivable/payable entries.

    ``disbursement`` increases borrower cash and debt exposure. ``repayment``
    does the inverse. A reversal passes the inverse movement of its target.
    """

    lender_cash = -amount if movement == "disbursement" else amount
    borrower_cash = -lender_cash
    receivable = amount if movement == "disbursement" else -amount
    payable = -receivable
    namespace = uuid.UUID(event_id)
    return [
        {
            "id": str(uuid.uuid5(namespace, "lender-cash")),
            "wallet_id": lender_wallet_id,
            "business_unit_id": lender_business_unit_id,
            "account_class": "cash",
            "signed_amount": lender_cash,
            "currency": "IDR",
        },
        {
            "id": str(uuid.uuid5(namespace, "borrower-cash")),
            "wallet_id": borrower_wallet_id,
            "business_unit_id": borrower_business_unit_id,
            "account_class": "cash",
            "signed_amount": borrower_cash,
            "currency": "IDR",
        },
        {
            "id": str(uuid.uuid5(namespace, "receivable")),
            "wallet_id": None,
            "business_unit_id": lender_business_unit_id,
            "account_class": "receivable",
            "signed_amount": receivable,
            "currency": "IDR",
        },
        {
            "id": str(uuid.uuid5(namespace, "payable")),
            "wallet_id": None,
            "business_unit_id": borrower_business_unit_id,
            "account_class": "payable",
            "signed_amount": payable,
            "currency": "IDR",
        },
    ]


class InMemoryInterwalletDebtRepository:
    """Thread-safe immutable repository for domain and concurrency tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._debts: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._keys: dict[str, tuple[str, str, str]] = {}
        self._outbox: dict[tuple[str, str, int], dict[str, Any]] = {}

    @property
    def outbox_count(self) -> int:
        with self._lock:
            return len(self._outbox)

    def _idempotent(self, key_hash: str, request_hash: str) -> tuple[str, bool] | None:
        existing = self._keys.get(key_hash)
        if existing is None:
            return None
        old_hash, debt_id, event_id = existing
        if old_hash != request_hash:
            raise DebtConflict("idempotency key was already used with a different request")
        return event_id, True

    def create(
        self,
        debt: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        idempotency_key_hash: str,
        request_hash: str,
        outbox: Mapping[str, Any],
    ) -> tuple[str, bool]:
        with self._lock:
            existing = self._keys.get(idempotency_key_hash)
            if existing is not None:
                old_hash, existing_debt_id, _event_id = existing
                if old_hash != request_hash:
                    raise DebtConflict(
                        "idempotency key was already used with a different request"
                    )
                return existing_debt_id, True
            stored_debt = _clone(dict(debt))
            stored_event = _clone(dict(event))
            self._debts[stored_debt["id"]] = stored_debt
            self._events[stored_debt["id"]] = [stored_event]
            self._keys[idempotency_key_hash] = (
                request_hash,
                stored_debt["id"],
                stored_event["id"],
            )
            self._outbox[("debt", stored_debt["id"], 1)] = _clone(dict(outbox))
            return stored_debt["id"], False

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
        with self._lock:
            replay = self._idempotent(idempotency_key_hash, request_hash)
            if replay is not None:
                return replay
            if debt_id not in self._debts:
                raise DebtNotFound("interwallet debt not found")
            events = self._events[debt_id]
            if len(events) != expected_version:
                raise DebtConflict("interwallet debt version changed concurrently")
            stored_event = _clone(dict(event))
            events.append(stored_event)
            self._keys[idempotency_key_hash] = (
                request_hash,
                debt_id,
                stored_event["id"],
            )
            self._outbox[("debt", debt_id, len(events))] = _clone(dict(outbox))
            return stored_event["id"], False

    def get(self, debt_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self._lock:
            if debt_id not in self._debts:
                raise DebtNotFound("interwallet debt not found")
            return _clone(self._debts[debt_id]), _clone(self._events[debt_id])


class InterwalletDebtService:
    """Create and replay auditable debt aggregates from immutable events."""

    def __init__(self, repository: DebtRepository) -> None:
        self._repository = repository

    @staticmethod
    def _check_fields(payload: Mapping[str, Any], allowed: frozenset[str], required: set[str]) -> None:
        if not isinstance(payload, Mapping):
            _fail("request", "must be an object")
        unknown = sorted(set(payload) - allowed)
        missing = sorted(required - set(payload))
        if unknown:
            raise DebtValidationError(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            raise DebtValidationError(f"missing field(s): {', '.join(missing)}")

    def create_debt(
        self, payload: Mapping[str, Any], *, actor: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._check_fields(payload, CREATE_FIELDS, set(CREATE_REQUIRED))
        idempotency_key = _idempotency(payload.get("idempotency_key"))
        lender_wallet_id = str(_uuid(payload.get("lender_wallet_id"), "lender_wallet_id"))
        borrower_wallet_id = str(_uuid(payload.get("borrower_wallet_id"), "borrower_wallet_id"))
        if lender_wallet_id == borrower_wallet_id:
            _fail("wallet", "lender and borrower wallets must differ")
        lender_unit_id = str(
            _uuid(payload.get("lender_business_unit_id"), "lender_business_unit_id")
        )
        borrower_unit_id = str(
            _uuid(payload.get("borrower_business_unit_id"), "borrower_business_unit_id")
        )
        principal = _amount(payload.get("principal"), "principal")
        if payload.get("currency") != "IDR":
            _fail("currency", "must be IDR")
        occurred_at = str(_instant(payload.get("occurred_at"), "occurred_at"))
        due_at = _instant(payload.get("due_at"), "due_at", optional=True)
        if due_at is not None and due_at < occurred_at:
            _fail("due_at", "must not be earlier than occurred_at")
        authenticated_actor = _actor(actor)
        debt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        debt = {
            "id": debt_id,
            "lender_wallet_id": lender_wallet_id,
            "borrower_wallet_id": borrower_wallet_id,
            "lender_business_unit_id": lender_unit_id,
            "borrower_business_unit_id": borrower_unit_id,
            "project_id": _uuid(payload.get("project_id"), "project_id", optional=True),
            "principal": principal,
            "currency": "IDR",
            "occurred_at": occurred_at,
            "due_at": due_at,
            "description": _text(payload.get("description"), "description"),
            "actor": authenticated_actor,
        }
        event = self._event(
            debt,
            event_id=event_id,
            event_type="disbursement",
            amount=principal,
            occurred_at=occurred_at,
            actor=authenticated_actor,
            movement="disbursement",
        )
        request_hash = _sha256(_canonical_json(payload))
        outbox = self._outbox(debt_id, 1, debt, [event])
        stored_debt_id, duplicate = self._repository.create(
            debt,
            event,
            idempotency_key_hash=_sha256(idempotency_key),
            request_hash=request_hash,
            outbox=outbox,
        )
        return {"debt": self.get_debt(stored_debt_id), "duplicate": duplicate}

    @staticmethod
    def _event(
        debt: Mapping[str, Any],
        *,
        event_id: str,
        event_type: str,
        amount: int,
        occurred_at: str,
        actor: Mapping[str, Any],
        movement: str,
        description: str | None = None,
        reason: str | None = None,
        corrects_event_id: str | None = None,
        reverses_event_id: str | None = None,
        corrected_event_type: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": event_id,
            "debt_id": debt["id"],
            "event_type": event_type,
            "amount": amount,
            "occurred_at": occurred_at,
            "actor": dict(actor),
            "description": description,
            "reason": reason,
            "corrects_event_id": corrects_event_id,
            "reverses_event_id": reverses_event_id,
            "corrected_event_type": corrected_event_type,
            "postings": _postings(
                event_id=event_id,
                lender_wallet_id=debt["lender_wallet_id"],
                borrower_wallet_id=debt["borrower_wallet_id"],
                lender_business_unit_id=debt["lender_business_unit_id"],
                borrower_business_unit_id=debt["borrower_business_unit_id"],
                amount=amount,
                movement=movement,
            ),
        }

    def repay_debt(
        self,
        debt_id: str,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        _uuid(debt_id, "debt_id")
        self._check_fields(payload, REPAY_FIELDS, set(REPAY_FIELDS))
        debt, events = self._repository.get(debt_id)
        expected_version = _version(payload.get("expected_version"))
        state = self._project(debt, events)
        amount = _amount(payload.get("amount"), "amount")
        if state["status"] != "open" or amount > state["outstanding"]:
            raise DebtConflict("repayment amount exceeds open outstanding debt")
        event = self._event(
            debt,
            event_id=str(uuid.uuid4()),
            event_type="repayment",
            amount=amount,
            occurred_at=str(_instant(payload.get("occurred_at"), "occurred_at")),
            actor=_actor(actor),
            movement="repayment",
            description=_text(payload.get("description"), "description"),
        )
        duplicate = self._append(debt, events, event, payload, expected_version)
        return {"debt": self.get_debt(debt_id), "duplicate": duplicate}

    def correct_event(
        self,
        debt_id: str,
        event_id: str,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        _uuid(debt_id, "debt_id")
        _uuid(event_id, "event_id")
        self._check_fields(payload, CORRECT_FIELDS, set(CORRECT_FIELDS))
        debt, events = self._repository.get(debt_id)
        target = self._mutable_target(events, event_id)
        if target["event_type"] not in {"disbursement", "repayment"}:
            raise DebtConflict("only disbursement or repayment events can be corrected")
        corrected_type = target["event_type"]
        amount = _amount(payload.get("amount"), "amount")
        if corrected_type == "disbursement":
            effective_repaid = self._project(debt, events)["repaid"]
            if amount < effective_repaid:
                raise DebtConflict("corrected principal cannot be below effective repayment")
        event = self._event(
            debt,
            event_id=str(uuid.uuid4()),
            event_type="correction",
            amount=amount,
            occurred_at=str(_instant(payload.get("occurred_at"), "occurred_at")),
            actor=_actor(actor),
            movement=corrected_type,
            reason=_text(payload.get("reason"), "reason"),
            corrects_event_id=event_id,
            corrected_event_type=corrected_type,
        )
        expected_version = _version(payload.get("expected_version"))
        duplicate = self._append(debt, events, event, payload, expected_version)
        return {"debt": self.get_debt(debt_id), "duplicate": duplicate}

    def reverse_event(
        self,
        debt_id: str,
        event_id: str,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        _uuid(debt_id, "debt_id")
        _uuid(event_id, "event_id")
        self._check_fields(payload, REVERSE_FIELDS, set(REVERSE_FIELDS))
        debt, events = self._repository.get(debt_id)
        target = self._mutable_target(events, event_id)
        target_type = target.get("corrected_event_type") or target["event_type"]
        if target_type not in {"disbursement", "repayment"}:
            raise DebtConflict("event cannot be reversed")
        state = self._project(debt, events)
        if target_type == "disbursement" and state["repaid"] > 0:
            raise DebtConflict("disbursement cannot be reversed after repayment exposure")
        movement = "repayment" if target_type == "disbursement" else "disbursement"
        event = self._event(
            debt,
            event_id=str(uuid.uuid4()),
            event_type="reversal",
            amount=target["amount"],
            occurred_at=str(_instant(payload.get("occurred_at"), "occurred_at")),
            actor=_actor(actor),
            movement=movement,
            reason=_text(payload.get("reason"), "reason"),
            reverses_event_id=event_id,
            corrected_event_type=target_type,
        )
        expected_version = _version(payload.get("expected_version"))
        duplicate = self._append(debt, events, event, payload, expected_version)
        return {"debt": self.get_debt(debt_id), "duplicate": duplicate}

    @staticmethod
    def _mutable_target(events: list[dict[str, Any]], event_id: str) -> dict[str, Any]:
        target = next((item for item in events if item["id"] == event_id), None)
        if target is None:
            raise DebtNotFound("interwallet debt event not found")
        if any(item.get("corrects_event_id") == event_id for item in events):
            raise DebtConflict("interwallet debt event is already corrected")
        if any(item.get("reverses_event_id") == event_id for item in events):
            raise DebtConflict("interwallet debt event is already reversed")
        return target

    def _append(
        self,
        debt: Mapping[str, Any],
        events: list[dict[str, Any]],
        event: Mapping[str, Any],
        payload: Mapping[str, Any],
        expected_version: int,
    ) -> bool:
        idempotency_key = _idempotency(payload.get("idempotency_key"))
        outbox = self._outbox(str(debt["id"]), expected_version + 1, debt, [*events, dict(event)])
        _, duplicate = self._repository.append_event(
            str(debt["id"]),
            event,
            expected_version=expected_version,
            idempotency_key_hash=_sha256(idempotency_key),
            request_hash=_sha256(_canonical_json(payload)),
            outbox=outbox,
        )
        return duplicate

    @staticmethod
    def _project(debt: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        effective: dict[str, dict[str, Any]] = {}
        reversed_ids: set[str] = set()
        for event in events:
            if event["event_type"] in {"disbursement", "repayment"}:
                effective[event["id"]] = event
            elif event["event_type"] == "correction":
                target_id = str(event["corrects_event_id"])
                effective.pop(target_id, None)
                effective[event["id"]] = event
            elif event["event_type"] == "reversal":
                target_id = str(event["reverses_event_id"])
                effective.pop(target_id, None)
                reversed_ids.add(target_id)

        disbursements = [
            item
            for item in effective.values()
            if (item.get("corrected_event_type") or item["event_type"]) == "disbursement"
        ]
        repayments = [
            item
            for item in effective.values()
            if (item.get("corrected_event_type") or item["event_type"]) == "repayment"
        ]
        principal = sum(int(item["amount"]) for item in disbursements)
        repaid = sum(int(item["amount"]) for item in repayments)
        outstanding = principal - repaid
        if outstanding < 0:
            raise DebtConflict("effective repayment exceeds principal")
        if not disbursements:
            status = "reversed"
        elif outstanding == 0:
            status = "paid"
        else:
            status = "open"
        return {
            "principal": principal,
            "repaid": repaid,
            "outstanding": outstanding,
            "status": status,
            "reversed_event_ids": sorted(reversed_ids),
        }

    def get_debt(self, debt_id: str) -> dict[str, Any]:
        _uuid(debt_id, "debt_id")
        debt, events = self._repository.get(debt_id)
        projection = self._project(debt, events)
        return {
            **debt,
            "original_principal": debt["principal"],
            **projection,
            "version": len(events),
            "events": events,
        }

    @staticmethod
    def _outbox(
        debt_id: str,
        version: int,
        debt: Mapping[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "schema_version": "canonical.finance.debt.v1",
            "debt": dict(debt),
            "events": events,
            "version": version,
        }
        return {
            "id": str(uuid.uuid4()),
            "export_key": f"debt:{debt_id}:v{version}",
            "payload": payload,
            "payload_sha256": _sha256(_canonical_json(payload)),
        }
