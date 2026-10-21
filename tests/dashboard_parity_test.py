import unittest

from dashboard_api.parity import compare_aggregates, compare_drilldown


class DashboardParityTests(unittest.TestCase):
    def test_matching_wallet_type_month_aggregates_pass(self):
        source = [
            {"wallet": "BCA(056)", "transaction_type": "Pemasukan", "month": "2026-10", "amount": 100_000},
            {"wallet": "BCA(056)", "transaction_type": "Pengeluaran", "month": "2026-10", "amount": 40_000},
        ]
        mirror = list(reversed(source))
        result = compare_aggregates(source, mirror)
        self.assertTrue(result["ok"])
        self.assertEqual(result["difference_idr"], 0)
        self.assertEqual(result["mismatches"], [])

    def test_any_difference_fails_with_exact_dimension(self):
        source = [{"wallet": "BCA(056)", "transaction_type": "Pemasukan", "month": "2026-10", "amount": 100_000}]
        mirror = [{"wallet": "BCA(056)", "transaction_type": "Pemasukan", "month": "2026-10", "amount": 99_000}]
        result = compare_aggregates(source, mirror)
        self.assertFalse(result["ok"])
        self.assertEqual(result["difference_idr"], -1_000)
        self.assertEqual(result["mismatches"][0]["wallet"], "BCA(056)")

    def test_drilldown_requires_exact_source_keys_and_total(self):
        source = [{"source_key": "a", "amount": 40_000}, {"source_key": "b", "amount": 60_000}]
        self.assertTrue(compare_drilldown(source, list(reversed(source)))["ok"])
        result = compare_drilldown(source, [{"source_key": "a", "amount": 40_000}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_source_keys"], ["b"])
        self.assertEqual(result["difference_idr"], -60_000)


if __name__ == "__main__":
    unittest.main()
