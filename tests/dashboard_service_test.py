import unittest
from datetime import date, datetime, timezone

from dashboard_api.contracts import parse_filters
from dashboard_api.service import build_drilldown, build_overview


class DashboardMetricContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        self.filters = parse_filters({}, today=date(2026, 10, 21))

    def row(self, source_key, amount, transaction_type, **overrides):
        row = {
            "source_key": source_key,
            "transaction_date": date(2026, 10, 20),
            "amount": amount,
            "transaction_type": transaction_type,
            "company": "HOLLA",
            "wallet": "CV HB(101)",
            "project": "Project Alpha",
            "category": "Produksi",
            "source_block": "ledger",
            "source_wallet": None,
            "is_valid": True,
        }
        row.update(overrides)
        return row

    def test_overview_uses_exact_metric_terms_and_operating_totals(self):
        rows = [
            self.row("income", 10_000_000, "Pemasukan"),
            self.row("expense", 3_000_000, "Pengeluaran"),
        ]

        result = build_overview(rows, self.filters, self.now)

        self.assertEqual(
            list(result["metrics"]),
            [
                "cash_position",
                "inflow",
                "outflow",
                "net_movement",
                "open_internal_debt",
                "data_completeness",
            ],
        )
        self.assertEqual(result["metrics"]["cash_position"], 7_000_000)
        self.assertEqual(result["metrics"]["inflow"], 10_000_000)
        self.assertEqual(result["metrics"]["outflow"], 3_000_000)
        self.assertEqual(result["metrics"]["net_movement"], 7_000_000)
        self.assertEqual(result["metrics"]["data_completeness"], 100)

    def test_internal_transfer_pair_does_not_inflate_consolidated_totals(self):
        rows = [
            self.row("income", 8_000_000, "Pemasukan"),
            self.row("transfer-out", 2_000_000, "Transfer Internal", source_wallet="CV HB(101)"),
            self.row("transfer-in", 2_000_000, "Transfer Internal", wallet="TX SBY(216)", source_wallet="CV HB(101)"),
            self.row("expense", 1_000_000, "Pengeluaran"),
        ]

        result = build_overview(rows, self.filters, self.now)

        self.assertEqual(result["metrics"]["inflow"], 8_000_000)
        self.assertEqual(result["metrics"]["outflow"], 1_000_000)
        self.assertEqual(result["metrics"]["net_movement"], 7_000_000)

    def test_office_operation_with_source_wallet_remains_external_expense(self):
        rows = [
            self.row(
                "office-electricity",
                750_000,
                "Pengeluaran",
                company="Operasional Kantor",
                project="Operasional",
                source_block="operasional",
                source_wallet="CV HB(101)",
            ),
            self.row(
                "wallet-transfer",
                2_000_000,
                "Transfer Internal",
                source_block="transfer",
                source_wallet="CV HB(101)",
            ),
        ]

        result = build_overview(rows, self.filters, self.now)

        self.assertEqual(result["metrics"]["outflow"], 750_000)
        self.assertEqual(result["metrics"]["net_movement"], -750_000)

    def test_invalid_rows_only_reduce_completeness(self):
        rows = [
            self.row("good", 5_000_000, "Pemasukan"),
            self.row("bad-date", 99_000_000, "Pemasukan", transaction_date=None, is_valid=False),
            self.row("bad-amount", None, "Pengeluaran", is_valid=False),
        ]

        result = build_overview(rows, self.filters, self.now)

        self.assertEqual(result["metrics"]["inflow"], 5_000_000)
        self.assertEqual(result["metrics"]["outflow"], 0)
        self.assertEqual(result["metrics"]["data_completeness"], 33)
        self.assertEqual(result["completeness"]["invalid_rows"], 2)

    def test_mixed_filters_use_one_transaction_subset(self):
        filters = parse_filters(
            {
                "wallet": "TX SBY(216)",
                "company": "TEXTURIN-Surabaya",
                "project": "Hotel",
            },
            today=date(2026, 10, 21),
            allowed_projects=("Hotel",),
        )
        rows = [
            self.row("match", 4_000_000, "Pemasukan", wallet="TX SBY(216)", company="TEXTURIN-Surabaya", project="Hotel"),
            self.row("wrong-wallet", 9_000_000, "Pemasukan"),
            self.row("wrong-project", 7_000_000, "Pengeluaran", wallet="TX SBY(216)", company="TEXTURIN-Surabaya", project="Other"),
        ]

        result = build_overview(rows, filters, self.now)

        self.assertEqual(result["matching_source_keys"], ["match"])
        self.assertEqual(result["metrics"]["inflow"], 4_000_000)
        self.assertEqual(result["metrics"]["outflow"], 0)

    def test_open_internal_debt_and_metric_drilldown_are_explicit(self):
        rows = [
            self.row("open-debt", 2_500_000, "Hutang", source_block="hutang", status="OPEN"),
            self.row("paid-debt", 3_000_000, "Hutang", source_block="hutang", status="PAID"),
        ]

        result = build_overview(rows, self.filters, self.now)
        drilldown = build_drilldown(self.filters, "outflow")

        self.assertEqual(result["metrics"]["open_internal_debt"], 2_500_000)
        self.assertEqual(drilldown["view"], "transactions")
        self.assertEqual(drilldown["transaction_type"], "expense")
        self.assertEqual(drilldown["date_from"], "2026-10-01")
        self.assertEqual(drilldown["date_to"], "2026-10-21")


if __name__ == "__main__":
    unittest.main()
