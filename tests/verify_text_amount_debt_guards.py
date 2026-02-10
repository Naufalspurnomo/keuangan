import json
import unittest
from unittest.mock import Mock, patch

import ai_helper


def _fake_groq_response(payload: dict) -> Mock:
    mock_resp = Mock()
    mock_resp.choices = [Mock(message=Mock(content=json.dumps(payload, ensure_ascii=False)))]
    return mock_resp


class TextAmountDebtGuardsTests(unittest.TestCase):
    def test_fixes_rb_scale_error_and_drops_debt_artifact_duplicate(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Lain-lain",
                    "keterangan": "Bayar sugeng",
                    "jumlah": 250000000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Vadim",
                    "company": "TEXTURIN-Bali",
                },
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Lain-lain",
                    "keterangan": "Pinjam TX SBY",
                    "jumlah": 250000000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Vadim",
                    "company": "TEXTURIN-Bali",
                },
            ]
        }
        text = "Bayar sugeng 250rb , project vadim, pinjam TX SBY"

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        self.assertEqual(int(txs[0].get("jumlah", 0) or 0), 250000)
        self.assertIn("bayar", (txs[0].get("keterangan", "") or "").lower())

    def test_single_debt_line_is_kept(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-10",
                    "kategori": "Lain-lain",
                    "keterangan": "Pinjam TX SBY",
                    "jumlah": 250000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Vadim",
                    "company": "TEXTURIN-Bali",
                }
            ]
        }
        text = "Pinjam TX SBY 250rb project vadim"

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        self.assertEqual(int(txs[0].get("jumlah", 0) or 0), 250000)
        self.assertIn("pinjam", (txs[0].get("keterangan", "") or "").lower())


if __name__ == "__main__":
    unittest.main()
