import unittest
from datetime import date

from dashboard_api.contracts import DashboardContractError, parse_filters


class DashboardFilterContractTests(unittest.TestCase):
    def test_defaults_to_current_month_in_jakarta(self):
        filters = parse_filters({}, today=date(2026, 10, 21))

        self.assertEqual(filters.period, "this_month")
        self.assertEqual(filters.timezone, "Asia/Jakarta")
        self.assertEqual(filters.date_from, date(2026, 10, 1))
        self.assertEqual(filters.date_to, date(2026, 10, 21))

    def test_custom_dates_are_inclusive_and_serializable(self):
        filters = parse_filters(
            {
                "period": "custom",
                "date_from": "2026-09-01",
                "date_to": "2026-09-30",
                "wallet": "TX SBY(216)",
                "company": "TEXTURIN-Surabaya",
                "project": "Seragam Hotel",
            },
            today=date(2026, 10, 21),
            allowed_projects=("Seragam Hotel",),
        )

        self.assertEqual(filters.date_from, date(2026, 9, 1))
        self.assertEqual(filters.date_to, date(2026, 9, 30))
        self.assertEqual(filters.to_query()["date_to"], "2026-09-30")
        self.assertEqual(filters.wallet, "TX SBY(216)")

    def test_rejects_unknown_wallet_company_and_project(self):
        cases = (
            {"wallet": "UNKNOWN"},
            {"company": "UNKNOWN"},
            {"project": "UNKNOWN"},
        )
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(DashboardContractError):
                    parse_filters(args, today=date(2026, 10, 21), allowed_projects=("Known",))

    def test_rejects_invalid_range_and_unknown_keys(self):
        with self.assertRaises(DashboardContractError):
            parse_filters(
                {"period": "custom", "date_from": "2026-10-21", "date_to": "2026-10-01"},
                today=date(2026, 10, 21),
            )
        with self.assertRaises(DashboardContractError):
            parse_filters({"sql": "drop table"}, today=date(2026, 10, 21))


if __name__ == "__main__":
    unittest.main()
