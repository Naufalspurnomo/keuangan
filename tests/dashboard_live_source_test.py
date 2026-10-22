import unittest
from unittest.mock import MagicMock, patch

from dashboard_api import live_source


class DashboardLiveSourceTests(unittest.TestCase):
    def setUp(self):
        live_source.reset_live_snapshot_cache_for_tests()

    def tearDown(self):
        live_source.reset_live_snapshot_cache_for_tests()

    def test_missing_required_sheet_fails_without_creating_anything(self):
        spreadsheet = MagicMock()
        spreadsheet.worksheet.side_effect = RuntimeError("missing")
        with self.assertRaisesRegex(RuntimeError, "required dashboard worksheets unavailable"):
            live_source._verify_required_worksheets(spreadsheet)
        self.assertEqual(spreadsheet.add_worksheet.call_count, 0)

    @patch("dashboard_api.live_source.build_live_snapshot", return_value={"version": "dashboard.snapshot.v1"})
    @patch("dashboard_api.live_source.get_wallet_balances", return_value={"CV HB(101)": {"saldo": 1}})
    @patch("dashboard_api.live_source.get_raw_rows_for_audit", return_value=[])
    @patch("dashboard_api.live_source._read_debts", return_value=[])
    @patch("dashboard_api.live_source._verify_required_worksheets")
    @patch("dashboard_api.live_source.get_spreadsheet", return_value=MagicMock())
    def test_cache_reuses_one_projection(self, _spreadsheet, _verify, _debts, raw_rows, balances, projection):
        first = live_source.load_live_snapshot()
        second = live_source.load_live_snapshot()
        self.assertEqual(first, second)
        self.assertEqual(raw_rows.call_count, 1)
        self.assertEqual(balances.call_count, 1)
        self.assertEqual(projection.call_count, 1)
        balances.assert_called_once_with(force_refresh=False, strict=True, spreadsheet=_spreadsheet.return_value)

    @patch("dashboard_api.live_source.get_wallet_balances", side_effect=RuntimeError("wallet balance read was partial"))
    @patch("dashboard_api.live_source.get_raw_rows_for_audit", return_value=[])
    @patch("dashboard_api.live_source._verify_required_worksheets")
    @patch("dashboard_api.live_source.get_spreadsheet", return_value=MagicMock())
    def test_partial_balance_read_fails_closed(self, _spreadsheet, _verify, _raw_rows, _balances):
        with self.assertRaisesRegex(RuntimeError, "partial"):
            live_source.load_live_snapshot(force_refresh=True)


if __name__ == "__main__":
    unittest.main()
