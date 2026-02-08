import unittest
from unittest.mock import patch

from handlers.pending_handler import handle_pending_response


class PendingHandlerGuardsTest(unittest.TestCase):
    def test_category_scope_invalid_choice_stays_in_pending(self):
        pending_data = {
            "type": "category_scope",
            "transactions": [{"keterangan": "Biaya", "jumlah": 1000}],
            "raw_text": "biaya project",
            "original_message_id": "evt_1",
            "event_id": "evt_1",
        }

        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="3",
            pending_data=pending_data,
            sender_name="Tester",
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("completed"))
        self.assertIn("Balas 1", result.get("response", ""))

    def test_dompet_project_invalid_choice_stays_in_pending(self):
        pending_data = {
            "type": "dompet_selection_project",
            "transactions": [{"keterangan": "Biaya", "jumlah": 1000}],
            "raw_text": "biaya project",
            "original_message_id": "evt_2",
            "event_id": "evt_2",
        }

        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="9",
            pending_data=pending_data,
            sender_name="Tester",
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("completed"))
        self.assertIn("Pilih angka 1-5", result.get("response", ""))

    def test_unknown_pending_type_returns_guard_message(self):
        pending_data = {"type": "unknown_flow"}
        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="halo",
            pending_data=pending_data,
            sender_name="Tester",
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("completed"))
        self.assertIn("Ketik /cancel", result.get("response", ""))

    @patch("handlers.pending_handler.append_project_transaction")
    @patch("handlers.pending_handler.append_operational_transaction")
    def test_confirm_commit_operational_rejects_zero_amount(
        self,
        mock_append_operational,
        mock_append_project,
    ):
        pending_data = {
            "type": "confirm_commit_operational",
            "transactions": [{"keterangan": "Biaya", "jumlah": 0}],
            "source_wallet": "TEXTURIN-Surabaya",
            "category": "Lain Lain",
            "event_id": "evt_zero",
            "pending_key": "120363@g.us:6281",
        }

        result = handle_pending_response(
            user_id="6281",
            chat_id="120363@g.us",
            text="ya",
            pending_data=pending_data,
            sender_name="Tester",
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("completed"))
        self.assertIn("belum valid", result.get("response", "").lower())
        mock_append_operational.assert_not_called()
        mock_append_project.assert_not_called()


if __name__ == "__main__":
    unittest.main()
