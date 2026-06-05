import unittest

from services.finance_decision import decide_project_resolution


class FinanceDecisionTests(unittest.TestCase):
    def test_accepts_exact_project(self):
        decision = decide_project_resolution({
            "status": "EXACT",
            "final_name": "Holla - Workshop",
        })

        self.assertTrue(decision.should_accept)
        self.assertEqual(decision.final_name, "Holla - Workshop")

    def test_confirms_ambiguous_by_default(self):
        decision = decide_project_resolution({
            "status": "AMBIGUOUS",
            "final_name": "Holla - Mural PVJ",
            "match_count": 1,
        })

        self.assertTrue(decision.should_confirm)
        self.assertEqual(decision.suggested_name, "Holla - Mural PVJ")

    def test_accepts_unique_ambiguous_when_policy_allows(self):
        decision = decide_project_resolution(
            {
                "status": "AMBIGUOUS",
                "final_name": "Holla - Mural PVJ",
                "match_count": 1,
            },
            auto_accept_unique_ambiguous=True,
        )

        self.assertTrue(decision.should_accept)
        self.assertEqual(decision.final_name, "Holla - Mural PVJ")

    def test_new_project_is_explicit_action(self):
        decision = decide_project_resolution({
            "status": "NEW",
            "final_name": "Taman Beringas Selatan",
        })

        self.assertEqual(decision.action, "new")
        self.assertEqual(decision.final_name, "Taman Beringas Selatan")

    def test_invalid_project_name_is_missing_action(self):
        decision = decide_project_resolution({
            "status": "INVALID",
            "original": "Pinjam",
            "reason": "generic_project_keyword",
        })

        self.assertEqual(decision.action, "missing")
        self.assertEqual(decision.reason, "generic_project_keyword")


if __name__ == "__main__":
    unittest.main()
