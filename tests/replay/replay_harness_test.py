"""
replay_harness_test.py - unittest gate untuk replay harness.

Mengikuti konvensi tests/ lain (unittest). Memastikan:
- semua case berlabel jalan tanpa error,
- tidak ada hasil "unexpected" (regresi nyata atau known_gap yang sudah basi),
- regression cases kunci (HOLLA/CV HB sebagai lender, "Successful" bukan project)
  benar-benar lolos.
"""

import os
import unittest

from tests.replay.runner import (
    DEFAULT_FIXTURES,
    load_fixtures,
    resolve_finance_message,
    run_all,
    summarize,
)


class ReplayHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_fixtures(DEFAULT_FIXTURES)
        cls.checked_fields = (
            cls.fixtures.get("_schema", {}).get("checked_fields")
            or ["project", "main_wallet", "debt_source", "company", "needs_confirmation"]
        )
        cls.results = run_all(cls.fixtures)
        cls.by_id = {r.case_id: r for r in cls.results}

    def test_fixtures_file_exists(self):
        self.assertTrue(os.path.exists(DEFAULT_FIXTURES))
        self.assertTrue(self.fixtures.get("cases"), "fixtures must contain cases")

    def test_no_unexpected_results(self):
        unexpected = [r.case_id for r in self.results if r.is_unexpected]
        self.assertEqual(
            unexpected, [],
            f"Unexpected replay results (regresi atau known_gap basi): {unexpected}",
        )

    def test_regression_debt_lender_not_main_wallet(self):
        r = self.by_id["debt-holla-funds-vadim-fee"]
        self.assertTrue(r.passed, f"HOLLA-as-lender regression failed: {r.mismatches}")

    def test_regression_ocr_status_not_project(self):
        r = self.by_id["ocr-successful-not-project"]
        self.assertTrue(r.passed, f"'Successful' leaked as project: {r.mismatches}")

    def test_blocklist_blocks_status_words_directly(self):
        # Unit-level guard independent of fixtures.
        decision = resolve_finance_message(
            "bayar project Successful dari TX SBY",
            ocr_text="Transfer Successful",
        )
        self.assertIsNone(decision.project)
        self.assertTrue(decision.needs_confirmation)

    def test_overall_accuracy_reported(self):
        summary = summarize(self.results, self.checked_fields)
        # Sanity: harness measures something and reports a ratio in [0,1].
        self.assertGreaterEqual(summary["case_accuracy"], 0.0)
        self.assertLessEqual(summary["case_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
