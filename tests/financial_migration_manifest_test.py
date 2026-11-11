from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from services.financial_migration import build_manifest, reconcile_manifest


ROOT = Path(__file__).resolve().parents[1]


WALLET_ID = "11111111-1111-4111-8111-111111111111"
UNIT_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"


def snapshot():
    return {
        "spreadsheet_id": "sheet-123",
        "tabs": {
            "CV HB(101)": [
                {
                    "sheet_row": 10,
                    "source_block": "pemasukan",
                    "tanggal": "2026-11-01",
                    "jumlah": "1.000.000",
                    "tipe": "Pemasukan",
                    "keterangan": "Project payment",
                    "project_id": PROJECT_ID,
                },
                {
                    "sheet_row": 11,
                    "source_block": "pengeluaran",
                    "tanggal": "broken",
                    "jumlah": "not-money",
                    "tipe": "Pengeluaran",
                    "keterangan": "manual broken row",
                },
            ]
        },
    }


def mappings():
    return {
        "wallets": {
            "CV HB(101)": {
                "wallet_id": WALLET_ID,
                "business_unit_id": UNIT_ID,
            }
        },
        "projects": {PROJECT_ID: PROJECT_ID},
    }


def test_manifest_is_deterministic_and_quarantines_invalid_rows():
    first = build_manifest(snapshot(), mappings())
    second = build_manifest(deepcopy(snapshot()), deepcopy(mappings()))

    assert first == second
    assert len(first["rows"]) == 2
    mapped, quarantined = first["rows"]
    assert mapped["disposition"] == "mapped"
    assert mapped["mapping_type"] == "transaction"
    assert mapped["canonical_transaction_id"]
    assert mapped["wallet_id"] == WALLET_ID
    assert mapped["business_unit_id"] == UNIT_ID
    assert mapped["canonical_project_id"] == PROJECT_ID
    assert quarantined["disposition"] == "quarantined"
    assert quarantined["mapping_type"] == "quarantine"
    assert quarantined["disposition_actor"]["kind"] == "migration"
    assert quarantined["disposition_reason"]
    assert first["source_snapshot_sha256"] == second["source_snapshot_sha256"]


def test_project_name_never_substitutes_for_explicit_project_id():
    source = snapshot()
    row = source["tabs"]["CV HB(101)"][0]
    row.pop("project_id")
    row["nama_projek"] = "Project payment"

    result = build_manifest(source, mappings())

    assert result["rows"][0]["disposition"] == "quarantined"
    assert "project_id" in result["rows"][0]["disposition_reason"]


def test_checkpoint_resume_produces_same_rows_without_duplicates():
    source = snapshot()
    full = build_manifest(source, mappings())
    first = build_manifest(source, mappings(), limit=1)
    resumed = build_manifest(source, mappings(), start_after=first["checkpoint"])

    combined = first["rows"] + resumed["rows"]
    assert combined == full["rows"]
    assert len({row["id"] for row in combined}) == len(combined)
    assert resumed["checkpoint"] == full["checkpoint"]


def test_reconciliation_never_hides_offsetting_missing_amounts():
    source = snapshot()
    source["tabs"]["CV HB(101)"][1] = {
        "sheet_row": 11,
        "source_block": "pengeluaran",
        "tanggal": "2026-11-02",
        "jumlah": "1.000.000",
        "tipe": "Pengeluaran",
        "keterangan": "Project cost",
        "project_id": PROJECT_ID,
    }
    complete = build_manifest(source, mappings())
    missing = deepcopy(complete)
    missing["rows"] = []

    result = reconcile_manifest(source, missing)

    assert result["unexplained_rows"] == 2
    assert result["unexplained_amount"] == 2_000_000
    assert result["ending_balance_drift"] == 0
    assert result["cutover_ready"] is False


