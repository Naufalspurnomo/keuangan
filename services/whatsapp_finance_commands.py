"""Canonical WhatsApp finance command construction and resumable batch dispatch."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo


JAKARTA = ZoneInfo("Asia/Jakarta")


class ActorNotAuthorized(RuntimeError):
    """The sender has no explicit finance role binding."""


class FinanceGateway(Protocol):
    def dispatch(
        self,
        command: Mapping[str, Any],
        *,
        legacy_write,
    ) -> dict[str, Any]: ...


def _sender_set(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def resolve_whatsapp_actor(
    sender_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    stable_id = str(sender_id or "").strip()
    boss = stable_id in _sender_set(source.get("FINANCE_BOSS_SENDER_IDS"))
    admin = stable_id in _sender_set(source.get("FINANCE_ADMIN_SENDER_IDS"))
    if not stable_id or boss == admin:
        raise ActorNotAuthorized("sender has no unambiguous finance role")
    return {
        "id": stable_id,
        "role": "boss" if boss else "admin",
        "channel": "whatsapp",
    }


def _canonical_key(event_id: str, suffix: str) -> str:
    raw = f"whatsapp:{event_id}:{suffix}"
    if 16 <= len(raw) <= 128 and not any(character.isspace() for character in raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"whatsapp:{digest}:{suffix[:32]}"[:128]


def _instant(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    if parsed.isoformat() != value:
        return None
    return datetime.combine(parsed, time.min, tzinfo=JAKARTA).isoformat()


def _canonical_only():
    raise AssertionError("canonical authority must never invoke a legacy Sheet write")


def _transaction_type(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    if normalized == "pemasukan":
        return "inflow"
    if normalized == "pengeluaran":
        return "outflow"
    return None


def dispatch_if_canonical_enabled(
    app: Any,
    *,
    sender_id: str,
    event_id: str,
    transactions: list[Mapping[str, Any]],
    wallet_label: str,
    project_id: str | None,
    project_label: str | None,
    source: str,
    debt_source_wallet_label: str | None = None,
    scope: str = "project",
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    if not bool(app.config.get("CANONICAL_FINANCE_WRITES_ENABLED", False)):
        return None
    gateway = app.extensions.get("finance_write_authority_gateway")
    if gateway is None:
        raise RuntimeError("canonical finance authority gateway is unavailable")
    actor = resolve_whatsapp_actor(sender_id, environ=environ)
    return dispatch_confirmed_finance_batch(
        gateway=gateway,
        event_id=event_id,
        transactions=transactions,
        wallet_label=wallet_label,
        project_id=project_id,
        project_label=project_label,
        actor=actor,
        source=source,
        debt_source_wallet_label=debt_source_wallet_label,
        scope=scope,
    )


def dispatch_confirmed_finance_batch(
    *,
    gateway: FinanceGateway,
    event_id: str,
    transactions: list[Mapping[str, Any]],
    wallet_label: str,
    project_id: str | None,
    project_label: str | None,
    actor: Mapping[str, Any],
    source: str,
    debt_source_wallet_label: str | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    stable_event_id = str(event_id or "").strip()
    if not stable_event_id:
        return {"status": "quarantined", "reason_code": "missing_idempotency"}
    if not transactions:
        return {"status": "quarantined", "reason_code": "empty_batch"}

    effective_scope = scope
    if scope == "auto":
        general_labels = {"", "saldo umum", "umum", "unknown"}
        label_kinds = {
            "general"
            if str(transaction.get("nama_projek") or "").strip().casefold() in general_labels
            else "project"
            for transaction in transactions
        }
        if len(label_kinds) != 1:
            return {"status": "quarantined", "reason_code": "ambiguous_scope"}
        effective_scope = "group" if label_kinds == {"general"} else "project"
    if effective_scope not in {"project", "office", "group"}:
        return {"status": "quarantined", "reason_code": "invalid_scope"}

    total = 0
    commands: list[dict[str, Any]] = []
    project_identities: set[tuple[str | None, str | None]] = set()
    for index, transaction in enumerate(transactions):
        occurred_at = _instant(transaction.get("tanggal"))
        if occurred_at is None:
            return {"status": "quarantined", "reason_code": "missing_transaction_date"}
        message_id = str(transaction.get("message_id") or "").strip()
        suffix = f"item:{message_id or index}"
        amount = transaction.get("jumlah")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return {"status": "quarantined", "reason_code": "invalid_amount"}
        transaction_type = _transaction_type(transaction.get("tipe"))
        if transaction_type is None:
            return {"status": "quarantined", "reason_code": "invalid_transaction_type"}
        row_project_id = transaction.get("project_id") or project_id
        row_project_label = (
            transaction.get("project_label")
            or transaction.get("nama_projek")
            or project_label
        )
        if effective_scope == "project":
            row_identity = (
                str(row_project_id).strip() if row_project_id else None,
                str(row_project_label).strip() if row_project_label else None,
            )
            project_identities.add(row_identity)
        command = {
            "kind": "transaction",
            "idempotency_key": _canonical_key(stable_event_id, suffix),
            "scope": effective_scope,
            "project_id": row_project_id if effective_scope == "project" else None,
            "project_label": row_project_label if effective_scope == "project" else None,
            "wallet_label": wallet_label,
            "transaction_type": transaction_type,
            "amount": amount,
            "currency": "IDR",
            "category": str(transaction.get("category") or "Lainnya").strip(),
            "description": str(transaction.get("keterangan") or "").strip(),
            "occurred_at": occurred_at,
            "source": str(source or "whatsapp").strip().casefold(),
            "source_reference": message_id or stable_event_id,
            "evidence": {
                "source_event_id": stable_event_id,
                "source_message_id": message_id or None,
                "occurred_at_precision": "date",
            },
            "actor": dict(actor),
        }
        commands.append(command)
        total += amount

    lender = str(debt_source_wallet_label or "").strip()
    if lender and lender != wallet_label and len(project_identities) > 1:
        return {"status": "quarantined", "reason_code": "ambiguous_debt_project"}

    for command in commands:
        result = gateway.dispatch(command, legacy_write=_canonical_only)
        if result.get("status") != "committed":
            return dict(result)

    debt_committed = False
    if lender and lender != wallet_label:
        debt_project_id, debt_project_label = (
            next(iter(project_identities)) if project_identities else (None, None)
        )
        debt_command = {
            "kind": "debt",
            "idempotency_key": _canonical_key(stable_event_id, "debt"),
            "lender_wallet_label": lender,
            "borrower_wallet_label": wallet_label,
            "project_id": debt_project_id,
            "project_label": debt_project_label,
            "principal": total,
            "currency": "IDR",
            "occurred_at": commands[0]["occurred_at"],
            "due_at": None,
            "description": commands[0]["description"],
            "actor": dict(actor),
        }
        result = gateway.dispatch(debt_command, legacy_write=_canonical_only)
        if result.get("status") != "committed":
            return dict(result)
        debt_committed = True

    return {
        "status": "committed",
        "transaction_count": len(transactions),
        "debt_committed": debt_committed,
    }
