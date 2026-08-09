import time
import unittest

from services import project_service
from services.project_service import normalize_project_input
from services.text_transaction_fallback import (
    build_text_transaction_fallback,
    extract_single_text_amount,
)


class TextTransactionFallbackTests(unittest.TestCase):
    def test_extracts_and_validates_operational_admin_line(self):
        text = "Biaya Admin Uyun 2.500, Operasional Kantor"

        self.assertEqual(extract_single_text_amount(text), 2500)
        transaction = build_text_transaction_fallback(text, 2500)

        self.assertEqual(transaction["jumlah"], 2500)
        self.assertEqual(transaction["keterangan"], "Biaya Admin Uyun")
        self.assertEqual(transaction["tipe"], "Pengeluaran")
        self.assertNotIn("needs_project", transaction)

    def test_project_label_is_removed_before_resolution(self):
        normalized = normalize_project_input("Project Hojja - Shyntia lukisan")

        self.assertEqual(normalized, "Hojja - Shyntia lukisan")
        self.assertNotIn("Project Hojja", normalized)

    def test_single_substring_project_is_still_ambiguous(self):
        old_cache = {
            "names": set(project_service._project_cache.get("names", set())),
            "records": list(project_service._project_cache.get("records", [])),
            "last_updated": project_service._project_cache.get("last_updated", 0),
            "ttl": project_service._project_cache.get("ttl", 300),
        }
        try:
            project_service._project_cache.update({
                "names": {"Laundry Herman"},
                "records": [],
                "last_updated": time.time(),
            })
            result = project_service.resolve_project_name("Laundry")
        finally:
            project_service._project_cache.update(old_cache)

        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["final_name"], "Laundry Herman")


    def test_long_explicit_phrase_does_not_match_short_project(self):
        old_cache = {
            "names": set(project_service._project_cache.get("names", set())),
            "records": list(project_service._project_cache.get("records", [])),
            "last_updated": project_service._project_cache.get("last_updated", 0),
            "ttl": project_service._project_cache.get("ttl", 300),
        }
        try:
            project_service._project_cache.update({
                "names": {"Laundry"},
                "records": [],
                "last_updated": time.time(),
            })
            result = project_service.resolve_project_name("Lukisan Laundry Mrs Shyntia")
        finally:
            project_service._project_cache.update(old_cache)

        self.assertEqual(result["status"], "NEW")
if __name__ == "__main__":
    unittest.main()
