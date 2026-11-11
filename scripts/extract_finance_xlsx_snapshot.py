#!/usr/bin/env python3
"""Extract immutable financial authority rows from a verified XLSX backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


AUTHORITY_TABS = ("Data_Agregat", "Ops Kantor Baru", "HUTANG")
EXPECTED_HEADERS = {
    "Data_Agregat": (
        "Tanggal", "Waktu", "Tipe", "Dompet", "Jumlah", "Projek", "Keterangan",
        "Oleh", "Source", "MessageID", "Kategori", "Company", "Group",
    ),
    "Ops Kantor Baru": (
        "No", "Tanggal", "Jumlah", "Keterangan", "Oleh", "Source", "Kategori", "MessageID",
    ),
    "HUTANG": (
        "No", "Tanggal", "Nominal", "Keterangan", "Yang Hutang", "Yang Dihutangi",
        "Status", "Tgl Lunas", "MessageID",
    ),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _date_cell(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _canonical(value)


def _row(tab: str, sheet_row: int, header: tuple[str, ...], values: tuple[Any, ...]) -> dict[str, Any]:
    cells = {name: _canonical(values[index] if index < len(values) else None) for index, name in enumerate(header)}
    for field in ("Tanggal", "Tgl Lunas"):
        if field in cells:
            cells[field] = _date_cell(values[header.index(field)] if header.index(field) < len(values) else None)
    if tab == "Data_Agregat":
        project = str(cells["Projek"]).strip() if cells["Projek"] not in (None, "") else None
        return {
            "sheet_row": sheet_row,
            "tanggal": cells["Tanggal"],
            "waktu": cells["Waktu"],
            "tipe": cells["Tipe"],
            "sheet_name": cells["Dompet"],
            "jumlah": cells["Jumlah"],
            "nama_projek": project,
            "keterangan": cells["Keterangan"],
            "oleh": cells["Oleh"],
            "source": cells["Source"],
            "message_id": cells["MessageID"],
            "kategori": cells["Kategori"],
            "company_sheet": cells["Company"],
            "source_group": cells["Group"],
            "source_block": str(cells["Tipe"] or "transaction").strip().casefold(),
        }
    if tab == "Ops Kantor Baru":
        return {
            "sheet_row": sheet_row,
            "tanggal": cells["Tanggal"],
            "tipe": "Pengeluaran",
            "sheet_name": "Ops Kantor Baru",
            "jumlah": cells["Jumlah"],
            "nama_projek": None,
            "keterangan": cells["Keterangan"],
            "oleh": cells["Oleh"],
            "source": cells["Source"],
            "message_id": cells["MessageID"],
            "kategori": cells["Kategori"],
            "company_sheet": "Operasional",
            "source_block": "office",
        }
    return {
        "sheet_row": sheet_row,
        "tanggal": cells["Tanggal"],
        "tipe": "Pengeluaran",
        "sheet_name": "HUTANG",
        "jumlah": cells["Nominal"],
        "nama_projek": None,
        "keterangan": cells["Keterangan"],
        "message_id": cells["MessageID"],
        "source_block": "debt_principal",
        "borrower": cells["Yang Hutang"],
        "lender": cells["Yang Dihutangi"],
        "debt_status": cells["Status"],
        "paid_at": cells["Tgl Lunas"],
    }


def extract_snapshot(source: Path, *, spreadsheet_id: str, captured_at: str) -> dict[str, Any]:
    if not source.is_file() or source.is_symlink():
        raise ValueError("source XLSX must be a regular file")
    source_bytes = source.read_bytes()
    workbook = load_workbook(source, read_only=True, data_only=True)
    if tuple(name for name in AUTHORITY_TABS if name not in workbook.sheetnames):
        raise ValueError("authority tab missing")
    tabs: dict[str, list[dict[str, Any]]] = {}
    tab_hashes: dict[str, str] = {}
    for tab in AUTHORITY_TABS:
        worksheet = workbook[tab]
        iterator = worksheet.iter_rows(values_only=True)
        actual_header = tuple(str(value).strip() if value is not None else "" for value in next(iterator, ()))
        expected_header = EXPECTED_HEADERS[tab]
        if actual_header[: len(expected_header)] != expected_header:
            raise ValueError(f"unexpected header for authority tab {tab}")
        rows: list[dict[str, Any]] = []
        for sheet_row, values in enumerate(iterator, start=2):
            if not any(value not in (None, "") for value in values):
                continue
            if any(isinstance(value, str) and value.startswith("#") for value in values[: len(expected_header)]):
                raise ValueError(f"authority tab {tab} contains a formula error at row {sheet_row}")
            rows.append(_row(tab, sheet_row, expected_header, values))
        tabs[tab] = rows
        tab_hashes[tab] = _sha256_bytes(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    return {
        "version": "hollawall.finance.source-snapshot.v1",
        "spreadsheet_id": spreadsheet_id,
        "captured_at": captured_at,
        "source": {
            "filename": source.name,
            "sha256": _sha256_bytes(source_bytes),
            "bytes": len(source_bytes),
            "authority_tabs": list(AUTHORITY_TABS),
            "tab_hashes": tab_hashes,
        },
        "tabs": tabs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = extract_snapshot(
        args.source,
        spreadsheet_id=args.spreadsheet_id.strip(),
        captured_at=args.captured_at.strip(),
    )
    if not snapshot["spreadsheet_id"]:
        raise ValueError("spreadsheet ID is required")
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "version": snapshot["version"],
        "source_sha256": snapshot["source"]["sha256"],
        "rows": {tab: len(rows) for tab, rows in snapshot["tabs"].items()},
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
