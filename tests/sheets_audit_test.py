import unittest
from unittest.mock import patch

import sheets_helper as sheets
from config.constants import (
    OPERASIONAL_COLS,
    OPERASIONAL_DATA_START,
    OPERASIONAL_SHEET_NAME,
    SPLIT_LAYOUT_DATA_START,
    SPLIT_PENGELUARAN,
)
from config.wallets import DOMPET_SHEETS
from services.row_validator import validate_rows


class _FakeWorksheet:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = worksheets

    def worksheet(self, name):
        return self._worksheets[name]


def _blank_rows(count, width):
    return [[""] * width for _ in range(count)]


def _operational_rows():
    rows = _blank_rows(OPERASIONAL_DATA_START - 1, 8)
    row = [""] * 8
    row[OPERASIONAL_COLS["TANGGAL"] - 1] = "2026-06-01"
    row[OPERASIONAL_COLS["JUMLAH"] - 1] = "150.000"
    row[OPERASIONAL_COLS["KETERANGAN"] - 1] = "atk kantor"
    row[OPERASIONAL_COLS["KATEGORI"] - 1] = "Peralatan"
    rows.append(row)
    return rows


def _wallet_rows_with_invalid_manual_edit():
    rows = _blank_rows(SPLIT_LAYOUT_DATA_START - 1, 18)
    row = [""] * 18
    row[SPLIT_PENGELUARAN["JUMLAH"] - 1] = "abc"
    row[SPLIT_PENGELUARAN["PROJECT"] - 1] = "Vadim"
    row[SPLIT_PENGELUARAN["KETERANGAN"] - 1] = "manual broken row"
    rows.append(row)
    return rows


class SheetsAuditRowsTests(unittest.TestCase):
    def test_raw_audit_rows_keep_rows_that_get_all_data_would_skip(self):
        worksheets = {
            OPERASIONAL_SHEET_NAME: _FakeWorksheet(_operational_rows()),
        }
        for dompet in DOMPET_SHEETS:
            worksheets[dompet] = _FakeWorksheet(_blank_rows(SPLIT_LAYOUT_DATA_START - 1, 18))
        worksheets["TX SBY(216)"] = _FakeWorksheet(_wallet_rows_with_invalid_manual_edit())

        with patch.object(sheets, "get_spreadsheet", return_value=_FakeSpreadsheet(worksheets)):
            rows = sheets.get_raw_rows_for_audit()

        broken = [r for r in rows if r.get("keterangan") == "manual broken row"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["sheet_name"], "TX SBY(216)")
        self.assertEqual(broken[0]["sheet_row"], SPLIT_LAYOUT_DATA_START)

        issues = validate_rows(rows)
        self.assertTrue(any(i.field == "tanggal" and i.sheet_name == "TX SBY(216)" for i in issues))
        self.assertTrue(any(i.field == "jumlah" and i.sheet_name == "TX SBY(216)" for i in issues))


if __name__ == "__main__":
    unittest.main()