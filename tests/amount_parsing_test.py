import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault("GROQ_API_KEY", "test-key")

from ai_helper import (
    _dedupe_text_level_duplicates,
    _extract_labeled_amount_from_text,
    extract_from_text,
)
from security import validate_transaction_data
from services.transaction_queue import normalize_amount
from services.text_transaction_fallback import build_text_transaction_fallback
from utils.amounts import parse_money_token
from utils.parsers import parse_revision_amount


class AmountParsingTests(unittest.TestCase):
    def test_parse_money_token_supports_bank_decimal_format(self):
        self.assertEqual(parse_money_token("480,000.00"), 480000)
        self.assertEqual(parse_money_token("480.000,00"), 480000)
        self.assertEqual(parse_money_token("10.984.668"), 10984668)
        self.assertEqual(parse_money_token(480000.0), 480000)
        self.assertEqual(parse_money_token("480000.0"), 480000)
        self.assertEqual(parse_revision_amount("480,000.00"), 480000)
        self.assertEqual(parse_revision_amount("480.000,00"), 480000)
        self.assertEqual(normalize_amount("480,000.00"), 480000)

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
        self.assertEqual(_extract_labeled_amount_from_text("Nominal: 100rb"), 100000)

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

    def test_extract_from_text_skips_non_object_transactions(self):
        class FakeMessage:
            content = '{"transactions":["malformed", null, 123]}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        with patch("ai_helper.call_groq_api", return_value=FakeResponse()), \
             patch("services.finance_agent._safe_sheet_context", return_value={
                 "wallets": [],
                 "known_projects": ["workshop"],
                 "sheet_context_available": True,
             }):
            transactions = extract_from_text("beli alat 100rb projek workshop", "Naufal")

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["jumlah"], 100000)
        self.assertEqual(transactions[0]["nama_projek"], "workshop")

    def test_extract_from_text_uses_grounded_fallback_when_groq_is_unavailable(self):
        with patch("ai_helper.call_groq_api", side_effect=RuntimeError("provider down")):
            transactions = extract_from_text(
                "bayar alat 100rb projek workshop",
                "Naufal",
            )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["jumlah"], 100000)
        self.assertEqual(transactions[0]["nama_projek"], "workshop")

    def test_extract_from_text_rejects_partial_over_limit_payload(self):
        rows = [
            {
                "tanggal": "2026-06-01",
                "tipe": "Pengeluaran",
                "jumlah": 100000 + index,
                "kategori": "Lain-lain",
                "keterangan": f"item {index}",
                "nama_projek": "workshop",
            }
            for index in range(11)
        ]

        class FakeMessage:
            content = json.dumps({"transactions": rows})

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        source = "catat " + " ".join(f"{100 + index}rb" for index in range(11))
        with patch("ai_helper.call_groq_api", return_value=FakeResponse()), \
             patch("services.finance_agent._safe_sheet_context", return_value={
                 "wallets": [],
                 "known_projects": ["workshop"],
                 "sheet_context_available": True,
             }):
            transactions = extract_from_text(source, "Naufal")

        self.assertEqual(transactions, [])

    def test_text_dedupe_preserves_repeated_identical_payments(self):
        tx = {
            "tanggal": "2026-06-01",
            "tipe": "Pengeluaran",
            "jumlah": 100000,
            "nama_projek": "workshop",
            "keterangan": "beli semen",
        }

        result = _dedupe_text_level_duplicates([dict(tx), dict(tx)], "beli semen 100rb projek workshop")

        self.assertEqual(len(result), 2)

    def test_grounded_fallback_rejects_invalid_explicit_date(self):
        self.assertEqual(
            build_text_transaction_fallback(
                "Tanggal: 2026-02-31 bayar alat 100rb projek workshop",
                100000,
            ),
            {},
        )

    def test_grounded_fallback_preserves_valid_explicit_date(self):
        result = build_text_transaction_fallback(
            "Tanggal: 01/06/2026 bayar alat 100rb projek workshop",
            100000,
        )
        self.assertEqual(result["tanggal"], "2026-06-01")


if __name__ == "__main__":
    unittest.main()
