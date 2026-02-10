import unittest
from unittest.mock import patch

from handlers import query_handler


class QueryHandlerSpecificityTests(unittest.TestCase):
    @patch("handlers.query_handler._handle_wallet_query", return_value="WALLET")
    @patch("handlers.query_handler._handle_project_query", return_value="PROJECT")
    @patch("handlers.query_handler.resolve_dompet_from_text", return_value="TX BALI(087)")
    def test_project_keyword_beats_dompet_alias(
        self,
        _mock_dompet,
        mock_project,
        mock_wallet,
    ):
        result = query_handler.handle_query_command(
            "Bot pengeluaran projek Vadim Bali berapa?",
            user_id="u1",
            chat_id="c1",
        )

        self.assertEqual(result, "PROJECT")
        mock_project.assert_called_once()
        mock_wallet.assert_not_called()

    @patch("handlers.query_handler._handle_hutang_query", return_value="HUTANG")
    @patch("handlers.query_handler.resolve_dompet_from_text", return_value="CV HB(101)")
    def test_hutang_query_for_dompet_routes_to_hutang_handler(self, _mock_dompet, mock_hutang):
        result = query_handler.handle_query_command(
            "Bot utang CV HB berapa?",
            user_id="u1",
            chat_id="c1",
        )

        self.assertEqual(result, "HUTANG")
        mock_hutang.assert_called_once()

    @patch("handlers.query_handler.find_open_hutang")
    def test_hutang_dompet_summary_includes_borrow_and_lender_totals(self, mock_find_open_hutang):
        # side effects: first call borrower rows, second call lender rows
        mock_find_open_hutang.side_effect = [
            [{"jumlah": 100000}, {"jumlah": 200000}],
            [{"jumlah": 50000}],
        ]

        result = query_handler._handle_hutang_query(
            norm_text="utang cv hb",
            days=30,
            period_label="30 hari terakhir",
            dompet="CV HB(101)",
        )

        self.assertIn("Masih berutang", result)
        self.assertIn("Rp 300.000", result)
        self.assertIn("Piutang belum lunas", result)
        self.assertIn("Rp 50.000", result)


if __name__ == "__main__":
    unittest.main()
