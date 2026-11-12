from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.extract_prereset_finance_archive import extract_archive_snapshot
from services.financial_migration import build_manifest

WALLET_ID = "00000000-0000-4000-8000-000000000101"
UNIT_ID = "00000000-0000-4000-8000-000000000201"
SOURCE_KEY = "message:CV HB(101):pemasukan:legacy-1"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _archive(tmp_path: Path) -> tuple[Path, Path, Path]:
    sheets = tmp_path / "sheets.json"
    postgres = tmp_path / "postgres.json"
    manifest = tmp_path / "manifest.json"
    _write_json(sheets, {"CV HB(101)": {"values_formula_mode": []}})
    row = {
        "source_key": SOURCE_KEY,
        "source_sheet": "CV HB(101)",
        "source_row": 9,
        "source_block": "pemasukan",
        "message_id": "legacy-1",
        "transaction_date": "2026-11-01",
        "amount": 125_000,
        "transaction_type": "Pemasukan",
        "company": "CV HB(101)",
        "wallet": "CV HB(101)",
        "project": None,
        "category": "Pendapatan",
        "description": "fixture",
        "recorded_by": "Owner",
        "input_source": "WhatsApp",
        "source_wallet": None,
        "is_valid": True,
        "payload": {"legacy": True},
    }
    columns = sorted(row)
    _write_json(
        postgres,
        {
            "tables": {
                "financial_ledger": {
                    "columns": columns,
                    "count": 1,
                    "rows": [row],
                }
            }
        },
    )
    _write_json(
        manifest,
        {
            "created_utc": "20261103T001922Z",
            "workbook_id": "sheet-fixture",
            "financial_ledger_count": 1,
            "files": {
                "sheets.json": hashlib.sha256(sheets.read_bytes()).hexdigest(),
                "postgres.json": hashlib.sha256(postgres.read_bytes()).hexdigest(),
            },
        },
    )
    return manifest, sheets, postgres


def test_extracts_deterministically_and_preserves_trusted_source_key(tmp_path: Path) -> None:
    manifest, sheets, postgres = _archive(tmp_path)
    first = extract_archive_snapshot(
        manifest_path=manifest,
        sheets_path=sheets,
        postgres_path=postgres,
        output_path=tmp_path / "first.json",
    )
    second = extract_archive_snapshot(
        manifest_path=manifest,
        sheets_path=sheets,
        postgres_path=postgres,
        output_path=tmp_path / "second.json",
    )

    assert first == second
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()
    row = first["tabs"]["CV HB(101)"][0]
    assert row["source_key"] == SOURCE_KEY
    migration = build_manifest(
        first,
        {
            "wallets": {
                "CV HB(101)": {
                    "wallet_id": WALLET_ID,
                    "business_unit_id": UNIT_ID,
                }
            }
        },
    )
    assert [row["disposition"] for row in migration["rows"]] == ["mapped"]
    assert migration["rows"][0]["legacy_source_key"] == SOURCE_KEY


def test_rejects_archive_hash_mismatch_without_output(tmp_path: Path) -> None:
    manifest, sheets, postgres = _archive(tmp_path)
    sheets.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"

    with pytest.raises(ValueError, match="archive hash mismatch"):
        extract_archive_snapshot(
            manifest_path=manifest,
            sheets_path=sheets,
            postgres_path=postgres,
            output_path=output,
        )

    assert not output.exists()


def test_accepts_shared_sheet_locator_when_source_keys_differ(tmp_path: Path) -> None:
    manifest, sheets, postgres = _archive(tmp_path)
    data = json.loads(postgres.read_text(encoding="utf-8"))
    table = data["tables"]["financial_ledger"]
    second = dict(table["rows"][0])
    second.update(
        {
            "source_key": "message:CV HB(101):pemasukan:legacy-2",
            "message_id": "legacy-2",
            "amount": 225_000,
        }
    )
    table["rows"].append(second)
    table["count"] = 2
    _write_json(postgres, data)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["financial_ledger_count"] = 2
    manifest_data["files"]["postgres.json"] = hashlib.sha256(postgres.read_bytes()).hexdigest()
    _write_json(manifest, manifest_data)

    snapshot = extract_archive_snapshot(
        manifest_path=manifest,
        sheets_path=sheets,
        postgres_path=postgres,
        output_path=tmp_path / "snapshot.json",
    )
    assert snapshot["provenance"]["shared_source_coordinates"] == 1
    migration = build_manifest(
        snapshot,
        {
            "wallets": {
                "CV HB(101)": {
                    "wallet_id": WALLET_ID,
                    "business_unit_id": UNIT_ID,
                }
            }
        },
    )
    assert len(migration["rows"]) == 2
    assert len({row["id"] for row in migration["rows"]}) == 2
    assert {row["source_block"] for row in migration["rows"]} == {"pemasukan"}


def test_rejects_duplicate_provenance(tmp_path: Path) -> None:
    manifest, sheets, postgres = _archive(tmp_path)
    data = json.loads(postgres.read_text(encoding="utf-8"))
    table = data["tables"]["financial_ledger"]
    table["rows"].append(dict(table["rows"][0]))
    table["count"] = 2
    _write_json(postgres, data)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["financial_ledger_count"] = 2
    manifest_data["files"]["postgres.json"] = hashlib.sha256(postgres.read_bytes()).hexdigest()
    _write_json(manifest, manifest_data)

    with pytest.raises(ValueError, match="duplicate provenance"):
        extract_archive_snapshot(
            manifest_path=manifest,
            sheets_path=sheets,
            postgres_path=postgres,
            output_path=tmp_path / "snapshot.json",
        )
