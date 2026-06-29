"""Tests for services.row_validator (Fase 1-kecil pagar data)."""

import unittest

from services.row_validator import (
    validate_row,
    validate_rows,
    summarize_issues,
    format_issue_report,
)


def _good_row(**over):
    base = {
        "tanggal": "2026-06-01",
        "keterangan": "beli cat",
        "jumlah": 150000,
        "tipe": "Pengeluaran",
        "nama_projek": "vadim",
        "company_sheet": "TEXTURIN-Surabaya",
        "sheet_name": "TX SBY(216)",
    }
    base.update(over)
    return base


class RowValidatorTests(unittest.TestCase):
    def test_clean_row_has_no_issues(self):
        self.assertEqual(validate_row(_good_row()), [])

    def test_operational_row_is_known(self):
        row = _good_row(company_sheet="Operasional Kantor", nama_projek="Operasional")
        self.assertEqual(validate_row(row), [])

    def test_empty_amount_flagged(self):
        issues = validate_row(_good_row(jumlah=""))
        self.assertTrue(any(i.field == "jumlah" for i in issues))

    def test_zero_and_negative_amount_flagged(self):
        self.assertTrue(any(i.field == "jumlah" for i in validate_row(_good_row(jumlah=0))))
        self.assertTrue(any(i.field == "jumlah" for i in validate_row(_good_row(jumlah=-5000))))

    def test_nonnumeric_amount_flagged(self):
        issues = validate_row(_good_row(jumlah="seratus ribu"))
        self.assertTrue(any(i.field == "jumlah" for i in issues))

    def test_numeric_string_amount_is_accepted(self):
        self.assertEqual(validate_row(_good_row(jumlah="150000")), [])

    def test_formatted_rupiah_amount_is_accepted(self):
        self.assertEqual(validate_row(_good_row(jumlah="Rp 150.000")), [])
        self.assertEqual(validate_row(_good_row(jumlah="480,000.00")), [])

    def test_missing_date_flagged(self):
        issues = validate_row(_good_row(tanggal=""))
        self.assertTrue(any(i.field == "tanggal" for i in issues))

    def test_unknown_tipe_flagged(self):
        issues = validate_row(_good_row(tipe="Transfer"))
        self.assertTrue(any(i.field == "tipe" for i in issues))

    def test_unknown_dompet_flagged(self):
        row = _good_row(company_sheet="Dompet Misterius", sheet_name="", dompet="")
        issues = validate_row(row)
        self.assertTrue(any(i.field == "dompet" for i in issues))

    def test_known_via_sheet_name_only(self):
        row = _good_row(company_sheet="", dompet="", sheet_name="CV HB(101)")
        self.assertEqual(validate_row(row), [])

    def test_non_dict_row_flagged(self):
        issues = validate_row(["not", "a", "dict"], index=3)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].problem, "not_a_dict")
        self.assertEqual(issues[0].index, 3)

    def test_validate_rows_aggregates(self):
        rows = [_good_row(), _good_row(jumlah=0), _good_row(tipe="X")]
        issues = validate_rows(rows)
        summary = summarize_issues(issues)
        self.assertEqual(summary["rows_flagged"], 2)
        self.assertEqual(summary["total_issues"], 2)

    def test_format_report_clean(self):
        self.assertIn("Tidak ada", format_issue_report([]))

    def test_format_report_lists_issues(self):
        issues = validate_rows([_good_row(jumlah=0)])
        report = format_issue_report(issues)
        self.assertIn("Baris 1", report)
        self.assertIn("nominal", report.lower())

    def test_empty_input_is_safe(self):
        self.assertEqual(validate_rows([]), [])
        self.assertEqual(validate_rows(None), [])


if __name__ == "__main__":
    unittest.main()
