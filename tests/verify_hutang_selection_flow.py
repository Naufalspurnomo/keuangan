import unittest
from unittest.mock import patch

from handlers.pending_handler import handle_pending_response


class HutangSelectionFlowTests(unittest.TestCase):
    @patch("handlers.pending_handler.clear_pending_confirmation")
    @patch("handlers.pending_handler.invalidate_dashboard_cache")
    @patch("handlers.pending_handler.update_hutang_status_by_no")
    def test_valid_numeric_choice_marks_paid(self, mock_update, mock_invalidate, mock_clear):
        mock_update.return_value = {
            "no": "12",
            "keterangan": "Pinjam modal",
            "amount": 271000,
            "yang_hutang": "TX SBY(216)",
            "yang_dihutangi": "TX BALI(087)",
        }

        pending_data = {
            "type": "hutang_payment_selection",
            "candidates": [
                {
                    "no": "11",
                    "keterangan": "Pinjam A",
                    "amount": 180000,
                    "yang_hutang": "TX SBY(216)",
                    "yang_dihutangi": "TX BALI(087)",
                },
                {
                    "no": "12",
                    "keterangan": "Pinjam modal",
                    "amount": 271000,
                    "yang_hutang": "TX SBY(216)",
                    "yang_dihutangi": "TX BALI(087)",
                },
            ],
        }

        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="2",
            pending_data=pending_data,
            sender_name="User",
        )

        self.assertTrue(result.get("completed"))
        self.assertIn("Hutang #12 ditandai PAID", result.get("response", ""))
        mock_update.assert_called_once_with(12, "PAID")
        mock_invalidate.assert_called_once()
        mock_clear.assert_called_once()

    @patch("handlers.pending_handler.clear_pending_confirmation")
    def test_invalid_choice_keeps_pending(self, mock_clear):
        pending_data = {
            "type": "hutang_payment_selection",
            "candidates": [
                {"no": "3", "amount": 500000, "yang_hutang": "CV HB(101)", "yang_dihutangi": "TX BALI(087)", "keterangan": "A"},
                {"no": "4", "amount": 750000, "yang_hutang": "CV HB(101)", "yang_dihutangi": "TX BALI(087)", "keterangan": "B"},
            ],
        }

        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="9",
            pending_data=pending_data,
            sender_name="User",
        )

        self.assertFalse(result.get("completed"))
        self.assertIn("Balas angka 1-2", result.get("response", ""))
        mock_clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
