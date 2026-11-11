"""Deterministic offline manifest and reconciliation for the finance cutover."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from services.legacy_financial_rows import build_source_key, normalize_row


MANIFEST_VERSION = "canonical.finance.migration.v1"
_NAMESPACE = uuid.UUID("d874f915-5e75-4b16-83c1-380235c0ced1")
_MAPPING_TYPES = {
    "opening_balance": "opening_balance",
    "adjustment": "adjustment",
    "debt_principal": "debt_principal",
    "debt_repayment": "debt_repayment",
    "project_status": "project_status",
    "document": "document",
    "allocation": "allocation",
    "receipt": "receipt",
    "evidence": "evidence",
    "quotation": "quotation",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _source_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    tabs = snapshot.get("tabs")
    if not isinstance(tabs, Mapping):
        raise ValueError("snapshot tabs must be an object")

    rows: list[dict[str, Any]] = []
    for tab, tab_rows in sorted(tabs.items(), key=lambda item: str(item[0])):
        if not isinstance(tab_rows, Sequence) or isinstance(tab_rows, (str, bytes)):
            raise ValueError(f"snapshot tab {tab!r} must contain rows")
        for raw in tab_rows:
            if not isinstance(raw, Mapping):
                raise ValueError(f"snapshot tab {tab!r} contains a non-object row")
            row = dict(raw)
            row["sheet_name"] = str(tab)
            try:
                source_row = int(row.get("sheet_row"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"snapshot tab {tab!r} has invalid sheet_row") from exc
            if source_row <= 0:
                raise ValueError(f"snapshot tab {tab!r} has invalid sheet_row")
            row["sheet_row"] = source_row
            rows.append(row)
    rows.sort(key=lambda row: (row["sheet_name"], row["sheet_row"]))
    coordinates = [(row["sheet_name"], row["sheet_row"]) for row in rows]
    if len(coordinates) != len(set(coordinates)):
        raise ValueError("snapshot contains duplicate tab/row coordinates")
    return rows


def _signed_source_amount(raw: Mapping[str, Any]) -> int | None:
    normalized = normalize_row(dict(raw))
    amount = normalized["amount"]
    if not normalized["is_valid"] or not isinstance(amount, int):
        return None
    return amount if str(normalized["transaction_type"]).casefold() == "pemasukan" else -amount


def _manifest_row(
    *,
    spreadsheet_id: str,
    snapshot_sha256: str,
    captured_at: str,
    raw: Mapping[str, Any],
    mappings: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_row(dict(raw))
    tab = str(raw["sheet_name"])
    coordinate = f"{tab}:{raw['sheet_row']}"
    source_key = build_source_key(dict(raw))
    row_sha256 = _sha256(raw)
    identity = f"{spreadsheet_id}:{coordinate}:{source_key}"
    row_id = str(uuid.uuid5(_NAMESPACE, f"manifest:{identity}"))
    transaction_id = str(uuid.uuid5(_NAMESPACE, f"transaction:{identity}"))

    reason: str | None = None
    wallet_mapping = mappings.get("wallets", {}).get(tab)
    if not normalized["is_valid"]:
        reason = "invalid date or amount"
    elif not isinstance(wallet_mapping, Mapping):
        reason = f"wallet mapping missing for source tab {tab}"

    raw_project_id = raw.get("project_id")
    has_project_reference = bool(raw_project_id or raw.get("nama_projek"))
    project_id: str | None = None
    if reason is None and has_project_reference:
        if not raw_project_id:
            reason = "explicit project_id is required; project name is not an identity"
        else:
            try:
                project_id = str(uuid.UUID(str(raw_project_id)))
            except (TypeError, ValueError, AttributeError):
                reason = "project_id is not a valid UUID"
            else:
                mapped_project = mappings.get("projects", {}).get(project_id)
                if mapped_project != project_id:
                    reason = f"project_id {project_id} has no explicit mapping"

    source_block = str(normalized["source_block"])
    mapping_type = _MAPPING_TYPES.get(source_block, "transaction")
    disposition = "quarantined" if reason else "mapped"
    wallet_id = str(wallet_mapping["wallet_id"]) if reason is None else None
    business_unit_id = (
        str(wallet_mapping["business_unit_id"]) if reason is None else None
    )
    amount = normalized["amount"]
    transaction_type = str(normalized["transaction_type"])
    signed_amount = amount if transaction_type.casefold() == "pemasukan" else -amount if amount else None

    return {
        "id": row_id,
        "source_spreadsheet_id": spreadsheet_id,
        "source_snapshot_sha256": snapshot_sha256,
        "source_tab": tab,
        "source_row": raw["sheet_row"],
        "legacy_source_key": source_key,
        "source_row_sha256": row_sha256,
        "canonical_transaction_id": transaction_id if disposition == "mapped" else None,
        "canonical_debt_id": None,
        "canonical_project_id": project_id if disposition == "mapped" else None,
        "wallet_id": wallet_id,
        "business_unit_id": business_unit_id,
        "mapping_type": mapping_type if disposition == "mapped" else "quarantine",
        "reference_map": {
            "amount": amount,
            "signed_amount": signed_amount,
            "transaction_date": (
                normalized["transaction_date"].isoformat()
                if normalized["transaction_date"]
                else None
            ),
            "transaction_type": transaction_type,
            "source_block": source_block,
        },
        "disposition": disposition,
        "disposition_actor": (
            {"kind": "migration", "version": MANIFEST_VERSION}
            if disposition == "quarantined"
            else None
        ),
        "disposition_reason": reason,
        "disposition_at": captured_at if disposition == "quarantined" else None,
    }


def build_manifest(
    snapshot: Mapping[str, Any],
    mappings: Mapping[str, Any],
    *,
    start_after: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic manifest without external reads or writes."""

    spreadsheet_id = str(snapshot.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        raise ValueError("snapshot spreadsheet_id is required")
    rows = _source_rows(snapshot)
    snapshot_sha256 = _sha256(snapshot)
    captured_at = str(snapshot.get("captured_at") or "1970-01-01T00:00:00Z")
    all_manifest_rows = [
        _manifest_row(
            spreadsheet_id=spreadsheet_id,
            snapshot_sha256=snapshot_sha256,
            captured_at=captured_at,
            raw=row,
            mappings=mappings,
        )
        for row in rows
    ]

    if start_after is not None:
        indices = [index for index, row in enumerate(all_manifest_rows) if row["id"] == start_after]
        if len(indices) != 1:
            raise ValueError("checkpoint does not belong to this source snapshot")
        all_manifest_rows = all_manifest_rows[indices[0] + 1 :]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        all_manifest_rows = all_manifest_rows[:limit]

    return {
        "version": MANIFEST_VERSION,
        "source_spreadsheet_id": spreadsheet_id,
        "source_snapshot_sha256": snapshot_sha256,
        "rows": all_manifest_rows,
        "checkpoint": all_manifest_rows[-1]["id"] if all_manifest_rows else start_after,
    }


def reconcile_manifest(
    snapshot: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare a source snapshot to its row-level manifest; never mutate state."""

    source_rows = _source_rows(snapshot)
    snapshot_sha256 = _sha256(snapshot)
    if manifest.get("source_snapshot_sha256") != snapshot_sha256:
        raise ValueError("manifest source snapshot hash mismatch")

    source_by_coordinate = {
        (row["sheet_name"], row["sheet_row"]): row for row in source_rows
    }
    manifest_rows = manifest.get("rows")
    if not isinstance(manifest_rows, Sequence):
        raise ValueError("manifest rows must be an array")
    seen: set[tuple[str, int]] = set()
    dangling = 0
    mapped = 0
    quarantined = 0

    for row in manifest_rows:
        coordinate = (str(row["source_tab"]), int(row["source_row"]))
        if coordinate in seen:
            raise ValueError("manifest contains duplicate source coordinates")
        seen.add(coordinate)
        source = source_by_coordinate.get(coordinate)
        if source is None:
            raise ValueError("manifest references a source row outside the snapshot")
        if row.get("source_row_sha256") != _sha256(source):
            raise ValueError("manifest source row hash mismatch")

        disposition = row.get("disposition")
        signed_amount = row.get("reference_map", {}).get("signed_amount")
        source_signed_amount = _signed_source_amount(source)
        if disposition == "mapped":
            mapped += 1
            if not row.get("canonical_transaction_id"):
                dangling += 1
            if signed_amount != source_signed_amount:
                raise ValueError("manifest signed amount does not match source row")
        elif disposition == "quarantined":
            quarantined += 1
            if not row.get("disposition_actor") or not row.get("disposition_reason"):
                dangling += 1
        else:
            dangling += 1

    missing_rows = [
        source
        for coordinate, source in source_by_coordinate.items()
        if coordinate not in seen
    ]
    missing_amounts = [
        signed
        for source in missing_rows
        if (signed := _signed_source_amount(source)) is not None
    ]
    unexplained_rows = len(missing_rows)
    unexplained_amount = sum(abs(amount) for amount in missing_amounts)
    ending_balance_drift = sum(missing_amounts)
    cutover_ready = (
        unexplained_rows == 0
        and unexplained_amount == 0
        and dangling == 0
    )
    return {
        "source_snapshot_sha256": snapshot_sha256,
        "source_rows": len(source_rows),
        "manifest_rows": len(manifest_rows),
        "mapped_rows": mapped,
        "quarantined_rows": quarantined,
        "unexplained_rows": unexplained_rows,
        "unexplained_amount": unexplained_amount,
        "ending_balance_drift": ending_balance_drift,
        "dangling_references": dangling,
        "cutover_ready": cutover_ready,
    }
