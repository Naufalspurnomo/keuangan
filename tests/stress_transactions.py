import json
import unittest
from unittest.mock import Mock, patch

import ai_helper
import main
from config.constants import OPERATIONAL_KEYWORDS
from config.wallets import DOMPET_ALIASES, DOMPET_SHEETS
from utils.context_detector import AMBIGUOUS_KEYWORDS


def _fake_groq_response(payload: dict) -> Mock:
    mock_resp = Mock()
    content = json.dumps(payload, ensure_ascii=False)
    mock_resp.choices = [Mock(message=Mock(content=content))]
    return mock_resp


class WalletUpdateStressTests(unittest.TestCase):
    def test_wallet_update_context_detection(self):
        samples = [
            "isi saldo dompet tx bali 5jt",
            "topup dompet cv hb 2jt",
            "transfer ke dompet tx sby 1.5jt",
            "update saldo dompet 087 3jt",
            "tambah dompet holla 500rb",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(ai_helper._is_wallet_update_context(text))

    def test_wallet_update_forces_saldo_umum(self):
        payload = {
            "transactions": [
                {
                    "tanggal": "2026-02-01",
                    "kategori": "Lain-lain",
                    "keterangan": "Isi saldo",
                    "jumlah": 5000000,
                    "tipe": "Pemasukan",
                    "nama_projek": "Monas",
                    "company": "TEXTURIN-Bali",
                }
            ]
        }

        with patch.object(ai_helper, "call_groq_api", return_value=_fake_groq_response(payload)):
            txs = ai_helper.extract_from_text("isi saldo dompet tx bali 5jt", "User")

        self.assertTrue(txs)
        tx = txs[0]
        self.assertEqual(tx.get("nama_projek"), "Saldo Umum")
        self.assertEqual(tx.get("company"), "UMUM")
        self.assertEqual(tx.get("detected_dompet"), "TX BALI(087)")

    def test_wallet_alias_detection_stress(self):
        for alias, expected in DOMPET_ALIASES.items():
            text = f"saldo dompet {alias}"
            with self.subTest(alias=alias):
                detected = ai_helper.detect_wallet_from_text(text)
                self.assertEqual(detected, expected)


class ContextDetectionStressTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("services.project_service.get_existing_projects", return_value=[])
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_operational_keywords_classification(self):
        ambiguous = set(AMBIGUOUS_KEYWORDS.keys())
        operational = sorted(set(OPERATIONAL_KEYWORDS) - ambiguous)

        for kw in operational:
            text = f"bayar {kw} 100rb"
            with self.subTest(keyword=kw):
                res = main.detect_transaction_context(
                    text,
                    [{"nama_projek": ""}],
                    category_scope="UNKNOWN",
                )
                self.assertEqual(res.get("mode"), "OPERATIONAL")

    def test_ambiguous_keywords_classification(self):
        for kw in AMBIGUOUS_KEYWORDS.keys():
            text = f"bayar {kw} 100rb"
            with self.subTest(keyword=kw):
                res = main.detect_transaction_context(
                    text,
                    [{"nama_projek": ""}],
                    category_scope="UNKNOWN",
                )
                self.assertEqual(res.get("mode"), "AMBIGUOUS")

    def test_project_bias_when_project_word_exists(self):
        res = main.detect_transaction_context(
            "projek monas beli cat 1jt",
            [{"nama_projek": "Monas"}],
            category_scope="UNKNOWN",
        )
        self.assertEqual(res.get("mode"), "PROJECT")

    def test_operational_bias_when_kantor_word_exists(self):
        res = main.detect_transaction_context(
            "operasional kantor beli wifi 300rb",
            [{"nama_projek": ""}],
            category_scope="UNKNOWN",
        )
        self.assertEqual(res.get("mode"), "OPERATIONAL")

    def test_ambiguous_when_project_and_kantor(self):
        res = main.detect_transaction_context(
            "projek kantor 2jt",
            [{"nama_projek": ""}],
            category_scope="UNKNOWN",
        )
        self.assertEqual(res.get("mode"), "AMBIGUOUS")

    def test_project_overrides_ambiguous_when_name_exists(self):
        res = main.detect_transaction_context(
            "gaji tukang projek Monas 2jt",
            [{"nama_projek": "Monas"}],
            category_scope="UNKNOWN",
        )
        self.assertEqual(res.get("mode"), "PROJECT")


if __name__ == "__main__":
    unittest.main()
