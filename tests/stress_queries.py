import unittest
from unittest.mock import patch

from config.wallets import DOMPET_ALIASES, DOMPET_SHEETS
from handlers import query_handler as qh
from utils.parsers import should_respond_in_group


FIXTURE_DATA = [
    {
        "tanggal": "2026-01-31",
        "jumlah": 20000000,
        "tipe": "Pemasukan",
        "nama_projek": "Monas",
        "company_sheet": "TX BALI(087)",
        "keterangan": "DP Monas",
        "kategori": "Income",
    },
    {
        "tanggal": "2026-01-31",
        "jumlah": 2000000,
        "tipe": "Pengeluaran",
        "nama_projek": "Monas",
        "company_sheet": "TX BALI(087)",
        "keterangan": "Beli cat",
        "kategori": "Project Expense",
    },
    {
        "tanggal": "2026-01-31",
        "jumlah": 5000000,
        "tipe": "Pemasukan",
        "nama_projek": "Saldo Umum",
        "company_sheet": "TX BALI(087)",
        "keterangan": "Topup",
        "kategori": "Income",
    },
    {
        "tanggal": "2026-01-30",
        "jumlah": 7000000,
        "tipe": "Pemasukan",
        "nama_projek": "Rich Palace",
        "company_sheet": "CV HB (101)",
        "keterangan": "DP Rich Palace",
        "kategori": "Income",
    },
    {
        "tanggal": "2026-01-30",
        "jumlah": 2500000,
        "tipe": "Pengeluaran",
        "nama_projek": "Rich Palace",
        "company_sheet": "CV HB (101)",
        "keterangan": "Beli cat",
        "kategori": "Project Expense",
    },
    {
        "tanggal": "2026-01-30",
        "jumlah": 4000000,
        "tipe": "Pemasukan",
        "nama_projek": "Taman Cafe",
        "company_sheet": "TX SBY(216)",
        "keterangan": "DP Taman Cafe",
        "kategori": "Income",
    },
    {
        "tanggal": "2026-01-30",
        "jumlah": 300000,
        "tipe": "Pengeluaran",
        "nama_projek": "Taman Cafe",
        "company_sheet": "TX SBY(216)",
        "keterangan": "Beli bensin",
        "kategori": "Project Expense",
    },
    {
        "tanggal": "2026-01-30",
        "jumlah": 785000,
        "tipe": "Pengeluaran",
        "nama_projek": "Operasional",
        "company_sheet": "Operasional Kantor",
        "keterangan": "Cicilan motor [Sumber: TX BALI]",
        "kategori": "Operasional",
    },
]


def build_summary(data):
    total_pemasukan = sum(d["jumlah"] for d in data if d.get("tipe") == "Pemasukan")
    total_pengeluaran = sum(d["jumlah"] for d in data if d.get("tipe") == "Pengeluaran")

    by_projek = {}
    for d in data:
        proj = d.get("nama_projek", "").strip()
        if not proj:
            continue
        key = qh._normalize_text(proj)
        if key not in by_projek:
            by_projek[key] = {
                "name": proj,
                "income": 0,
                "expense": 0,
                "profit_loss": 0,
            }
        if d.get("tipe") == "Pemasukan":
            by_projek[key]["income"] += d["jumlah"]
        elif d.get("tipe") == "Pengeluaran":
            by_projek[key]["expense"] += d["jumlah"]

    for key in by_projek:
        by_projek[key]["profit_loss"] = (
            by_projek[key]["income"] - by_projek[key]["expense"]
        )

    return {
        "total_pemasukan": total_pemasukan,
        "total_pengeluaran": total_pengeluaran,
        "saldo": total_pemasukan - total_pengeluaran,
        "transaction_count": len(data),
        "by_projek": by_projek,
    }


def wallet_balances_fixture():
    return {
        "CV HB (101)": {
            "pemasukan": 7000000,
            "pengeluaran": 2500000,
            "saldo": 4500000,
            "operational_debit": 0,
        },
        "TX SBY(216)": {
            "pemasukan": 4000000,
            "pengeluaran": 300000,
            "saldo": 3700000,
            "operational_debit": 0,
        },
        "TX BALI(087)": {
            "pemasukan": 25000000,
            "pengeluaran": 2000000,
            "saldo": 25000000 - 2000000 - 785000,
            "operational_debit": 785000,
        },
    }


class QueryStressTests(unittest.TestCase):
    def setUp(self):
        self.summary = build_summary(FIXTURE_DATA)
        self.patcher_data = patch.object(qh, "get_all_data", return_value=FIXTURE_DATA)
        self.patcher_summary = patch.object(qh, "get_summary", return_value=self.summary)
        self.patcher_wallets = patch.object(qh, "get_wallet_balances", return_value=wallet_balances_fixture())
        self.patcher_data.start()
        self.patcher_summary.start()
        self.patcher_wallets.start()

    def tearDown(self):
        self.patcher_data.stop()
        self.patcher_summary.stop()
        self.patcher_wallets.stop()

    def test_wallet_query_bali_specific(self):
        query = "Bot cek dong, pemasukan dompet texturin bali"
        answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
        self.assertIn("TX BALI(087)", answer)
        self.assertNotIn("TX SBY(216)", answer)

    def test_project_profit(self):
        query = "Bot projek Monas itu untung apa rugi?"
        answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
        self.assertIn("Projek Monas", answer)
        self.assertIn("Laba/Rugi", answer)
        self.assertIn("UNTUNG", answer)

    def test_operational_query(self):
        query = "Bot cek operasional kantor bulan ini"
        answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
        self.assertIn("operasional", answer.lower())
        self.assertIn("Rp", answer)

    def test_general_summary_query(self):
        query = "Total pemasukan 30 hari terakhir berapa?"
        answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
        self.assertIn("Total pemasukan", answer)
        self.assertIn("Rp", answer)

    def test_wallet_alias_stress(self):
        for alias, expected_dompet in DOMPET_ALIASES.items():
            query = f"pemasukan dompet {alias}"
            with self.subTest(alias=alias):
                answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
                self.assertIn(expected_dompet, answer)

    def test_wallet_balance_stress(self):
        for alias, expected_dompet in DOMPET_ALIASES.items():
            query = f"saldo dompet {alias}"
            with self.subTest(alias=alias):
                answer = qh.handle_query_command(query, "user", "chat", raw_query=query)
                self.assertIn(expected_dompet, answer)


class GroupFilterStressTests(unittest.TestCase):
    def test_group_chitchat_ignored(self):
        should, _ = should_respond_in_group("lagi bahas kucing lucu", True)
        self.assertFalse(should)

    def test_group_transaction_detected(self):
        should, _ = should_respond_in_group("beli cat 500rb", True)
        self.assertTrue(should)

    def test_group_command_always(self):
        should, _ = should_respond_in_group("/status", True)
        self.assertTrue(should)


if __name__ == "__main__":
    unittest.main()
