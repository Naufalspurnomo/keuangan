import unittest
from unittest.mock import patch

import sheets_helper
from config.constants import (
    HUTANG_COLS,
    OPERASIONAL_COLS,
    SPLIT_PEMASUKAN,
    SPLIT_PENGELUARAN,
)


class _FakeDompetSheet:
    def __init__(self, pemasukan=0, pengeluaran=0):
        self.pemasukan = int(pemasukan or 0)
        self.pengeluaran = int(pengeluaran or 0)

    def col_values(self, col_idx):
        base = [""] * 8  # SPLIT_LAYOUT_DATA_START - 1
        if col_idx == SPLIT_PEMASUKAN["JUMLAH"]:
            return base + [str(self.pemasukan)]
        if col_idx == SPLIT_PENGELUARAN["JUMLAH"]:
            return base + [str(self.pengeluaran)]
        return base


class _FakeOperationalSheet:
    def __init__(self):
        row = [""] * 8
        row[OPERASIONAL_COLS["JUMLAH"] - 1] = "100000"
        row[OPERASIONAL_COLS["KETERANGAN"] - 1] = "Biaya listrik [Sumber: CV HB]"
        self.rows = [["header"], row]

    def get_all_values(self):
        return self.rows


class _FakeHutangSheet:
    def __init__(self):
        row_open = [""] * 9
        row_open[HUTANG_COLS["NOMINAL"] - 1] = "300000"
        row_open[HUTANG_COLS["YANG_HUTANG"] - 1] = "TX SBY(216)"
        row_open[HUTANG_COLS["YANG_DIHUTANGI"] - 1] = "CV HB(101)"
        row_open[HUTANG_COLS["STATUS"] - 1] = "OPEN"

        row_paid = [""] * 9
        row_paid[HUTANG_COLS["NOMINAL"] - 1] = "300000"
        row_paid[HUTANG_COLS["YANG_HUTANG"] - 1] = "TX SBY(216)"
        row_paid[HUTANG_COLS["YANG_DIHUTANGI"] - 1] = "CV HB(101)"
        row_paid[HUTANG_COLS["STATUS"] - 1] = "PAID"

        self.rows = [["header"], row_open, row_paid]

    def get_all_values(self):
        return self.rows


class WalletBalanceConsistencyTests(unittest.TestCase):
    def test_paid_hutang_not_double_counted_in_real_saldo(self):
        fake_sheets = {
            "CV HB(101)": _FakeDompetSheet(pemasukan=1_000_000, pengeluaran=200_000),
            "TX SBY(216)": _FakeDompetSheet(pemasukan=0, pengeluaran=0),
            "TX BALI(087)": _FakeDompetSheet(pemasukan=0, pengeluaran=0),
        }

        with patch.object(sheets_helper, "DOMPET_SHEETS", list(fake_sheets.keys())), \
             patch("sheets_helper.get_dompet_sheet", side_effect=lambda d: fake_sheets[d]), \
             patch("sheets_helper.get_or_create_operational_sheet", return_value=_FakeOperationalSheet()), \
             patch("sheets_helper.get_or_create_hutang_sheet", return_value=_FakeHutangSheet()):
            balances = sheets_helper.get_wallet_balances()

        # CV HB: internal 800k - operational 100k = 700k (PAID is audit-only)
        self.assertEqual(balances["CV HB(101)"]["saldo"], 700_000)
        self.assertEqual(balances["CV HB(101)"]["utang_paid_in"], 300_000)
        # TX SBY borrower receives OPEN adjustment +300k
        self.assertEqual(balances["TX SBY(216)"]["saldo"], 300_000)

    def test_dashboard_summary_uses_same_wallet_balance_engine(self):
        wallet_balances = {
            "CV HB(101)": {"pemasukan": 10, "pengeluaran": 4, "operational_debit": 1, "utang_open_in": 0, "utang_paid_in": 0, "saldo": 5},
            "TX SBY(216)": {"pemasukan": 8, "pengeluaran": 3, "operational_debit": 0, "utang_open_in": 2, "utang_paid_in": 0, "saldo": 7},
            "TX BALI(087)": {"pemasukan": 2, "pengeluaran": 1, "operational_debit": 0, "utang_open_in": 0, "utang_paid_in": 0, "saldo": 1},
        }

        fake_dompet = _FakeDompetSheet(0, 0)

        with patch.object(sheets_helper, "DOMPET_SHEETS", list(wallet_balances.keys())), \
             patch("sheets_helper.get_dompet_sheet", return_value=fake_dompet), \
             patch("sheets_helper.get_or_create_operational_sheet", return_value=_FakeOperationalSheet()), \
             patch("sheets_helper.get_wallet_balances", return_value=wallet_balances):
            sheets_helper._dashboard_cache = None
            sheets_helper._dashboard_last_update = 0
            summary = sheets_helper.get_dashboard_summary()

        self.assertEqual(summary["dompet_summary"]["CV HB(101)"]["bal"], 5)
        self.assertEqual(summary["dompet_summary"]["TX SBY(216)"]["bal"], 7)
        self.assertEqual(summary["dompet_summary"]["TX BALI(087)"]["bal"], 1)
        self.assertEqual(summary["balance"], 13)


if __name__ == "__main__":
    unittest.main()
