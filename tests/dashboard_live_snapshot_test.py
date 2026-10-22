import unittest
from datetime import datetime, timezone

from dashboard_api.live_snapshot import build_live_snapshot


class DashboardLiveSnapshotTests(unittest.TestCase):
    def test_projection_matches_frontend_snapshot_contract_and_eliminates_internal_debt(self):
        raw_rows = [
            {
                "tanggal": "2026-10-20",
                "jumlah": "1.500.000",
                "tipe": "Pemasukan",
                "keterangan": "Termin proyek",
                "company_sheet": "HOLLA",
                "nama_projek": "Villa A",
                "sheet_name": "CV HB(101)",
                "sheet_row": 9,
                "source_block": "pemasukan",
            },
            {
                "tanggal": "2026-10-21",
                "jumlah": "250.000",
                "tipe": "Pengeluaran",
                "keterangan": "Listrik kantor",
                "company_sheet": "Operasional Kantor",
                "nama_projek": "Operasional",
                "sheet_name": "Operasional Kantor",
                "sheet_row": 2,
                "source_block": "operasional",
            },
            {
                "tanggal": "2026-10-21",
                "jumlah": "700.000",
                "tipe": "Pengeluaran",
                "keterangan": "Hutang ke dompet TX SBY",
                "company_sheet": "HOLLA",
                "nama_projek": "Saldo Umum",
                "sheet_name": "CV HB(101)",
                "sheet_row": 11,
                "source_block": "pengeluaran",
                "internal_movement": True,
            },
            {
                "tanggal": "rusak",
                "jumlah": "l",
                "tipe": "Pengeluaran",
                "keterangan": "Baris manual rusak",
                "sheet_name": "TX SBY(216)",
                "sheet_row": 12,
                "source_block": "pengeluaran",
            },
        ]
        balances = {
            "CV HB(101)": {"saldo": 2_000_000},
            "TX SBY(216)": {"saldo": 3_000_000},
            "TX Bali(087)": {"saldo": 4_000_000},
        }
        debts = [
            {"source_key": "HUTANG:2", "date": "2026-10-20", "amount": 700_000, "notes": "Bridge", "borrower": "CV HB(101)", "lender": "TX SBY(216)", "status": "OPEN"},
            {"source_key": "HUTANG:3", "date": "2026-10-19", "amount": 400_000, "notes": "Lunas", "borrower": "TX Bali(087)", "lender": "CV HB(101)", "status": "PAID"},
        ]

        snapshot = build_live_snapshot(
            raw_rows,
            balances,
            debts,
            now=datetime(2026, 10, 21, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(snapshot["version"], "dashboard.snapshot.v1")
        self.assertEqual(snapshot["overview"]["metrics"]["cash_balance"], 9_000_000)
        self.assertEqual(snapshot["overview"]["metrics"]["operating_inflow"], 1_500_000)
        self.assertEqual(snapshot["overview"]["metrics"]["operating_outflow"], 250_000)
        self.assertEqual(snapshot["overview"]["metrics"]["open_internal_debt"], 700_000)
        self.assertEqual(snapshot["overview"]["counts"], {"valid_rows": 3, "invalid_rows": 1})
        self.assertEqual(snapshot["meta"]["data_through"], "2026-10-21")
        self.assertEqual(snapshot["meta"]["freshness"], "fresh")
        self.assertEqual(
            [row["source_key"] for row in snapshot["transactions"]],
            ["Operasional Kantor:operasional:2", "CV HB(101):pengeluaran:11", "CV HB(101):pemasukan:9"],
        )
        self.assertTrue(snapshot["transactions"][1]["internal_movement"])
        self.assertEqual(snapshot["project_summaries"], [
            {"name": "Villa A", "net_cashflow": 1_500_000},
            {"name": "Operasional", "net_cashflow": -250_000},
        ])
        self.assertEqual(snapshot["cash_trend"][-1]["balance"], 9_000_000)
        self.assertEqual(
            [row["source_key"] for row in snapshot["wallets"]],
            ["CV HB(101):wallet:summary", "TX SBY(216):wallet:summary", "TX Bali(087):wallet:summary"],
        )
        self.assertEqual(
            snapshot["overview"]["drilldowns"],
            {
                "cash_balance": "wallets",
                "operating_inflow": "transactions:external-income",
                "operating_outflow": "transactions:external-expense",
                "net_operating_cashflow": "transactions:external",
                "open_internal_debt": "debts:open",
                "project_cashflow": "transactions:projects",
            },
        )
        self.assertEqual(
            snapshot["quality_rows"],
            [{"source_key": "TX SBY(216):pengeluaran:12", "invalid_reason": "invalid_date_or_amount"}],
        )

    def test_stale_uses_latest_valid_transaction_not_request_time(self):
        snapshot = build_live_snapshot(
            [{"tanggal": "2026-09-01", "jumlah": "100000", "tipe": "Pemasukan", "sheet_name": "CV HB(101)", "sheet_row": 9, "source_block": "pemasukan"}],
            {"CV HB(101)": {"saldo": 100_000}},
            [],
            now=datetime(2026, 10, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["meta"]["freshness"], "stale")

    def test_hutang_settlement_markers_are_internal(self):
        from sheets_helper import is_internal_transfer_transaction

        fixtures = [
            {"message_id": "evt|UTANG", "keterangan": "bridge", "nama_projek": "Villa"},
            {"message_id": "evt|TERIMA", "keterangan": "bridge", "nama_projek": "Villa"},
            {"message_id": "HUTANG_PAID_12", "keterangan": "bridge", "nama_projek": "Villa"},
            {"message_id": "evt", "keterangan": "Terima pelunasan hutang dari TX SBY", "nama_projek": "Villa"},
            {"message_id": "evt", "keterangan": "Bayar hutang ke CV HB", "nama_projek": "Villa"},
        ]
        self.assertTrue(all(is_internal_transfer_transaction(row) for row in fixtures))
        self.assertFalse(is_internal_transfer_transaction({"message_id": "evt", "keterangan": "Bayar listrik kantor", "nama_projek": "Operasional"}))

    def test_amount_without_original_digit_is_invalid(self):
        snapshot = build_live_snapshot(
            [{"tanggal": "2026-10-20", "jumlah": "l", "tipe": "Pemasukan", "sheet_name": "CV HB(101)", "sheet_row": 9, "source_block": "pemasukan"}],
            {"CV HB(101)": {"saldo": 0}},
            [],
            now=datetime(2026, 10, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["overview"]["counts"], {"valid_rows": 0, "invalid_rows": 1})

    def test_duplicate_source_keys_fail_closed(self):
        row = {"tanggal": "2026-10-20", "jumlah": "100000", "tipe": "Pemasukan", "sheet_name": "CV HB(101)", "sheet_row": 9, "source_block": "pemasukan"}
        with self.assertRaisesRegex(ValueError, "duplicate source key"):
            build_live_snapshot([row, dict(row)], {"CV HB(101)": {"saldo": 100_000}}, [], now=datetime(2026, 10, 21, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
