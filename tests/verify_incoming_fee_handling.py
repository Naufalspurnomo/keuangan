import json
import unittest
from unittest.mock import Mock, patch

import ai_helper


def _fake_groq_response(payload: dict) -> Mock:
    mock_resp = Mock()
    mock_resp.choices = [Mock(message=Mock(content=json.dumps(payload, ensure_ascii=False)))]
    return mock_resp


class IncomingFeeHandlingTests(unittest.TestCase):
    def test_incoming_dp_drops_sender_fee(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-09",
                    "kategori": "Lain-lain",
                    "keterangan": "DP pengerjaan projek Daria",
                    "jumlah": 1766500,
                    "tipe": "Pemasukan",
                    "nama_projek": "Daria",
                    "company": "HOJJA",
                }
            ]
        }
        text = (
            "DP pengerjaan projek Daria\n"
            "Receipt/Struk content:\n"
            "Amount: IDR 1,764,000.00\n"
            "Fee: IDR 2,500.00\n"
            "Total: IDR 1,766,500.00"
        )

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        tx = txs[0]
        self.assertEqual(tx.get("tipe"), "Pemasukan")
        self.assertEqual(int(tx.get("jumlah", 0) or 0), 1764000)
        self.assertNotIn("biaya transfer", (tx.get("keterangan") or "").lower())

    def test_outgoing_transfer_keeps_fee(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-09",
                    "kategori": "Lain-lain",
                    "keterangan": "Transfer ke vendor projek Daria",
                    "jumlah": 1766500,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Daria",
                    "company": "HOJJA",
                }
            ]
        }
        text = (
            "transfer ke vendor projek Daria\n"
            "Receipt/Struk content:\n"
            "Amount: IDR 1,764,000.00\n"
            "Fee: IDR 2,500.00\n"
            "Total: IDR 1,766,500.00"
        )

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        fee_txs = [t for t in txs if (t.get("keterangan") or "").lower().startswith("biaya transfer")]
        self.assertEqual(len(fee_txs), 1)
        self.assertEqual(fee_txs[0].get("tipe"), "Pengeluaran")
        self.assertEqual(int(fee_txs[0].get("jumlah", 0) or 0), 2500)


if __name__ == "__main__":
    unittest.main()
