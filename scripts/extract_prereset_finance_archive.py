#!/usr/bin/env python3
"""Build a deterministic migration snapshot from the verified pre-reset archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



EXPECTED_COLUMNS = {
    "source_key",
    "source_sheet",
    "source_row",
    "source_block",
    "message_id",
    "transaction_date",
    "amount",
    "transaction_type",
    "company",
    "wallet",
    "project",
    "category",
    "description",
    "recorded_by",
    "input_source",
    "source_wallet",
    "is_valid",
    "payload",
}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_archive_snapshot(
    *, manifest_path: Path, sheets_path: Path, postgres_path: Path, output_path: Path
) -> dict[str, Any]:
    manifest = _load(manifest_path)
    postgres = _load(postgres_path)
    declared_files = manifest.get("files")
    if not isinstance(declared_files, dict):
        raise ValueError("archive manifest files map is missing")
    for path in (sheets_path, postgres_path):
        if declared_files.get(path.name) != _sha256(path):
            raise ValueError(f"archive hash mismatch: {path.name}")

    table = (postgres.get("tables") or {}).get("financial_ledger")
    if not isinstance(table, dict):
        raise ValueError("financial_ledger table is missing")
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not EXPECTED_COLUMNS.issubset(columns):
        raise ValueError("financial_ledger columns are incompatible")
    if not isinstance(rows, list) or table.get("count") != len(rows):
        raise ValueError("financial_ledger row count is inconsistent")
    if manifest.get("financial_ledger_count") != len(rows):
        raise ValueError("archive manifest ledger count mismatch")

    tabs: dict[str, list[dict[str, Any]]] = {}
    source_keys: set[str] = set()
    source_coordinates: Counter[tuple[str, str, int]] = Counter()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("financial_ledger row must be an object")
        if raw.get("is_valid") is not True:
            raise ValueError("pre-reset projection contains an invalid ledger row")
        source_key = str(raw.get("source_key") or "").strip()
        source_sheet = str(raw.get("source_sheet") or "").strip()
        source_block = str(raw.get("source_block") or "").strip().lower()
        source_row = raw.get("source_row")
        if not source_key or not source_sheet or source_block not in {
            "pemasukan",
            "pengeluaran",
            "operasional",
        }:
            raise ValueError("pre-reset projection row has incomplete provenance")
        if not isinstance(source_row, int) or source_row <= 0:
            raise ValueError("pre-reset projection row has invalid source coordinate")
        coordinate = (source_sheet, source_block, source_row)
        if source_key in source_keys:
            raise ValueError("pre-reset projection contains duplicate provenance")
        source_keys.add(source_key)
        source_coordinates[coordinate] += 1

        payload = raw.get("payload")
        row = dict(payload) if isinstance(payload, dict) else {}
        row.update(
            {
                "sheet_name": source_sheet,
                "source_tab": source_sheet,
                "sheet_row": source_row,
                "source_block": source_block,
                "source_key": source_key,
                "preserve_source_key": True,
                "message_id": raw.get("message_id"),
                "tanggal": raw.get("transaction_date"),
                "jumlah": raw.get("amount"),
                "tipe": raw.get("transaction_type"),
                "company_sheet": raw.get("company"),
                "dompet_sheet": raw.get("wallet"),
                "nama_projek": raw.get("project"),
                "kategori": raw.get("category"),
                "keterangan": raw.get("description"),
                "oleh": raw.get("recorded_by"),
                "source": raw.get("input_source"),
                "source_wallet": raw.get("source_wallet"),
                "project_id": None,
            }
        )
        tabs.setdefault(source_sheet, []).append(row)

    for rows_for_tab in tabs.values():
        rows_for_tab.sort(key=lambda row: (row["sheet_row"], row["source_block"], row["source_key"]))

    snapshot: dict[str, Any] = {
        "spreadsheet_id": str(manifest.get("workbook_id") or "").strip(),
        "tabs": dict(sorted(tabs.items())),
        "captured_at": str(manifest.get("created_utc") or "").strip(),
        "provenance": {
            "archive_manifest_sha256": _sha256(manifest_path),
            "sheets_sha256": _sha256(sheets_path),
            "postgres_sha256": _sha256(postgres_path),
            "legacy_ledger_rows": len(rows),
            "shared_source_coordinates": sum(
                count > 1 for count in source_coordinates.values()
            ),
            "source": "verified-pre-reset-archive",
        },
    }
    if not snapshot["spreadsheet_id"] or not snapshot["captured_at"]:
        raise ValueError("archive workbook identity or cutoff is missing")
    snapshot["snapshot_hash"] = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sheets", type=Path, required=True)
    parser.add_argument("--postgres", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = extract_archive_snapshot(
        manifest_path=args.manifest,
        sheets_path=args.sheets,
        postgres_path=args.postgres,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "spreadsheet_id": snapshot["spreadsheet_id"],
                "snapshot_hash": snapshot["snapshot_hash"],
                "tabs": {name: len(rows) for name, rows in snapshot["tabs"].items()},
                "rows": snapshot["provenance"]["legacy_ledger_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
