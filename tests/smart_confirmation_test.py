"""Tests for services.smart_confirmation (Fase 3 context-aware prompts)."""

import unittest

from services.smart_confirmation import (
    build_wallet_question,
    build_project_question,
    summarize_known_context,
)


class SmartConfirmationTests(unittest.TestCase):
    def test_wallet_question_mentions_project(self):
        msg = build_wallet_question(
            project="Ronald",
            transactions=[{"keterangan": "fee tukang", "jumlah": 500000}],
            base_prompt="1. CV HB\n2. TX SBY\n3. TX BALI",
        )
        self.assertIn("Ronald", msg)
        self.assertIn("dompet mana", msg.lower())
        self.assertIn("TX SBY", msg)  # base prompt preserved
        self.assertIn("500.000", msg)  # rupiah formatting

    def test_wallet_question_without_project(self):
        msg = build_wallet_question(
            transactions=[{"keterangan": "beli semen", "jumlah": 150000}],
            base_prompt="1. CV HB",
        )
        self.assertIn("dompet mana", msg.lower())
        self.assertIn("semen", msg)
        self.assertNotIn("Project", msg)

    def test_wallet_question_notes_debt_source(self):
        msg = build_wallet_question(
            project="Vadim",
            transactions=[{"keterangan": "material", "jumlah": 200000}],
            debt_source="CV HB(101)",
            base_prompt="1. CV HB",
        )
        self.assertIn("hutang", msg.lower())
        self.assertIn("CV HB(101)", msg)

    def test_wallet_question_falls_back_without_base_prompt(self):
        msg = build_wallet_question(project="X")
        self.assertIn("dompet mana", msg.lower())

    def test_project_question_with_suggestion_and_wallet(self):
        msg = build_project_question(
            suggested="Mural PVJ",
            wallet="CV HB(101)",
            transactions=[{"keterangan": "cat", "jumlah": 80000}],
        )
        self.assertIn("Mural PVJ", msg)
        self.assertIn("CV HB(101)", msg)

    def test_project_question_without_suggestion_asks_name(self):
        msg = build_project_question(wallet="TX SBY(216)")
        self.assertIn("namanya apa", msg.lower())
        self.assertIn("TX SBY(216)", msg)

    def test_summarize_known_context_full(self):
        s = summarize_known_context(
            project="Ronald", wallet="CV HB(101)", company="HOLLA", debt_source="TX BALI(087)"
        )
        self.assertIn("project Ronald", s)
        self.assertIn("dompet CV HB(101)", s)
        self.assertIn("pinjam dari TX BALI(087)", s)

    def test_summarize_known_context_empty(self):
        self.assertEqual(summarize_known_context(), "")

    def test_handles_missing_amounts_gracefully(self):
        # Non-numeric / missing jumlah must not crash.
        msg = build_wallet_question(
            project="X",
            transactions=[{"keterangan": "abc", "jumlah": "bukan angka"}, {}],
            base_prompt="1. CV HB",
        )
        self.assertIn("dompet mana", msg.lower())


if __name__ == "__main__":
    unittest.main()
