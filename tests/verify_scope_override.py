import unittest
from unittest.mock import patch

import main


class ScopeOverrideTests(unittest.TestCase):
    @patch("services.project_service.get_existing_projects", return_value=[])
    def test_ambiguous_scope_with_project_keyword_prefers_project(self, _mock_projects):
        result = main.detect_transaction_context(
            "fee sugeng project avant",
            [{"nama_projek": ""}],
            category_scope="AMBIGUOUS",
        )
        self.assertEqual(result.get("mode"), "PROJECT")

    @patch("services.project_service.get_existing_projects", return_value=[])
    def test_ambiguous_scope_with_operational_keyword_prefers_operational(self, _mock_projects):
        result = main.detect_transaction_context(
            "fee admin kantor",
            [{"nama_projek": ""}],
            category_scope="AMBIGUOUS",
        )
        self.assertEqual(result.get("mode"), "OPERATIONAL")


if __name__ == "__main__":
    unittest.main()
