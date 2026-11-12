import unittest
from unittest.mock import patch

from flask import Flask

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

    def test_operational_commit_does_not_claim_success_without_save_ack(self):
        pending = {
            "type": "confirm_commit_operational",
            "transactions": [{
                "jumlah": 450000,
                "keterangan": "gaji tukang",
                "tipe": "Pengeluaran",
            }],
            "source_wallet": "CV HB(101)",
            "category": "Gaji",
            "source": "WhatsApp",
            "event_id": "evt-operational-fail",
            "pending_key": "chat:user",
        }

        with patch(
            "handlers.pending_handler.append_operational_transaction",
            return_value={"success": False, "error": "sheet rejected"},
        ), patch("handlers.pending_handler.clear_pending_confirmation") as clear_confirmation, \
             patch("handlers.pending_handler.clear_pending_transaction") as clear_pending:
            result = handle_pending_response(
                "user",
                "chat@g.us",
                "1",
                pending,
                "Naufal",
            )

        self.assertFalse(result["completed"])
        self.assertIn("belum dikonfirmasi tersimpan", result["response"])
        clear_confirmation.assert_not_called()
        clear_pending.assert_not_called()

    def test_project_confirmed_canonical_path_never_calls_sheet_helpers(self):
        pending = {
            "type": "confirm_commit_project",
            "transactions": [{
                "jumlah": 450000,
                "keterangan": "material proyek",
                "tipe": "Pengeluaran",
                "tanggal": "2026-11-12",
                "nama_projek": "Project Alpha",
            }],
            "dompet": "CV HB(101)",
            "company": "HOLLA",
            "source": "WhatsApp",
            "event_id": "evt-canonical-project",
            "pending_key": "chat:user",
        }
        app = Flask(__name__)
        with app.app_context(), patch(
            "handlers.pending_handler._canonical_pending_batch",
            return_value={"authority": "postgresql", "status": "committed"},
        ) as canonical, patch(
            "handlers.pending_handler.append_project_transaction"
        ) as append_project, patch(
            "handlers.pending_handler.append_hutang_entry"
        ) as append_debt:
            result = handle_pending_response(
                "6281212042709",
                "chat@g.us",
                "1",
                pending,
                "Naufal",
            )

        self.assertTrue(result["completed"])
        canonical.assert_called_once()
        append_project.assert_not_called()
        append_debt.assert_not_called()

    def test_canonical_quarantine_keeps_pending_and_never_falls_back(self):
        pending = {
            "type": "confirm_commit_project",
            "transactions": [{
                "jumlah": 450000,
                "keterangan": "material proyek",
                "tipe": "Pengeluaran",
                "tanggal": "2026-11-12",
                "nama_projek": "Unknown Project",
            }],
            "dompet": "CV HB(101)",
            "company": "HOLLA",
            "source": "WhatsApp",
            "event_id": "evt-canonical-quarantine",
            "pending_key": "chat:user",
        }
        app = Flask(__name__)
        with app.app_context(), patch(
            "handlers.pending_handler._canonical_pending_batch",
            return_value={
                "authority": "postgresql",
                "status": "quarantined",
                "reason_code": "unmapped_project",
                "quarantine_id": "00000000-0000-4000-8000-000000000702",
            },
        ), patch(
            "handlers.pending_handler.append_project_transaction"
        ) as append_project, patch(
            "handlers.pending_handler.clear_pending_confirmation"
        ) as clear_confirmation:
            result = handle_pending_response(
                "6281212042709",
                "chat@g.us",
                "1",
                pending,
                "Naufal",
            )

        self.assertFalse(result["completed"])
        self.assertIn("00000000-0000-4000-8000-000000000702", result["response"])
        append_project.assert_not_called()
        clear_confirmation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
