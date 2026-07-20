import unittest
from datetime import date

from services.ledger_bootstrap import _select_rows


class LedgerBootstrapTests(unittest.TestCase):
    def test_select_rows_keeps_only_valid_rows_inside_window(self):
        rows = [
            {"sheet_name": "CV HB(101)", "sheet_row": 9, "source_block": "pengeluaran", "tanggal": date.today().isoformat(), "jumlah": "1000"},
            {"sheet_name": "CV HB(101)", "sheet_row": 10, "source_block": "pengeluaran", "tanggal": "manual", "jumlah": "-"},
        ]
        selected, invalid = _select_rows(rows, 365)

        self.assertEqual(len(selected), 1)
        self.assertEqual(invalid, 1)


if __name__ == "__main__":
    unittest.main()
