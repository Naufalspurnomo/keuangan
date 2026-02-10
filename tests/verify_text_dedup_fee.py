import json
import unittest
from unittest.mock import Mock, patch

import ai_helper


def _fake_groq_response(payload: dict) -> Mock:
    mock_resp = Mock()
    mock_resp.choices = [Mock(message=Mock(content=json.dumps(payload, ensure_ascii=False)))]
    return mock_resp


class TextDedupFeeTests(unittest.TestCase):
    def test_dedup_generic_and_specific_fee_line(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Gaji",
                    "keterangan": "fee azen 500rb, projek lukisan nicholas",
                    "jumlah": 500000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Lukisan Nicholas",
                    "company": "HOJJA",
                },
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Gaji",
                    "keterangan": "Fee Azen",
                    "jumlah": 500000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Lukisan Nicholas",
                    "company": "HOJJA",
                },
            ]
        }
        text = "fee azen 500rb, projek lukisan nicholas"

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        self.assertEqual(int(txs[0].get("jumlah", 0) or 0), 500000)
        self.assertIn("fee", (txs[0].get("keterangan") or "").lower())

    def test_fee_person_project_is_not_transfer_fee(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Gaji",
                    "keterangan": "fee azen 500rb, projek lukisan nicholas",
                    "jumlah": 500000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Lukisan Nicholas",
                    "company": "HOJJA",
                }
            ]
        }
        text = "fee azen 500rb, projek lukisan nicholas"

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        self.assertEqual(int(txs[0].get("jumlah", 0) or 0), 500000)
        self.assertNotIn("biaya transfer", (txs[0].get("keterangan") or "").lower())


if __name__ == "__main__":
    unittest.main()
