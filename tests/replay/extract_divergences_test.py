"""Tests for the shadow-log divergence extractor."""

import unittest

from tests.replay.extract_divergences import (
    parse_divergence_line,
    divergence_to_draft_case,
)


# Mirrors the exact format emitted by main._shadow_compare_narrow_resolver.
SAMPLE_DIVERGENCE = (
    "2026-06-29 16:00:00 [INFO] keuangan: NARROW_SHADOW divergence | "
    "conf=0.7 needs_conf=True | "
    "main_wallet: resolver=None pipeline='CV HB(101)' | "
    "debt_source: resolver='CV HB(101)' pipeline=None"
)
SAMPLE_MATCH = "2026-06-29 16:00:00 [INFO] keuangan: NARROW_SHADOW match | conf=0.93"


class ExtractDivergencesTests(unittest.TestCase):
    def test_match_line_is_ignored(self):
        self.assertIsNone(parse_divergence_line(SAMPLE_MATCH))

    def test_unrelated_line_is_ignored(self):
        self.assertIsNone(parse_divergence_line("2026 [INFO] something else entirely"))

    def test_parses_confidence_and_needs(self):
        parsed = parse_divergence_line(SAMPLE_DIVERGENCE)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["confidence"], 0.7)
        self.assertTrue(parsed["needs_confirmation"])

    def test_parses_fields_resolver_vs_pipeline(self):
        parsed = parse_divergence_line(SAMPLE_DIVERGENCE)
        fields = parsed["fields"]
        self.assertEqual(fields["main_wallet"]["resolver"], None)
        self.assertEqual(fields["main_wallet"]["pipeline"], "CV HB(101)")
        self.assertEqual(fields["debt_source"]["resolver"], "CV HB(101)")
        self.assertEqual(fields["debt_source"]["pipeline"], None)

    def test_draft_case_has_required_keys(self):
        parsed = parse_divergence_line(SAMPLE_DIVERGENCE)
        case = divergence_to_draft_case(parsed, idx=1)
        self.assertEqual(case["id"], "shadow-divergence-1")
        self.assertTrue(case["needs_review"])
        self.assertIn("expect", case)
        # Draft seeds expect.main_wallet from pipeline value (human will verify).
        self.assertEqual(case["expect"]["main_wallet"], "CV HB(101)")
        self.assertIn("_observed", case)

    def test_project_list_form_is_parsed(self):
        line = (
            "NARROW_SHADOW divergence | conf=0.6 needs_conf=False | "
            "project: resolver='vadim' pipeline=['ronald']"
        )
        parsed = parse_divergence_line(line)
        self.assertEqual(parsed["fields"]["project"]["resolver"], "vadim")
        self.assertEqual(parsed["fields"]["project"]["pipeline"], "ronald")


if __name__ == "__main__":
    unittest.main()
