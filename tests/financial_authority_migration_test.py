from __future__ import annotations

import hashlib

import pytest

from services.financial_authority_migration import (
    CUTOVER_TOLERANCE,
    MigrationContractError,
    build_manifest_entry,
    canonical_source_identity,
    reconcile_authorities,
)
from services.financial_export import (
    CanonicalExportRow,
    ExportContractError,
    export_rows,
    verify_export_rows,
)


SNAPSHOT = hashlib.sha256(b"immutable-sheet-export").hexdigest()


def test_historical_source_identity_is_deterministic_and_coordinate_bound():
    first = canonical_source_identity("sheet-1", SNAPSHOT, "Wallet A", 22, "legacy:22")
    rerun = canonical_source_identity("sheet-1", SNAPSHOT, "Wallet A", 22, "legacy:22")
    next_row = canonical_source_identity("sheet-1", SNAPSHOT, "Wallet A", 23, "legacy:22")

    assert first == rerun
    assert first != next_row


def test_historical_source_identity_rejects_fractional_row_coordinates():
    with pytest.raises(MigrationContractError, match="positive integer row"):
        canonical_source_identity(
            "sheet-1", SNAPSHOT, "Wallet A", 22.5, "legacy:22"  # type: ignore[arg-type]
        )


def test_unmapped_row_is_quarantined_and_never_defaults_to_office():
    entry = build_manifest_entry(
        source_spreadsheet_id="sheet-1",
        source_snapshot_sha256=SNAPSHOT,
        source_tab="Wallet A",
        source_row=22,
        legacy_source_key="legacy:22",
        row={"amount": 50_000, "project": "Unknown"},
        mapping={},
    )

    assert entry["mapping_type"] == "quarantine"
    assert entry["disposition"] == "quarantined"
    assert entry["canonical_transaction_id"] is None
    assert entry["reference_map"]["excluded_from_canonical_totals"] is True


def test_cutover_reconciliation_requires_every_drift_and_dangling_count_to_be_zero():
    exact = reconcile_authorities(
        legacy_rows=[{"wallet_id": "w1", "amount": 100, "ending_balance": 500}],
        canonical_rows=[{"wallet_id": "w1", "amount": 100, "ending_balance": 500}],
        dangling_references=[],
    )
    drifted = reconcile_authorities(
        legacy_rows=[{"wallet_id": "w1", "amount": 100, "ending_balance": 500}],
        canonical_rows=[{"wallet_id": "w1", "amount": 99, "ending_balance": 499}],
        dangling_references=["allocation:1"],
    )

    assert CUTOVER_TOLERANCE == 0
    assert exact["cutover_ready"] is True
    assert drifted["cutover_ready"] is False
    assert drifted["unexplained_amount"] == 1
    assert drifted["ending_balance_drift"] == 1
    assert drifted["dangling_references"] == 1


class _ExportSheet:
    def __init__(self):
        self.rows = {}
        self.writes = 0

    def read(self, export_key):
        return self.rows.get(export_key)

    def upsert(self, export_key, payload):
        self.writes += 1
        self.rows[export_key] = dict(payload)


def test_export_is_idempotent_across_crash_window_and_detects_manual_edit():
    sheet = _ExportSheet()
    row = CanonicalExportRow(
        transaction_id="a47f5f25-f461-5f35-a397-f3d87f5efcc1",
        sequence=1,
        payload={"amount": 125_000, "status": "posted"},
    )

    first = export_rows([row], sheet=sheet, protected_destination=True)
    replay = export_rows([row], sheet=sheet, protected_destination=True)

    assert first["written"] == 1
    assert replay["written"] == 0
    assert sheet.writes == 1
    assert verify_export_rows([row], sheet=sheet)["ready"] is True

    sheet.rows[row.export_key]["amount"] = 1
    drift = verify_export_rows([row], sheet=sheet)
    assert drift["ready"] is False
    assert drift["edited"] == [row.export_key]


def test_export_refuses_unprotected_or_noncanonical_destination():
    sheet = _ExportSheet()
    row = CanonicalExportRow(
        transaction_id="a47f5f25-f461-5f35-a397-f3d87f5efcc1",
        sequence=1,
        payload={"amount": 1},
    )
    with pytest.raises(ExportContractError, match="protected"):
        export_rows([row], sheet=sheet, protected_destination=False)


def test_export_rejects_reserved_metadata_overrides_and_fractional_sequences():
    with pytest.raises(ExportContractError, match="reserved"):
        CanonicalExportRow(
            transaction_id="a47f5f25-f461-5f35-a397-f3d87f5efcc1",
            sequence=1,
            payload={"export_key": "forged"},
        )

    with pytest.raises(ExportContractError, match="positive integer"):
        CanonicalExportRow(
            transaction_id="a47f5f25-f461-5f35-a397-f3d87f5efcc1",
            sequence=1.5,  # type: ignore[arg-type]
            payload={"amount": 1},
        )