def test_explicit_quarantine_is_excluded_from_canonical_amounts():
    source = snapshot()
    source["tabs"]["UNKNOWN"] = [
        {
            "sheet_row": 2,
            "source_block": "pemasukan",
            "tanggal": "2026-11-03",
            "jumlah": "500000",
            "tipe": "Pemasukan",
            "keterangan": "unknown wallet",
        }
    ]
    manifest = build_manifest(source, mappings())

    result = reconcile_manifest(source, manifest)

    assert result["quarantined_rows"] == 2
    assert result["unexplained_amount"] == 0
    assert result["ending_balance_drift"] == 0
    assert result["cutover_ready"] is True


def test_reconciliation_requires_complete_untampered_manifest():
    result = build_manifest(snapshot(), mappings())

    reconciled = reconcile_manifest(snapshot(), result)
    assert reconciled == {
        "source_snapshot_sha256": result["source_snapshot_sha256"],
        "source_rows": 2,
        "manifest_rows": 2,
        "mapped_rows": 1,
        "quarantined_rows": 1,
        "unexplained_rows": 0,
        "unexplained_amount": 0,
        "ending_balance_drift": 0,
        "dangling_references": 0,
        "cutover_ready": True,
    }

    missing = deepcopy(result)
    missing["rows"].pop()
    missing_result = reconcile_manifest(snapshot(), missing)
    assert missing_result["cutover_ready"] is False
    assert missing_result["unexplained_rows"] == 1
    assert missing_result["unexplained_amount"] == 0

    missing_valid = deepcopy(result)
    missing_valid["rows"].pop(0)
    missing_valid_result = reconcile_manifest(snapshot(), missing_valid)
    assert missing_valid_result["cutover_ready"] is False
    assert missing_valid_result["unexplained_rows"] == 1
    assert missing_valid_result["unexplained_amount"] == 1_000_000
    assert missing_valid_result["ending_balance_drift"] == 1_000_000

    tampered = deepcopy(result)
    tampered["rows"][0]["source_row_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source row hash"):
        reconcile_manifest(snapshot(), tampered)


def test_dry_run_and_reconciliation_clis_are_side_effect_free(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    mappings_path = tmp_path / "mappings.json"
    manifest_path = tmp_path / "manifest.json"
    reconciliation_path = tmp_path / "reconciliation.json"
    snapshot_path.write_text(json.dumps(snapshot()), encoding="utf-8")
    mappings_path.write_text(json.dumps(mappings()), encoding="utf-8")

    backfill = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "backfill_sheets_to_postgres.py"),
            "--dry-run",
            "--snapshot",
            str(snapshot_path),
            "--mappings",
            str(mappings_path),
            "--output",
            str(manifest_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={},
    )
    assert backfill.returncode == 0, backfill.stderr
    assert json.loads(backfill.stdout) == json.loads(manifest_path.read_text())

    reconcile = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reconcile_financial_authorities.py"),
            "--snapshot",
            str(snapshot_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(reconciliation_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={},
    )
    assert reconcile.returncode == 0, reconcile.stderr
    assert json.loads(reconcile.stdout)["cutover_ready"] is True

    incomplete = json.loads(manifest_path.read_text())
    incomplete["rows"].pop(0)
    manifest_path.write_text(json.dumps(incomplete), encoding="utf-8")
    reconcile_incomplete = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reconcile_financial_authorities.py"),
            "--snapshot",
            str(snapshot_path),
            "--manifest",
            str(manifest_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={},
    )
    assert reconcile_incomplete.returncode == 2
    assert json.loads(reconcile_incomplete.stdout)["cutover_ready"] is False


def test_backfill_cli_requires_explicit_dry_run(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    mappings_path = tmp_path / "mappings.json"
    snapshot_path.write_text(json.dumps(snapshot()), encoding="utf-8")
    mappings_path.write_text(json.dumps(mappings()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "backfill_sheets_to_postgres.py"),
            "--snapshot",
            str(snapshot_path),
            "--mappings",
            str(mappings_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={},
    )
    assert result.returncode == 2
    assert "--dry-run" in result.stderr
