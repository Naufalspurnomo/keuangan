import unittest
from unittest.mock import patch

from handlers.pending_handler import handle_pending_response


class PendingHandlerDebtTests(unittest.TestCase):
    def _pending_mismatch(self):
        return {
            "type": "project_dompet_mismatch",
            "transactions": [
                {
                    "keterangan": "Fee paw minggu ke juni projek Ronald pinjam HOLLA",
                    "jumlah": 552500,
                    "tipe": "Pengeluaran",
                    "nama_projek": "ronald (Start)",
                }
            ],
            "dompet_locked": "TX SBY(216)",
            "company_locked": "TEXTURIN-Surabaya",
            "dompet_input": "CV HB(101)",
            "company_input": "HOLLA",
            "debt_source_dompet": None,
            "raw_text": "Fee paw minggu ke juni, projek ronald, pinjam HOLLA",
            "sender_name": "Naufal",
            "source": "WhatsApp",
            "original_message_id": "msg-1",
            "event_id": "evt-1",
            "pending_key": "chat:user",
        }

    def test_project_mismatch_accepts_natural_debt_source_reply(self):
        with patch("handlers.pending_handler.set_pending_confirmation") as set_pending:
            result = handle_pending_response(
                "user",
                "chat@g.us",
                "pinjam ke dompet CV HB",
                self._pending_mismatch(),
                "Naufal",
            )

        self.assertFalse(result["completed"])
        data = set_pending.call_args.kwargs["data"]
        self.assertEqual(data["type"], "confirm_commit_project")
        self.assertEqual(data["dompet"], "TX SBY(216)")
        self.assertEqual(data["company"], "TEXTURIN-Surabaya")
        self.assertEqual(data["debt_source_dompet"], "CV HB(101)")
        self.assertIn("Sumber dana (utang): CV HB(101)", result["response"])

    def test_project_mismatch_asks_wallet_when_user_says_other_debt_wallet(self):
        with patch("handlers.pending_handler.set_pending_confirmation") as set_pending:
            result = handle_pending_response(
                "user",
                "chat@g.us",
                "pinjam dompet lain",
                self._pending_mismatch(),
                "Naufal",
            )

        set_pending.assert_not_called()
        self.assertFalse(result["completed"])
        self.assertIn("Dompet pemberi pinjaman", result["response"])


if __name__ == "__main__":
    unittest.main()
