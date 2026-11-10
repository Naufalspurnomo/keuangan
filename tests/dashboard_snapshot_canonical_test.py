from datetime import datetime, timezone

from dashboard_api.live_snapshot import build_live_snapshot


def _row(**overrides):
    row = {
        "sheet_name": "CV HB(101)",
        "company_sheet": "HOLLA",
        "source_block": "project",
        "sheet_row": 7,
        "tanggal": "2026-11-02",
        "tipe": "Pengeluaran",
        "jumlah": 100_000,
        "nama_projek": "Proyek Alpha (Start)",
        "keterangan": "Pembelian material",
        "kategori": "Material",
        "internal_movement": False,
    }
    row.update(overrides)
    return row


def _snapshot(*rows):
    return build_live_snapshot(
        list(rows),
        {"CV HB(101)": {"saldo": 1_000_000}},
        [],
        now=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )


def test_snapshot_emits_canonical_scope_and_normalized_project_identity():
    snapshot = _snapshot(_row())
    transaction = snapshot["transactions"][0]
    assert transaction["scope"] == "project"
    assert transaction["project"] == "Proyek Alpha"
    assert transaction["project_raw"] == "Proyek Alpha (Start)"
    assert transaction["office_category"] is None
    assert snapshot["project_summaries"][0]["name"] == "Proyek Alpha"


def test_snapshot_keeps_canonical_project_id_across_wallets_and_reload():
    project_id = "00000000-0000-4000-8000-000000000001"
    snapshot = _snapshot(
        _row(project_id=project_id),
        _row(
            project_id=project_id,
            sheet_name="TX SBY(216)",
            company_sheet="TEXTURIN-Surabaya",
            sheet_row=8,
            nama_projek="Proyek Alpha",
        ),
    )

    assert {row["project_id"] for row in snapshot["transactions"]} == {project_id}
    assert len(snapshot["project_summaries"]) == 1
    assert snapshot["project_summaries"][0]["project_id"] == project_id
    assert snapshot["project_summaries"][0]["portfolio"] == "Lintas portfolio"


def test_snapshot_marks_office_rows_explicitly_instead_of_frontend_string_inference():
    snapshot = _snapshot(_row(nama_projek="Operasional", kategori="Operasi Kantor"))
    transaction = snapshot["transactions"][0]
    assert transaction["scope"] == "office"
    assert transaction["project"] is None
    assert transaction["office_category"] == "Operasi Kantor"


def test_snapshot_models_internal_movements_separately():
    snapshot = _snapshot(_row(nama_projek="Transfer Internal", internal_movement=True))
    transaction = snapshot["transactions"][0]
    assert transaction["scope"] == "internal_transfer"
    assert transaction["project"] is None
    assert snapshot["project_summaries"] == []
