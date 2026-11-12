"""Fail-closed reconstruction of canonical finance state from derived export rows."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

EXPORT_SCHEMA_VERSION = "canonical.finance.export.v1"
TRANSACTION_SCHEMA = "canonical.finance.transaction.v1"
DEBT_SCHEMA = "canonical.finance.debt.v1"


class ExportReconstructionError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        result = str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExportReconstructionError(f"{field} must be UUID") from exc
    if result != str(value).casefold():
        raise ExportReconstructionError(f"{field} must use canonical UUID format")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExportReconstructionError(f"{field} must be a positive integer")
    return value


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExportReconstructionError(f"{field} must be an object")
    return dict(value)


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExportReconstructionError(f"{field} must be an array")
    return value


def _validate_instant(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ExportReconstructionError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExportReconstructionError(f"{field} must be a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExportReconstructionError(f"{field} must include timezone")


def _validate_postings(
    postings_value: Any,
    *,
    transaction_id: str | None,
    expected_count: int,
    expected_accounts: set[str],
) -> list[dict[str, Any]]:
    postings = [_mapping(item, "posting") for item in _list(postings_value, "postings")]
    if len(postings) != expected_count:
        raise ExportReconstructionError("posting bundle is incomplete")
    ids: set[str] = set()
    accounts: set[str] = set()
    signed_total = 0
    currencies: set[str] = set()
    for posting in postings:
        posting_id = _uuid(posting.get("id"), "posting.id")
        if posting_id in ids:
            raise ExportReconstructionError("duplicate posting id")
        ids.add(posting_id)
        if transaction_id is not None and posting.get("transaction_id") != transaction_id:
            raise ExportReconstructionError("posting transaction_id mismatch")
        signed_amount = posting.get("signed_amount")
        if isinstance(signed_amount, bool) or not isinstance(signed_amount, int):
            raise ExportReconstructionError("posting signed_amount must be integer")
        signed_total += signed_amount
        account_class = posting.get("account_class")
        if not isinstance(account_class, str):
            raise ExportReconstructionError("posting account_class missing")
        accounts.add(account_class)
        currency = posting.get("currency")
        if not isinstance(currency, str) or not currency:
            raise ExportReconstructionError("posting currency missing")
        currencies.add(currency)
    if signed_total != 0:
        raise ExportReconstructionError("posting bundle is unbalanced")
    if accounts != expected_accounts or len(currencies) != 1:
        raise ExportReconstructionError("posting bundle classes or currency mismatch")
    return postings


def _validate_transaction(payload: dict[str, Any], aggregate_id: str, version: int) -> dict[str, Any]:
    if payload.get("schema_version") != TRANSACTION_SCHEMA:
        raise ExportReconstructionError("transaction schema mismatch")
    transaction_id = _uuid(payload.get("id"), "transaction.id")
    if transaction_id != aggregate_id:
        raise ExportReconstructionError("transaction aggregate id mismatch")
    if _positive_int(payload.get("version"), "transaction.version") != version:
        raise ExportReconstructionError("transaction aggregate version mismatch")
    status = payload.get("status")
    if status not in {"posted", "correction", "reversal"}:
        raise ExportReconstructionError("transaction status invalid")
    _validate_instant(payload.get("occurred_at"), "transaction.occurred_at")
    _validate_postings(
        payload.get("postings"),
        transaction_id=transaction_id,
        expected_count=2,
        expected_accounts={"cash", "income" if payload.get("transaction_type") == "inflow" else "expense"},
    )
    return payload


def _validate_debt(payload: dict[str, Any], aggregate_id: str, version: int) -> dict[str, Any]:
    if payload.get("schema_version") != DEBT_SCHEMA:
        raise ExportReconstructionError("debt schema mismatch")
    debt = _mapping(payload.get("debt"), "debt")
    debt_id = _uuid(debt.get("id"), "debt.id")
    if debt_id != aggregate_id:
        raise ExportReconstructionError("debt aggregate id mismatch")
    if _positive_int(payload.get("version"), "debt.version") != version:
        raise ExportReconstructionError("debt aggregate version mismatch")
    events = [_mapping(item, "debt event") for item in _list(payload.get("events"), "debt.events")]
    if len(events) != version:
        raise ExportReconstructionError("debt event history is incomplete")
    event_ids: set[str] = set()
    for event in events:
        event_id = _uuid(event.get("id"), "debt.event.id")
        if event_id in event_ids or event.get("debt_id") != debt_id:
            raise ExportReconstructionError("debt event identity mismatch")
        event_ids.add(event_id)
        _validate_instant(event.get("occurred_at"), "debt.event.occurred_at")
        _validate_postings(
            event.get("postings"),
            transaction_id=None,
            expected_count=4,
            expected_accounts={"cash", "receivable", "payable"},
        )
    return {"debt": debt, "events": events, "version": version}


def reconstruct_financial_export(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    documents = [dict(row) for row in rows]
    if not documents:
        raise ExportReconstructionError("export is empty")

    expected_ordinals = list(range(1, len(documents) + 1))
    observed_ordinals: list[int] = []
    export_keys: set[str] = set()
    transactions: dict[str, dict[str, Any]] = {}
    debt_snapshots: dict[str, dict[int, dict[str, Any]]] = {}

    for expected_ordinal, document in zip(expected_ordinals, documents, strict=True):
        row_hash = document.pop("row_sha256", None)
        if not isinstance(row_hash, str) or _sha256(_canonical_json(document)) != row_hash:
            raise ExportReconstructionError("row hash mismatch")
        ordinal = _positive_int(document.get("export_ordinal"), "export_ordinal")
        observed_ordinals.append(ordinal)
        if ordinal != expected_ordinal:
            raise ExportReconstructionError("export ordinal gap or reorder")
        if document.get("export_schema_version") != EXPORT_SCHEMA_VERSION:
            raise ExportReconstructionError("export schema mismatch")
        _validate_instant(document.get("outbox_created_at_utc"), "outbox_created_at_utc")

        aggregate_type = document.get("aggregate_type")
        if aggregate_type not in {"transaction", "debt"}:
            raise ExportReconstructionError("aggregate type unsupported")
        aggregate_id = _uuid(document.get("aggregate_id"), "aggregate_id")
        version = _positive_int(document.get("aggregate_version"), "aggregate_version")
        export_key = f"{aggregate_type}:{aggregate_id}:v{version}"
        if document.get("export_key") != export_key or export_key in export_keys:
            raise ExportReconstructionError("export key mismatch or duplicate")
        export_keys.add(export_key)

        payload_json = document.get("payload_json")
        if not isinstance(payload_json, str):
            raise ExportReconstructionError("payload_json must be text")
        try:
            payload = _mapping(json.loads(payload_json), "payload")
        except json.JSONDecodeError as exc:
            raise ExportReconstructionError("payload_json invalid") from exc
        if payload_json != _canonical_json(payload):
            raise ExportReconstructionError("payload_json is not canonical")
        if document.get("payload_sha256") != _sha256(payload_json):
            raise ExportReconstructionError("payload hash mismatch")

        if aggregate_type == "transaction":
            if aggregate_id in transactions:
                raise ExportReconstructionError("duplicate transaction aggregate")
            transactions[aggregate_id] = _validate_transaction(payload, aggregate_id, version)
        else:
            debt_snapshots.setdefault(aggregate_id, {})[version] = _validate_debt(
                payload, aggregate_id, version
            )

    referenced: set[str] = set()
    for transaction_id, transaction in transactions.items():
        version = transaction["version"]
        parents = [
            value
            for value in (transaction.get("revision_of_id"), transaction.get("reversal_of_id"))
            if value is not None
        ]
        if version == 1:
            if parents:
                raise ExportReconstructionError("root transaction cannot reference parent")
            continue
        if len(parents) != 1:
            raise ExportReconstructionError("transaction revision parent missing")
        parent_id = _uuid(parents[0], "transaction.parent_id")
        parent = transactions.get(parent_id)
        if parent is None or parent["version"] + 1 != version:
            raise ExportReconstructionError("transaction version chain incomplete")
        if parent_id in referenced:
            raise ExportReconstructionError("transaction history branches")
        referenced.add(parent_id)

    debt_versions: dict[str, int] = {}
    for debt_id, snapshots in debt_snapshots.items():
        versions = sorted(snapshots)
        if versions != list(range(1, max(versions) + 1)):
            raise ExportReconstructionError("debt version chain incomplete")
        for version in versions:
            if len(snapshots[version]["events"]) != version:
                raise ExportReconstructionError("debt cumulative history mismatch")
        debt_versions[debt_id] = max(versions)

    effective_ids = sorted(
        transaction_id
        for transaction_id, transaction in transactions.items()
        if transaction_id not in referenced and transaction["status"] != "reversal"
    )
    return {
        "transaction_count": len(transactions),
        "debt_count": len(debt_snapshots),
        "effective_transaction_ids": effective_ids,
        "debt_versions": debt_versions,
        "export_keys": sorted(export_keys),
        "ordinal_sha256": _sha256("\n".join(str(value) for value in observed_ordinals)),
    }
