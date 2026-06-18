import os
import unittest
from unittest.mock import patch

os.environ.setdefault("GROQ_API_KEY", "test-key")

from ai_helper import _extract_labeled_amount_from_text, extract_from_text
from security import validate_transaction_data
from utils.amounts import parse_money_token


class AmountParsingTests(unittest.TestCase):
    def test_parse_money_token_supports_bank_decimal_format(self):
        self.assertEqual(parse_money_token("480,000.00"), 480000)
        self.assertEqual(parse_money_token("480.000,00"), 480000)
        self.assertEqual(parse_money_token("10.984.668"), 10984668)
        self.assertEqual(parse_money_token(480000.0), 480000)
        self.assertEqual(parse_money_token("480000.0"), 480000)

    def test_validate_transaction_data_preserves_bank_decimal_scale(self):
        ok, error, tx = validate_transaction_data({
            "tanggal": "2026-06-01",
            "tipe": "Pengeluaran",
            "jumlah": "480,000.00",
            "kategori": "Lain-lain",
            "keterangan": "fee workshop",
        })

        self.assertTrue(ok, error)
        self.assertEqual(tx["jumlah"], 480000)

    def test_extract_labeled_amount_from_text(self):
        text = """Tanggal: 01/06/2026
Tipe: DB
Nominal: 480,000.00
Keterangan: TRSF E-BANKING"""

        self.assertEqual(_extract_labeled_amount_from_text(text), 480000)

    def test_extract_from_text_restores_zero_ai_amount_from_nominal_label(self):
        class FakeMessage:
            content = """{"transactions":[{"tanggal":"2026-06-01","tipe":"Pengeluaran","jumlah":0,"kategori":"Lain-lain","keterangan":"fee workshop","nama_projek":"workshop"}]}"""

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        text = """/catat
Tanggal: 01/06/2026
Tipe: DB
Nominal: 480,000.00
Keterangan: TRSF E-BANKING DB 0106/FTSCYWS95051 fee workshop 29-31 RIZKI AGUSTINA
Catatan: projek workshop"""

        with patch("ai_helper.call_groq_api", return_value=FakeResponse()):
            transactions = extract_from_text(text, "Naufal")

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["jumlah"], 480000)


if __name__ == "__main__":
    unittest.main()
