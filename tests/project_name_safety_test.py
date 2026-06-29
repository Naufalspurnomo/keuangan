import unittest

from ai_helper import extract_project_from_description, is_semantically_valid_project_name
from services.project_service import resolve_project_name


class ProjectNameSafetyTests(unittest.TestCase):
    def test_receipt_status_words_are_invalid_project_names(self):
        for candidate in ["Successful", "success", "berhasil", "status"]:
            with self.subTest(candidate=candidate):
                self.assertFalse(is_semantically_valid_project_name(candidate))
                result = resolve_project_name(candidate)
                self.assertEqual(result["status"], "INVALID")

    def test_transfer_successful_description_does_not_become_project(self):
        self.assertEqual(extract_project_from_description("Transfer Successful"), "")


if __name__ == "__main__":
    unittest.main()
