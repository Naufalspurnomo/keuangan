import unittest
from unittest.mock import MagicMock, patch

from dashboard_api import live_source
from services.ledger_store import build_source_key


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

    def test_relation_keys_use_the_canonical_builder_for_message_and_manual_rows(self):
        rows = [
            {
                "sheet_name": "CV HB(101)",
                "source_block": "pemasukan",
                "message_id": "dashboard:owner:request",
            },
            {
                "sheet_name": "TX SBY(216)",
                "source_block": "pengeluaran",
                "sheet_row": 77,
                "tanggal": "2026-11-10",
                "jumlah": 500_000,
                "keterangan": "Bahan proyek",
                "nama_projek": "Proyek Manual",
            },
        ]
        self.assertEqual(
            [live_source.build_source_key(row) for row in rows],
            [build_source_key(row) for row in rows],
        )

    @patch("psycopg.connect")
    def test_project_relation_enrichment_prefers_state_database_url(self, connect):
        source_key = "message:CV HB(101):project:dashboard:owner:request"
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(source_key, "00000000-0000-4000-8000-000000000001")]
        with patch.dict(
            live_source.os.environ,
            {"STATE_DATABASE_URL": "postgresql://state", "DATABASE_URL": "postgresql://fallback"},
            clear=True,
        ):
            result = live_source._read_project_ids([source_key])

        connect.assert_called_once_with("postgresql://state", autocommit=True)
        self.assertEqual(result[source_key], "00000000-0000-4000-8000-000000000001")

    def test_cache_ttl_is_bounded_for_ten_second_end_to_end_refresh(self):
        with patch.dict(live_source.os.environ, {"DASHBOARD_LIVE_CACHE_SECONDS": "999"}):
            self.assertEqual(live_source._cache_seconds(), 5)
        with patch.dict(live_source.os.environ, {"DASHBOARD_LIVE_CACHE_SECONDS": "0"}):
            self.assertEqual(live_source._cache_seconds(), 1)
        with patch.dict(live_source.os.environ, {"DASHBOARD_LIVE_CACHE_SECONDS": "invalid"}):
            self.assertEqual(live_source._cache_seconds(), 5)

    @patch("dashboard_api.live_source.threading.Thread")
    @patch("dashboard_api.live_source.time.monotonic", side_effect=[0.0, 0.0, 4.0, 6.0])
    @patch("dashboard_api.live_source.build_live_snapshot", return_value={"version": "first", "meta": {}})
    @patch("dashboard_api.live_source.get_wallet_balances", return_value={"CV HB(101)": {"saldo": 1}})
    @patch("dashboard_api.live_source.get_raw_rows_for_audit", return_value=[])
    @patch("dashboard_api.live_source._read_debts", return_value=[])
    @patch("dashboard_api.live_source._verify_required_worksheets")
    @patch("dashboard_api.live_source.get_spreadsheet", return_value=MagicMock())
    def test_expired_cache_returns_immediately_and_starts_background_refresh(
        self, _spreadsheet, _verify, _debts, raw_rows, _balances, projection, _monotonic, thread
    ):
        with patch.dict(live_source.os.environ, {"DASHBOARD_LIVE_CACHE_SECONDS": "5"}):
            first = live_source.load_live_snapshot()
            cached = live_source.load_live_snapshot()
            expired = live_source.load_live_snapshot()

        self.assertEqual(first["version"], "first")
        self.assertEqual(first["meta"]["source_status"], "live")
        self.assertEqual(cached["meta"]["source_status"], "live")
        self.assertEqual(expired["version"], "first")
        self.assertEqual(expired["meta"]["source_status"], "refreshing")
        self.assertEqual(raw_rows.call_count, 1)
        self.assertEqual(projection.call_count, 1)
        thread.assert_called_once_with(target=live_source._refresh_cache_in_background, daemon=True)
        thread.return_value.start.assert_called_once_with()

    @patch("dashboard_api.live_source.time.monotonic", side_effect=[10.0, 10.0])
    @patch("dashboard_api.live_source._read_fresh_snapshot", side_effect=RuntimeError("temporary source failure"))
    def test_background_failure_keeps_last_good_snapshot(self, _fresh, _monotonic):
        live_source._cached_snapshot = {"version": "dashboard.snapshot.v1", "meta": {}}
        live_source._cached_at = 1.0
        live_source._refreshing = True

        live_source._refresh_cache_in_background()

        self.assertEqual(live_source._cached_snapshot["version"], "dashboard.snapshot.v1")
        self.assertFalse(live_source._refreshing)
        self.assertEqual(live_source._last_refresh_failed_at, 10.0)

    @patch("dashboard_api.live_source.get_wallet_balances", side_effect=RuntimeError("wallet balance read was partial"))
    @patch("dashboard_api.live_source.get_raw_rows_for_audit", return_value=[])
    @patch("dashboard_api.live_source._verify_required_worksheets")
    @patch("dashboard_api.live_source.get_spreadsheet", return_value=MagicMock())
    def test_partial_balance_read_fails_closed(self, _spreadsheet, _verify, _raw_rows, _balances):
        with self.assertRaisesRegex(RuntimeError, "partial"):
            live_source.load_live_snapshot(force_refresh=True)


if __name__ == "__main__":
    unittest.main()
