"""Deterministic contracts for migrating legacy Sheets into canonical finance."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any, Iterable, Mapping


CUTOVER_TOLERANCE = 0
SOURCE_NAMESPACE = uuid.UUID("dcbe20e1-0562-55b7-8719-c31eef7ff288")
TRANSACTION_NAMESPACE = uuid.UUID("29e32aa2-00b2-5ce0-9239-c05e6ef30e87")


class MigrationContractError(ValueError):
    """A source row or explicit mapping violates the migration contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _snapshot_hash(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise MigrationContractError("source snapshot hash must be sha256")
    return normalized


def _source_row_number(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MigrationContractError("source identity requires a positive integer row")
    return value


def canonical_source_identity(
    source_spreadsheet_id: str,
    source_snapshot_sha256: str,
    source_tab: str,
    source_row: int,
    legacy_source_key: str,
) -> str:
    """Return a coordinate- and snapshot-bound deterministic source UUID."""

    spreadsheet = str(source_spreadsheet_id or "").strip()
    tab = str(source_tab or "").strip()
    legacy = str(legacy_source_key or "").strip()
    row_number = _source_row_number(source_row)
    if not spreadsheet or not tab or not legacy:
        raise MigrationContractError("source identity requires spreadsheet, tab, positive row, and legacy key")
    identity = canonical_json(
        {
            "legacy_source_key": legacy,
            "snapshot_sha256": _snapshot_hash(source_snapshot_sha256),
            "source_row": row_number,
            "source_spreadsheet_id": spreadsheet,
            "source_tab": tab,
        }
    )
    return str(uuid.uuid5(SOURCE_NAMESPACE, identity))


def build_manifest_entry(
    *,
    source_spreadsheet_id: str,
    source_snapshot_sha256: str,
    source_tab: str,
    source_row: int,
    legacy_source_key: str,
    row: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic row manifest; ambiguous rows fail into quarantine."""

    source_id = canonical_source_identity(
        source_spreadsheet_id,
        source_snapshot_sha256,
        source_tab,
        source_row,
        legacy_source_key,
    )
    snapshot = _snapshot_hash(source_snapshot_sha256)
    row_copy = dict(row)
    mapping_copy = dict(mapping)
    mapping_type = str(mapping_copy.get("mapping_type") or "").strip()
    wallet_id = mapping_copy.get("wallet_id")
    business_unit_id = mapping_copy.get("business_unit_id")
    canonical_project_id = mapping_copy.get("project_id")
    transaction_id: str | None = None

    explicit = bool(mapping_type and wallet_id and business_unit_id)
    if explicit and mapping_type != "quarantine":
        transaction_id = str(
            mapping_copy.get("transaction_id")
            or uuid.uuid5(TRANSACTION_NAMESPACE, f"{source_id}:{mapping_type}")
        )
        disposition = "mapped"
        reference_map = dict(mapping_copy.get("reference_map") or {})
    else:
        mapping_type = "quarantine"
        wallet_id = None
        business_unit_id = None
        canonical_project_id = None
        disposition = "quarantined"
        reference_map = {
            **dict(mapping_copy.get("reference_map") or {}),
            "excluded_from_canonical_totals": True,
            "quarantine_reason": str(
                mapping_copy.get("reason") or "wallet/business-unit mapping is missing or ambiguous"
            ),
        }

    return {
        "id": source_id,
        "source_spreadsheet_id": str(source_spreadsheet_id).strip(),
        "source_snapshot_sha256": snapshot,
        "source_tab": str(source_tab).strip(),
        "source_row": _source_row_number(source_row),
        "legacy_source_key": str(legacy_source_key).strip(),
        "source_row_sha256": _sha256(row_copy),
        "canonical_transaction_id": transaction_id,
        "canonical_debt_id": mapping_copy.get("debt_id") if explicit else None,
        "canonical_project_id": canonical_project_id,
        "wallet_id": wallet_id,
        "business_unit_id": business_unit_id,
        "mapping_type": mapping_type,
        "reference_map": reference_map,
        "disposition": disposition,
    }


def _group(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "amount": 0, "ending_balance": 0}
    )
    for row in rows:
        wallet_id = str(row.get("wallet_id") or "__unmapped__")
        grouped[wallet_id]["count"] += 1
        grouped[wallet_id]["amount"] += int(row.get("amount") or 0)
        grouped[wallet_id]["ending_balance"] = int(row.get("ending_balance") or 0)
    return dict(grouped)


def reconcile_authorities(
    *,
    legacy_rows: Iterable[Mapping[str, Any]],
    canonical_rows: Iterable[Mapping[str, Any]],
    dangling_references: Iterable[str],
) -> dict[str, Any]:
    legacy = _group(legacy_rows)
    canonical = _group(canonical_rows)
    keys = sorted(set(legacy) | set(canonical))
    unexplained_rows = sum(
        abs(legacy.get(key, {}).get("count", 0) - canonical.get(key, {}).get("count", 0))
        for key in keys
    )
    unexplained_amount = sum(
        abs(legacy.get(key, {}).get("amount", 0) - canonical.get(key, {}).get("amount", 0))
        for key in keys
    )
    ending_balance_drift = sum(
        abs(
            legacy.get(key, {}).get("ending_balance", 0)
            - canonical.get(key, {}).get("ending_balance", 0)
        )
        for key in keys
    )
    dangling = sorted(set(str(item) for item in dangling_references))
    grouped = {
        key: {"legacy": legacy.get(key), "canonical": canonical.get(key)} for key in keys
    }
    result = {
        "unexplained_rows": unexplained_rows,
        "unexplained_amount": unexplained_amount,
        "ending_balance_drift": ending_balance_drift,
        "dangling_references": len(dangling),
        "dangling_reference_ids": dangling,
        "grouped": grouped,
        "grouped_hash_sha256": _sha256(grouped),
    }
    result["cutover_ready"] = all(
        result[field] == CUTOVER_TOLERANCE
        for field in (
            "unexplained_rows",
            "unexplained_amount",
            "ending_balance_drift",
            "dangling_references",
        )
    )
    return result
