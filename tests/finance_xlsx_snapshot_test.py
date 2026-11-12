from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from scripts.extract_finance_xlsx_snapshot import EXPECTED_HEADERS, extract_snapshot
from services.financial_migration import build_manifest, reconcile_manifest


WALLET_ID = "00000000-0000-4000-8000-000000000001"
UNIT_ID = "00000000-0000-4000-8000-000000000002"


def _workbook(path: Path, *, bad_header: bool = False) -> None:
    workbook = Workbook()
    active = workbook.active
    assert active is not None
    workbook.remove(active)
    for tab, header in EXPECTED_HEADERS.items():
        sheet = workbook.create_sheet(tab)
        sheet.append(list(header))
    aggregate = workbook["Data_Agregat"]
    if bad_header:
        aggregate.cell(row=1, column=1, value="Tanggal Diubah")
    aggregate.append([
        datetime(2026, 11, 1),
        "12:00",
        "Pemasukan",
        "CV HB(101)",
        500_000,
        "",
        "Termin pertama",
        "Admin",
        "WhatsApp",
        "message-001",
        "Income",
        "HOLLA",
        "Finance",
    ])
    aggregate.append([
        datetime(2026, 11, 2),
        "13:00",
        "Pengeluaran",
        "TX SBY(216)",
        200_000,
        "Proyek Tanpa UUID",
        "Material",
        "Admin",
        "WhatsApp",
        "message-002",
        "Material",
        "TEXTURIN-Surabaya",
        "Finance",
    ])
    workbook["Ops Kantor Baru"].append([
        1,
        datetime(2026, 11, 3),
        100_000,
        "Internet kantor",
        "Admin",
        "WhatsApp",
        "Internet",
        "message-003",
    ])
    workbook.save(path)


def test_extracts_deterministic_authority_snapshot_and_preserves_source_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "Keuangan.xlsx"
    _workbook(source)

    first = extract_snapshot(
        source,
        spreadsheet_id="owner-finance-workbook",
        captured_at="2026-11-10T04:06:24Z",
    )
    second = extract_snapshot(
        source,
        spreadsheet_id="owner-finance-workbook",
        captured_at="2026-11-10T04:06:24Z",
    )

    assert first == second
    assert first["source"]["authority_tabs"] == ["Data_Agregat", "Ops Kantor Baru", "HUTANG"]
    assert [row["sheet_row"] for row in first["tabs"]["Data_Agregat"]] == [2, 3]
    assert first["tabs"]["Data_Agregat"][0]["sheet_name"] == "CV HB(101)"
    assert first["tabs"]["Ops Kantor Baru"][0]["source_block"] == "office"
    assert first["tabs"]["HUTANG"] == []
    json.dumps(first, ensure_ascii=False, sort_keys=True)


def test_rejects_header_drift_before_building_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "Keuangan.xlsx"
    _workbook(source, bad_header=True)

    with pytest.raises(ValueError, match="unexpected header"):
        extract_snapshot(
            source,
            spreadsheet_id="owner-finance-workbook",
            captured_at="2026-11-10T04:06:24Z",
        )


def test_rejects_formula_errors_in_authority_rows(tmp_path: Path) -> None:
    source = tmp_path / "Keuangan.xlsx"
    _workbook(source)
    workbook = Workbook()
    active = workbook.active
    assert active is not None
    workbook.remove(active)
    for tab, header in EXPECTED_HEADERS.items():
        sheet = workbook.create_sheet(tab)
        sheet.append(list(header))
    workbook["Data_Agregat"].append(["#N/A", None, "Pemasukan", "CV HB(101)", 1])
    workbook.save(source)

    with pytest.raises(ValueError, match="formula error"):
        extract_snapshot(
            source,
            spreadsheet_id="owner-finance-workbook",
            captured_at="2026-11-10T04:06:24Z",
        )


def test_manifest_maps_by_wallet_column_not_aggregate_source_tab(tmp_path: Path) -> None:
    source = tmp_path / "Keuangan.xlsx"
    _workbook(source)
    snapshot = extract_snapshot(
        source,
        spreadsheet_id="owner-finance-workbook",
        captured_at="2026-11-10T04:06:24Z",
    )
    mappings = {
        "wallets": {
            "CV HB(101)": {"wallet_id": WALLET_ID, "business_unit_id": UNIT_ID},
        },
        "projects": {},
    }

    manifest = build_manifest(snapshot, mappings)
    rows = {(row["source_tab"], row["source_row"]): row for row in manifest["rows"]}
    mapped = rows[("Data_Agregat", 2)]
    missing_wallet = rows[("Data_Agregat", 3)]
    office = rows[("Ops Kantor Baru", 2)]

    assert mapped["disposition"] == "mapped"
    assert mapped["wallet_id"] == WALLET_ID
    assert mapped["source_tab"] == "Data_Agregat"
    assert missing_wallet["disposition_reason"] == "wallet mapping missing for source wallet TX SBY(216)"
    assert office["disposition_reason"] == "wallet mapping missing for source wallet Ops Kantor Baru"
    reconciliation = reconcile_manifest(snapshot, manifest)
    assert reconciliation["coverage_complete"] is True
    assert reconciliation["cutover_ready"] is False
