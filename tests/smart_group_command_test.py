import unittest

from utils.groq_analyzer import (
    GroqContextAnalyzer,
    is_command_to_human,
    is_likely_future_plan,
)
from utils.parsers import is_explicit_catat_command, strip_explicit_catat_command


BANK_REVIEW_MESSAGE = """/catat
Tanggal: 01/06/2026
Tipe: DB
Nominal: 480,000.00
Keterangan: TRSF E-BANKING DB 0106/FTSCYWS95051 fee workshop 29-31 RIZKI AGUSTINA
Kategori sementara: Perlu Review
Catatan: projek workshop"""


class SmartGroupCommandTests(unittest.TestCase):
    def test_slash_catat_is_explicit_record_command(self):
        self.assertTrue(is_explicit_catat_command(BANK_REVIEW_MESSAGE))
        self.assertTrue(is_explicit_catat_command("+catat beli material 100rb"))
        self.assertTrue(is_explicit_catat_command("catat beli material 100rb"))

    def test_strip_slash_catat_preserves_payload(self):
        stripped = strip_explicit_catat_command(BANK_REVIEW_MESSAGE)

        self.assertTrue(stripped.startswith("Tanggal: 01/06/2026"))
        self.assertIn("Kategori sementara: Perlu Review", stripped)

    def test_perlu_review_metadata_is_not_future_plan(self):
        stripped = strip_explicit_catat_command(BANK_REVIEW_MESSAGE)

        self.assertFalse(is_likely_future_plan(stripped))

    def test_real_future_plan_still_detected(self):
        self.assertTrue(is_likely_future_plan("besok perlu bayar vendor 480rb"))

    def test_human_command_detection_uses_word_boundaries(self):
        self.assertFalse(is_command_to_human("bayar vendor 480rb projek workshop"))
        self.assertTrue(is_command_to_human("tolong bayarin vendor 480rb"))

    def test_safety_override_keeps_review_message_as_record_candidate(self):
        analyzer = GroqContextAnalyzer(None)
        stripped = strip_explicit_catat_command(BANK_REVIEW_MESSAGE)

        result = analyzer._apply_safety_overrides(
            {
                "should_respond": True,
                "intent": "RECORD_TRANSACTION",
                "confidence": 0.95,
                "category_scope": "PROJECT",
            },
            stripped,
            {"chat_type": "GROUP", "is_ambient": True},
            has_amount=True,
            is_future=is_likely_future_plan(stripped),
            is_human_cmd=is_command_to_human(stripped),
        )

        self.assertTrue(result["should_respond"])
        self.assertEqual(result["intent"], "RECORD_TRANSACTION")


if __name__ == "__main__":
    unittest.main()
