import unittest
from unittest.mock import patch

from handlers import pending_handler


class PendingProjectNewFlowTests(unittest.TestCase):
    @patch("handlers.pending_handler._continue_project_after_name")
    def test_project_new_confirm_combined_branch_no_name_error(self, mock_continue):
        mock_continue.return_value = {"response": "ok", "completed": False}

        pending_data = {
            "type": "project_new_confirm",
            "dompet_sheet": "CV HB(101)",
            "company": "HOLLA",
            "transactions": [
                {"jumlah": 2500000, "keterangan": "Beli cat", "tipe": "Pengeluaran"}
            ],
            "new_project_first_expense": True,
            "source": "WhatsApp",
            "original_message_id": "evt-1",
            "event_id": "evt-1",
        }

        result = pending_handler.handle_pending_response(
            user_id="user-1",
            chat_id="123@g.us",
            text="1",
            pending_data=pending_data,
            sender_name="Tester",
        )

        self.assertEqual(result, {"response": "ok", "completed": False})
        mock_continue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
