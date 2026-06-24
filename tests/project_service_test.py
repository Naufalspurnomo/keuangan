import time
import unittest

from services import project_service
from services import state_manager
from config.wallets import resolve_dompet_from_text


class ProjectServiceTests(unittest.TestCase):
    def setUp(self):
        self._old_cache = {
            "names": set(project_service._project_cache.get("names", set())),
            "records": list(project_service._project_cache.get("records", [])),
            "last_updated": project_service._project_cache.get("last_updated", 0),
            "ttl": project_service._project_cache.get("ttl", 300),
        }
        self._old_knowledge = {
            "projects": dict(state_manager._project_knowledge.get("projects", {})),
            "aliases": dict(state_manager._project_knowledge.get("aliases", {})),
        }
        state_manager._project_knowledge["projects"] = {}
        state_manager._project_knowledge["aliases"] = {}
        project_service._project_cache.update({
            "names": {
                "Holla - Mural PVJ",
                "TEXTURIN - Booth PVJ",
                "Holla - Workshop",
                "Holla - Bu Astri",
                "Grand Cayman",
            },
            "records": [
                {
                    "name": "Holla - Mural PVJ",
                    "base_name": "Mural PVJ",
                    "dompet": "CV HB(101)",
                    "company": "HOLLA",
                },
                {
                    "name": "TEXTURIN - Booth PVJ",
                    "base_name": "Booth PVJ",
                    "dompet": "TX SBY(216)",
                    "company": "TEXTURIN",
                },
                {
                    "name": "Holla - Workshop",
                    "base_name": "Workshop",
                    "dompet": "CV HB(101)",
                    "company": "HOLLA",
                },
                {
                    "name": "Holla - Bu Astri",
                    "base_name": "Bu Astri",
                    "dompet": "CV HB(101)",
                    "company": "HOLLA",
                },
                {
                    "name": "Grand Cayman",
                    "base_name": "Grand Cayman",
                    "dompet": "TX SBY(216)",
                    "company": "TEXTURIN-Surabaya",
                },
            ],
            "last_updated": time.time(),
            "ttl": 300,
        })

    def tearDown(self):
        project_service._project_cache.update(self._old_cache)
        state_manager._project_knowledge["projects"] = self._old_knowledge["projects"]
        state_manager._project_knowledge["aliases"] = self._old_knowledge["aliases"]

    def test_scoped_project_short_name_autofixes_unique_wallet_match(self):
        result = project_service.resolve_project_name(
            "pvj",
            dompet_sheet="CV HB(101)",
            company="HOLLA",
        )

        self.assertEqual(result["status"], "AUTO_FIX")
        self.assertEqual(result["final_name"], "Holla - Mural PVJ")

    def test_unscoped_project_short_name_stays_ambiguous_across_wallets(self):
        result = project_service.resolve_project_name("pvj")

        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["match_count"], 2)

    def test_debt_source_scope_fallback_finds_project_in_real_wallet(self):
        scoped = project_service.resolve_project_name(
            "Grand Cayman",
            dompet_sheet="CV HB(101)",
        )
        self.assertEqual(scoped["status"], "NEW")

        result = project_service.resolve_project_name_for_context(
            "Grand Cayman",
            dompet_sheet="CV HB(101)",
            debt_source_dompet="CV HB(101)",
        )

        self.assertEqual(result["status"], "EXACT")
        self.assertEqual(result["final_name"], "Grand Cayman")
        self.assertTrue(result["debt_source_scope_fallback"])

    def test_scoped_project_lookup_falls_back_to_unique_existing_project(self):
        scoped = project_service.resolve_project_name(
            "Bu Astri",
            dompet_sheet="TX SBY(216)",
        )
        self.assertEqual(scoped["status"], "NEW")

        result = project_service.resolve_project_name_for_context(
            "Bu Astri",
            dompet_sheet="TX SBY(216)",
        )

        self.assertEqual(result["status"], "EXACT")
        self.assertEqual(result["final_name"], "Holla - Bu Astri")
        self.assertTrue(result["scope_fallback"])

    def test_infers_existing_project_across_wrong_scope_from_explicit_text(self):
        result = project_service.infer_project_from_text_context(
            "rembus dan uang pp sby-batu-sby rio, projek bu astri",
            dompet_sheet="TX SBY(216)",
        )

        self.assertEqual(result["status"], "EXACT")
        self.assertEqual(result["final_name"], "Holla - Bu Astri")

    def test_travel_sby_text_does_not_select_tx_sby_wallet(self):
        self.assertIsNone(
            resolve_dompet_from_text(
                "rembus dan uang pp sby-batu-sby rio, projek bu astri"
            )
        )
        self.assertEqual(resolve_dompet_from_text("dompet sby"), "TX SBY(216)")
        self.assertEqual(resolve_dompet_from_text("tx sby"), "TX SBY(216)")

    def test_debt_words_are_invalid_project_names(self):
        for candidate in ["Pinjam", "utang", "minjam", "pakai"]:
            with self.subTest(candidate=candidate):
                result = project_service.resolve_project_name(candidate)
                self.assertEqual(result["status"], "INVALID")
                self.assertEqual(result["reason"], "generic_project_keyword")

    def test_infers_existing_project_from_full_text_without_project_keyword(self):
        result = project_service.infer_project_from_text_context(
            "fee tyo jesica grand cayman pinjam cv hb",
            dompet_sheet="CV HB(101)",
            debt_source_dompet="CV HB(101)",
        )

        self.assertEqual(result["status"], "EXACT")
        self.assertEqual(result["final_name"], "Grand Cayman")

    def test_infers_existing_project_from_typo_in_full_text(self):
        result = project_service.infer_project_from_text_context(
            "fee tyo jesica grand caiman pinjam cv hb",
            dompet_sheet="CV HB(101)",
            debt_source_dompet="CV HB(101)",
        )

        self.assertEqual(result["status"], "AUTO_FIX")
        self.assertEqual(result["final_name"], "Grand Cayman")


if __name__ == "__main__":
    unittest.main()
