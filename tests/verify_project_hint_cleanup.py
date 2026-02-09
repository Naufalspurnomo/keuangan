import json
import unittest
from unittest.mock import Mock, patch

import ai_helper


def _fake_groq_response(payload: dict) -> Mock:
    mock_resp = Mock()
    mock_resp.choices = [Mock(message=Mock(content=json.dumps(payload, ensure_ascii=False)))]
    return mock_resp


class ProjectHintCleanupTests(unittest.TestCase):
    def test_debt_phrase_not_included_in_project_name(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-09",
                    "kategori": "Lain-lain",
                    "keterangan": "Beli cat projek daria utang dari tx bali",
                    "jumlah": 350000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "daria utang",
                    "company": "HOJJA",
                }
            ]
        }

        text = "Beli cat projek daria utang dari tx bali 350rb"
        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text(text, "User")

        self.assertEqual(len(txs), 1)
        self.assertEqual((txs[0].get("nama_projek") or "").lower(), "daria")


if __name__ == "__main__":
    unittest.main()
